"""
Telegram бот для доступа к системе Giga Agent
Поддерживает одного пользователя-админа по ID
Использует aiogram 3.x для работы с Telegram API
"""

import asyncio
import logging
import os
import re
import io
from typing import Optional, Set, Dict
from collections import defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, FSInputFile, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from langgraph_sdk import get_client
from langchain_core.messages import HumanMessage, AIMessage

# Импорты для простого режима QA
# В Docker контейнере giga_agent уже установлен как пакет
from giga_agent.utils.llm import load_llm
from giga_agent.utils.env import load_project_env


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clean_markdown(text: str) -> str:
    """
    Очищает текст от markdown форматирования для отправки в Telegram
    """
    if not text:
        return text
    
    # Удаляем заголовки (# ## ### и т.д.)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Удаляем жирный текст (**text** или __text__)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    
    # Удаляем курсив (*text* или _text_)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_(?!_)(.*?)(?<!_)_(?!_)', r'\1', text)
    
    # Удаляем зачеркнутый текст (~~text~~)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    
    # Удаляем inline код (`code`)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    # Удаляем блоки кода (```code```)
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # Удаляем ссылки [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Удаляем изображения ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
    
    # Удаляем списки (маркеры - * или 1.)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = re.sub(r'^[\s]*[-*+]\s+', '', line)
        line = re.sub(r'^[\s]*\d+\.\s+', '', line)
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)
    
    # Удаляем лишние пустые строки
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


# Получаем конфигурацию из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_USER_ID = os.getenv("TELEGRAM_ADMIN_USER_ID")
LANGGRAPH_API_URL = os.getenv("LANGGRAPH_API_URL", "http://langgraph-api:8000")

# Проверяем обязательные переменные
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
if not TELEGRAM_ADMIN_USER_ID:
    raise ValueError("TELEGRAM_ADMIN_USER_ID не установлен в переменных окружения")

# Преобразуем ID админа в int
try:
    ADMIN_USER_ID = int(TELEGRAM_ADMIN_USER_ID)
except ValueError:
    raise ValueError(f"TELEGRAM_ADMIN_USER_ID должен быть числом, получено: {TELEGRAM_ADMIN_USER_ID}")

# Инициализируем LangGraph клиент
langgraph_client = get_client(url=LANGGRAPH_API_URL)

# Хранилище thread_id для каждого пользователя
user_threads: Dict[int, Optional[str]] = {}

# Хранилище режимов работы для каждого пользователя ("qa" или "full")
user_modes: Dict[int, str] = defaultdict(lambda: "full")  # По умолчанию режим "full"

# Хранилище истории сообщений для режима QA
user_qa_history: Dict[int, list] = defaultdict(list)

# ID админа в системе (UUID из БД)
SYSTEM_ADMIN_USER_ID = os.getenv("TELEGRAM_SYSTEM_USER_ID")
if not SYSTEM_ADMIN_USER_ID:
    raise ValueError("TELEGRAM_SYSTEM_USER_ID не установлен в переменных окружения. Укажите UUID пользователя из БД.")

# Загружаем переменные окружения для LLM
load_project_env()

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id == ADMIN_USER_ID


def get_reply_keyboard() -> ReplyKeyboardMarkup:
    """Создает Reply keyboard с кнопками режимов"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📝 QA режим"),
                KeyboardButton(text="🔧 Full режим")
            ],
            [
                KeyboardButton(text="🆕 Новый чат")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard


class MessageTracker:
    """Отслеживает отправленные сообщения для предотвращения дублирования"""
    
    def __init__(self):
        self.seen_contents: Set[str] = set()
        self.message_ids: Dict[str, int] = {}  # content_key -> message_id для обновления
        
    def is_seen(self, content: str) -> bool:
        """Проверяет, было ли сообщение уже отправлено"""
        content_key = content[:100] if content else ""
        return content_key in self.seen_contents
    
    def mark_seen(self, content: str):
        """Отмечает сообщение как отправленное"""
        content_key = content[:100] if content else ""
        if content_key:
            self.seen_contents.add(content_key)
    
    def clear(self):
        """Очищает отслеживание"""
        self.seen_contents.clear()
        self.message_ids.clear()


# Хранилище трекеров для каждого пользователя
user_trackers: Dict[int, MessageTracker] = defaultdict(MessageTracker)


async def process_ai_message(
    msg: dict,
    tracker: MessageTracker,
    bot: Bot,
    chat_id: int,
    is_final: bool = False
) -> tuple[str, str]:
    """
    Обрабатывает AI сообщение и отправляет его пользователю
    
    Returns:
        tuple: (cleaned_text, original_markdown) для финального ответа
    """
    # Извлекаем content и reasoning
    content = str(msg.get("content", ""))
    additional_kwargs = msg.get("additional_kwargs", {})
    reasoning = ""
    
    if isinstance(additional_kwargs, dict):
        reasoning = str(additional_kwargs.get("reasoning_content", ""))
    
    # Удаляем теги thinking из content
    if content:
        content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
        content = content.strip()
    
    final_text = ""
    final_markdown = ""
    
    # Если это финальный ответ, всегда сохраняем markdown, даже если сообщение уже было отправлено
    if is_final and content:
        final_text = clean_markdown(content)
        final_markdown = content
        logger.info(f"Сохраняем финальный ответ для markdown, длина: {len(content)}")
        # Для финального ответа не проверяем is_seen - всегда возвращаем markdown
        return final_text, final_markdown
    
    # Проверяем, не отправляли ли уже это сообщение (только для нефинальных)
    content_key = content[:100] if content else ""
    if content_key and tracker.is_seen(content_key):
        return "", ""
    
    # Отмечаем как отправленное
    if content_key:
        tracker.mark_seen(content_key)
    
    # В режиме auto-approve без отладки не отправляем reasoning отдельно
    # Отправляем content, если есть
    if content:
        cleaned_content = clean_markdown(content)
        
        logger.info(f"Обработка сообщения для пользователя {chat_id}, длина: {len(cleaned_content)}, is_final: {is_final}")
        
        # Отправляем сообщение (всегда, не только финальные)
        if cleaned_content:
            # Повторные попытки отправки сообщения
            max_retries = 3
            retry_delay = 1.0
            for attempt in range(max_retries):
                try:
                    # Разбиваем на части если нужно (лимит Telegram - 4096 символов)
                    max_length = 4000
                    if len(cleaned_content) > max_length:
                        # Отправляем по частям
                        parts_count = (len(cleaned_content) + max_length - 1) // max_length
                        logger.info(f"Отправка сообщения по частям ({parts_count} частей) для пользователя {chat_id}")
                        for i in range(0, len(cleaned_content), max_length):
                            part = cleaned_content[i:i+max_length]
                            part_num = i // max_length + 1
                            logger.info(f"Отправка части {part_num}/{parts_count} для пользователя {chat_id}, длина: {len(part)}")
                            await bot.send_message(
                                chat_id=chat_id,
                                text=part,
                                parse_mode=ParseMode.HTML
                            )
                            logger.info(f"Часть {part_num}/{parts_count} успешно отправлена пользователю {chat_id}")
                    else:
                        logger.info(f"Отправка сообщения пользователю {chat_id}, длина: {len(cleaned_content)}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=cleaned_content,
                            parse_mode=ParseMode.HTML
                        )
                        logger.info(f"Сообщение успешно отправлено пользователю {chat_id}")
                    break  # Успешно отправлено, выходим из цикла
                except (TelegramNetworkError, TelegramBadRequest, Exception) as e:
                    logger.warning(f"Ошибка при отправке ответа (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Увеличиваем задержку экспоненциально
                    else:
                        logger.error(f"Не удалось отправить ответ после {max_retries} попыток: {e}")
    
    return final_text, final_markdown


async def process_qa_message(
    message_text: str,
    user_id: int,
    bot: Bot,
    chat_id: int
) -> str:
    """
    Обрабатывает сообщение в режиме QA - простой запрос к LLM без инструментов
    
    Returns:
        str: Ответ от LLM
    """
    try:
        # Загружаем LLM
        llm = load_llm()
        
        # Получаем историю сообщений для пользователя
        history = user_qa_history[user_id]
        
        # Добавляем новое сообщение пользователя
        history.append(HumanMessage(content=message_text))
        
        # Отправляем запрос к LLM
        response = await llm.ainvoke(history)
        
        # Извлекаем ответ
        if isinstance(response, AIMessage):
            answer = response.content
        else:
            answer = str(response)
        
        # Удаляем теги thinking из ответа
        answer = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', answer, flags=re.IGNORECASE)
        answer = answer.strip()
        
        # Добавляем ответ в историю
        history.append(AIMessage(content=answer))
        
        # Ограничиваем размер истории (последние 20 сообщений)
        if len(history) > 20:
            history = history[-20:]
            user_qa_history[user_id] = history
        
        return answer
        
    except Exception as e:
        logger.error(f"Ошибка при обработке QA запроса: {e}", exc_info=True)
        raise


async def stream_langgraph_messages(
    thread_id: str,
    message: HumanMessage,
    configurable: dict,
    tracker: MessageTracker,
    bot: Bot,
    chat_id: int
) -> tuple[dict, str]:
    """
    Стримит сообщения от LangGraph API и отправляет их пользователю
    
    Returns:
        tuple: (result_state, final_markdown)
    """
    result_state = {}
    final_markdown = ""
    stream_timeout = 300.0  # 5 минут
    
    try:
        async for chunk in langgraph_client.runs.stream(
            thread_id=thread_id,
            assistant_id="chat",
            input={"messages": [message]},
            stream_mode=["values", "messages"],
            on_disconnect="continue",
            config={"configurable": configurable},
        ):
            if chunk.event == "values":
                result_state = chunk.data
                messages = result_state.get("messages", [])
                if messages:
                    # Обрабатываем все AI сообщения
                    for msg_item in messages:
                        # Преобразуем сообщение в dict если нужно
                        if not isinstance(msg_item, dict):
                            msg_dict = {
                                "content": str(getattr(msg_item, "content", "")),
                                "type": getattr(msg_item, "type", None),
                                "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                            }
                        else:
                            msg_dict = msg_item
                        
                        msg_type = msg_dict.get("type")
                        if msg_type == "ai":
                            _, markdown = await process_ai_message(
                                msg_dict,
                                tracker,
                                bot,
                                chat_id,
                                is_final=False
                            )
                            if markdown:
                                final_markdown = markdown
            
            elif chunk.event == "messages":
                # Обрабатываем новые сообщения напрямую
                if hasattr(chunk, "data") and chunk.data:
                    new_messages = chunk.data.get("messages", []) if isinstance(chunk.data, dict) else []
                    if new_messages:
                        for msg_item in new_messages:
                            # Преобразуем сообщение в dict если нужно
                            if not isinstance(msg_item, dict):
                                msg_dict = {
                                    "content": str(getattr(msg_item, "content", "")),
                                    "type": getattr(msg_item, "type", None),
                                    "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                                }
                            else:
                                msg_dict = msg_item
                            
                            msg_type = msg_dict.get("type")
                            if msg_type == "ai":
                                _, markdown = await process_ai_message(
                                    msg_dict,
                                    tracker,
                                    bot,
                                    chat_id,
                                    is_final=False
                                )
                                if markdown:
                                    final_markdown = markdown
            
            if chunk.event == "end":
                # Получаем финальное состояние
                if not result_state:
                    try:
                        history = await langgraph_client.threads.get_state(thread_id=thread_id)
                        if history and "values" in history:
                            result_state = history["values"]
                    except Exception as e:
                        logger.warning(f"Не удалось получить финальное состояние: {e}")
                break
            
            # Обрабатываем прерывания (interrupts) - при autoapprove=True автоматически продолжаются
            # При autoapprove=True в configurable interrupts должны автоматически продолжаться
            # Просто продолжаем стрим
            if chunk.event == "interrupt":
                continue
        
        # После завершения стрима обрабатываем финальное состояние
        # Убеждаемся, что все сообщения отправлены, включая финальный ответ
        logger.info(f"Обработка финального состояния для пользователя {chat_id}, result_state пуст: {not result_state}")
        if result_state:
            messages = result_state.get("messages", [])
            logger.info(f"Найдено сообщений в финальном состоянии: {len(messages)} для пользователя {chat_id}")
            if messages:
                # Обрабатываем все AI сообщения еще раз, чтобы убедиться, что финальный ответ отправлен
                # Ищем последнее длинное AI сообщение для финального ответа
                last_ai_message = None
                all_ai_messages = []
                for msg_item in messages:
                    # Преобразуем сообщение в dict если нужно
                    if not isinstance(msg_item, dict):
                        msg_dict = {
                            "content": str(getattr(msg_item, "content", "")),
                            "type": getattr(msg_item, "type", None),
                            "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                        }
                    else:
                        msg_dict = msg_item
                    
                    msg_type = msg_dict.get("type")
                    if msg_type == "ai":
                        # Сохраняем оригинальный content до очистки для markdown файла
                        original_content = str(msg_dict.get("content", ""))
                        if original_content:
                            # Удаляем thinking теги только для проверки длины
                            content_cleaned = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', original_content, flags=re.IGNORECASE)
                            content_cleaned = content_cleaned.strip()
                            all_ai_messages.append((len(content_cleaned), msg_dict, original_content))
                            if content_cleaned and len(content_cleaned) >= 200:
                                # Это потенциально финальный ответ - сохраняем с оригинальным content
                                if not last_ai_message or len(content_cleaned) > len(str(last_ai_message.get("content", ""))):
                                    last_ai_message = {**msg_dict, "content": original_content}
                
                # Всегда обрабатываем последний AI ответ как финальный
                # Сначала пытаемся найти длинное сообщение (>= 200 символов)
                if last_ai_message:
                    logger.info(f"Обработка финального ответа длиной {len(last_ai_message.get('content', ''))} для пользователя {chat_id}")
                    # last_ai_message уже содержит оригинальный content
                    _, markdown = await process_ai_message(
                        last_ai_message,
                        tracker,
                        bot,
                        chat_id,
                        is_final=True
                    )
                    if markdown:
                        final_markdown = markdown
                        logger.info(f"Финальный ответ обработан, markdown длина: {len(markdown)}")
                # Если не нашли длинное сообщение, берем последнее AI сообщение
                elif all_ai_messages:
                    all_ai_messages.sort(key=lambda x: x[0], reverse=True)
                    last_msg_dict = all_ai_messages[0][1]
                    original_content = all_ai_messages[0][2]  # Оригинальный content сохранен в третьем элементе
                    last_msg_dict["content"] = original_content
                    logger.info(f"Обработка последнего AI сообщения длиной {len(original_content)} как финального для пользователя {chat_id}")
                    _, markdown = await process_ai_message(
                        last_msg_dict,
                        tracker,
                        bot,
                        chat_id,
                        is_final=True
                    )
                    if markdown:
                        final_markdown = markdown
                        logger.info(f"Последний AI ответ обработан как финальный, markdown длина: {len(markdown)}")
        else:
            # Пытаемся получить состояние из истории
            try:
                history = await langgraph_client.threads.get_state(thread_id=thread_id)
                if history and "values" in history:
                    result_state = history["values"]
                    messages = result_state.get("messages", [])
                    if messages:
                        # Ищем последнее AI сообщение
                        for msg_item in reversed(messages):
                            if not isinstance(msg_item, dict):
                                msg_dict = {
                                    "content": str(getattr(msg_item, "content", "")),
                                    "type": getattr(msg_item, "type", None),
                                    "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                                }
                            else:
                                msg_dict = msg_item
                            
                            msg_type = msg_dict.get("type")
                            if msg_type == "ai":
                                content = str(msg_dict.get("content", ""))
                                if content:
                                    content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
                                    content = content.strip()
                                    if content:
                                        msg_dict["content"] = content
                                        _, markdown = await process_ai_message(
                                            msg_dict,
                                            tracker,
                                            bot,
                                            chat_id,
                                            is_final=True
                                        )
                                        if markdown:
                                            final_markdown = markdown
                                        break
            except Exception as e:
                logger.error(f"Ошибка при получении состояния из истории: {e}")
        
        # Убеждаемся, что финальный ответ всегда выведен
        # Если final_markdown все еще пуст, пытаемся найти последний AI ответ
        if not final_markdown and result_state:
            logger.info(f"Финальный markdown пуст, ищем последний AI ответ для пользователя {chat_id}")
            messages = result_state.get("messages", [])
            if messages:
                # Ищем последнее AI сообщение
                for msg_item in reversed(messages):
                    if not isinstance(msg_item, dict):
                        msg_dict = {
                            "content": str(getattr(msg_item, "content", "")),
                            "type": getattr(msg_item, "type", None),
                            "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                        }
                    else:
                        msg_dict = msg_item
                    
                    msg_type = msg_dict.get("type")
                    if msg_type == "ai":
                        content = str(msg_dict.get("content", ""))
                        if content:
                            content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
                            content = content.strip()
                            if content:
                                logger.info(f"Найдено AI сообщение длиной {len(content)} для финального ответа пользователя {chat_id}")
                                msg_dict["content"] = content
                                _, markdown = await process_ai_message(
                                    msg_dict,
                                    tracker,
                                    bot,
                                    chat_id,
                                    is_final=True
                                )
                                if markdown:
                                    final_markdown = markdown
                                    logger.info(f"Финальный ответ найден и обработан, markdown длина: {len(markdown)}")
                                break
        
        return result_state, final_markdown
        
    except asyncio.TimeoutError:
        logger.error(f"Таймаут стрима LangGraph для пользователя {chat_id}")
        # Пытаемся получить последнее состояние
        try:
            history = await langgraph_client.threads.get_state(thread_id=thread_id)
            if history and "values" in history:
                result_state = history["values"]
                messages = result_state.get("messages", [])
                if messages:
                    # Ищем последнее AI сообщение
                    for msg_item in reversed(messages):
                        if not isinstance(msg_item, dict):
                            msg_dict = {
                                "content": str(getattr(msg_item, "content", "")),
                                "type": getattr(msg_item, "type", None),
                                "additional_kwargs": getattr(msg_item, "additional_kwargs", {})
                            }
                        else:
                            msg_dict = msg_item
                        
                        msg_type = msg_dict.get("type")
                        if msg_type == "ai":
                            content = str(msg_dict.get("content", ""))
                            if content:
                                content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', content, flags=re.IGNORECASE)
                                content = content.strip()
                                if content:
                                    msg_dict["content"] = content
                                    _, markdown = await process_ai_message(
                                        msg_dict,
                                        tracker,
                                        bot,
                                        chat_id,
                                        is_final=True
                                    )
                                    if markdown:
                                        final_markdown = markdown
                                    break
        except Exception as e:
            logger.error(f"Не удалось получить состояние из истории: {e}")
        
        return result_state, final_markdown


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен. Вы не являетесь администратором системы.")
        logger.warning(f"Попытка доступа от неавторизованного пользователя: {user_id}")
        return
    
    # Устанавливаем режим по умолчанию
    user_modes[user_id] = "full"
    
    await message.answer(
        f"✅ Добро пожаловать, администратор!\n\n"
        f"Я готов обрабатывать ваши запросы к системе Giga Agent.\n\n"
        f"Режимы работы:\n"
        f"📝 QA режим - простой запрос к LLM без инструментов\n"
        f"🔧 Full режим - полный режим с инструментами и агентами\n\n"
        f"Используйте кнопки ниже для выбора режима или команды:\n"
        f"/qa - переключиться на QA режим\n"
        f"/full - переключиться на Full режим\n"
        f"/new - начать новый чат",
        reply_markup=get_reply_keyboard()
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    current_mode = user_modes[user_id]
    await message.answer(
        "📖 Справка по использованию бота:\n\n"
        f"Текущий режим: {'📝 QA' if current_mode == 'qa' else '🔧 Full'}\n\n"
        "Режимы работы:\n"
        "📝 QA режим - простой запрос к LLM, быстрый ответ без инструментов\n"
        "🔧 Full режим - полный режим с инструментами, агентами и возможностями системы\n\n"
        "Команды:\n"
        "/qa - переключиться на QA режим\n"
        "/full - переключиться на Full режим\n"
        "/new - начать новый чат (сбросить контекст)\n"
        "/help - эта справка\n\n"
        "Используйте кнопки для быстрого переключения режимов.",
        reply_markup=get_reply_keyboard()
    )


@dp.message(Command("qa"))
async def cmd_qa(message: Message):
    """Обработчик команды /qa - переключение на QA режим"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    user_modes[user_id] = "qa"
    await message.answer(
        "📝 Переключено на QA режим\n\n"
        "В этом режиме запросы обрабатываются напрямую через LLM без использования инструментов.\n"
        "Быстрый и простой режим для вопросов и ответов.",
        reply_markup=get_reply_keyboard()
    )


@dp.message(Command("full"))
async def cmd_full(message: Message):
    """Обработчик команды /full - переключение на Full режим"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    user_modes[user_id] = "full"
    await message.answer(
        "🔧 Переключено на Full режим\n\n"
        "В этом режиме используются все возможности системы:\n"
        "- Инструменты и агенты\n"
        "- Поиск в интернете\n"
        "- Работа с файлами\n"
        "- И другие возможности Giga Agent",
        reply_markup=get_reply_keyboard()
    )


@dp.message(Command("new"))
async def cmd_new(message: Message):
    """Обработчик команды /new - начинает новый диалог"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен.")
        return
    
    # Сбрасываем thread_id и трекер для пользователя
    user_threads[user_id] = None
    user_trackers[user_id].clear()
    
    # Сбрасываем историю QA режима
    user_qa_history[user_id] = []
    
    await message.answer(
        "🆕 Новый чат начат. Контекст предыдущего разговора сброшен.",
        reply_markup=get_reply_keyboard()
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message):
    """Обработчик текстовых сообщений"""
    user_id = message.from_user.id
    message_text = message.text
    
    # Проверяем права доступа
    if not is_admin(user_id):
        await message.answer("❌ Доступ запрещен. Вы не являетесь администратором системы.")
        logger.warning(f"Попытка доступа от неавторизованного пользователя: {user_id}")
        return
    
    # Обработка кнопок Reply keyboard
    if message_text == "📝 QA режим":
        user_modes[user_id] = "qa"
        await message.answer(
            "📝 Переключено на QA режим",
            reply_markup=get_reply_keyboard()
        )
        return
    elif message_text == "🔧 Full режим":
        user_modes[user_id] = "full"
        await message.answer(
            "🔧 Переключено на Full режим",
            reply_markup=get_reply_keyboard()
        )
        return
    elif message_text == "🆕 Новый чат":
        # Сбрасываем контекст
        user_threads[user_id] = None
        user_trackers[user_id].clear()
        user_qa_history[user_id] = []
        await message.answer(
            "🆕 Новый чат начат. Контекст сброшен.",
            reply_markup=get_reply_keyboard()
        )
        return
    
    # Получаем текущий режим пользователя
    current_mode = user_modes[user_id]
    
    # Если режим QA, обрабатываем простым запросом к LLM
    if current_mode == "qa":
        await handle_qa_message(message, message_text, user_id)
        return
    
    # Иначе обрабатываем в Full режиме (текущая логика)
    await handle_full_message(message, message_text, user_id)
    
async def handle_qa_message(message: Message, message_text: str, user_id: int):
    """Обработчик сообщений в режиме QA"""
    processing_msg = None
    try:
        processing_msg = await message.answer("⏳ Обрабатываю запрос...")
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение 'Обрабатываю запрос...': {e}")
    
    try:
        # Обрабатываем запрос в режиме QA
        answer = await process_qa_message(
            message_text=message_text,
            user_id=user_id,
            bot=bot,
            chat_id=message.chat.id
        )
        
        # Сохраняем оригинальный ответ для MD файла (до очистки markdown)
        original_answer = answer
        
        # Очищаем markdown для отправки в Telegram
        cleaned_answer = clean_markdown(answer)
        
        # Отправляем ответ
        max_length = 4000
        if len(cleaned_answer) > max_length:
            # Отправляем по частям
            parts = [cleaned_answer[i:i+max_length] for i in range(0, len(cleaned_answer), max_length)]
            for i, part in enumerate(parts):
                # Добавляем клавиатуру только к последней части
                if i == len(parts) - 1:
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=part,
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_reply_keyboard()
                    )
                else:
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=part,
                        parse_mode=ParseMode.HTML
                    )
        else:
            await message.answer(cleaned_answer, parse_mode=ParseMode.HTML, reply_markup=get_reply_keyboard())
        
        # Отправляем markdown файл с полным ответом
        # Прикрепляем к последней части ответа (если ответ больше лимита) или к единственному сообщению (если ответ меньше лимита)
        logger.info(f"Проверка markdown для QA режима пользователя {user_id}, длина: {len(original_answer) if original_answer else 0}")
        if original_answer:
            logger.info(f"Отправка markdown файла в QA режиме пользователю {user_id}, длина: {len(original_answer)}")
            # Повторные попытки отправки markdown файла
            max_retries = 3
            retry_delay = 1.0
            for attempt in range(max_retries):
                try:
                    markdown_bytes = original_answer.encode('utf-8')
                    markdown_file = BufferedInputFile(
                        file=markdown_bytes,
                        filename="response.md"
                    )
                    
                    await bot.send_document(
                        chat_id=message.chat.id,
                        document=markdown_file,
                        caption="📄 Полный ответ в формате Markdown",
                        reply_markup=get_reply_keyboard()
                    )
                    logger.info(f"Markdown файл успешно отправлен пользователю {user_id} в QA режиме")
                    break  # Успешно отправлено
                except (TelegramNetworkError, TelegramBadRequest, Exception) as e:
                    logger.warning(f"Ошибка при отправке markdown файла в QA режиме (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"Не удалось отправить markdown файл в QA режиме после {max_retries} попыток: {e}")
        else:
            logger.warning(f"Оригинальный ответ пуст для пользователя {user_id} в QA режиме, файл не будет отправлен")
        
        # Удаляем сообщение "Обрабатываю запрос..."
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Ошибка при обработке QA сообщения от пользователя {user_id}: {e}", exc_info=True)
        
        # Удаляем сообщение "Обрабатываю запрос..." если оно было отправлено
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        
        # Отправляем сообщение об ошибке
        error_message = f"❌ Произошла ошибка при обработке запроса: {str(e)[:500]}"
        try:
            await message.answer(error_message)
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")


async def handle_full_message(message: Message, message_text: str, user_id: int):
    """Обработчик сообщений в режиме Full"""
    # Отправляем сообщение о том, что запрос обрабатывается
    processing_msg = None
    try:
        processing_msg = await message.answer("⏳ Обрабатываю запрос...")
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение 'Обрабатываю запрос...': {e}")
    
    try:
        # Получаем или создаем thread_id для пользователя
        thread_id = user_threads.get(user_id)
        
        if not thread_id:
            # Создаем новый поток
            thread = await langgraph_client.threads.create()
            thread_id = thread["thread_id"]
            user_threads[user_id] = thread_id
        
        # Получаем трекер для пользователя
        tracker = user_trackers[user_id]
        
        # Формируем сообщение для LangGraph
        langgraph_message = HumanMessage(
            content=message_text,
            additional_kwargs={
                "user_input": message_text,
            }
        )
        
        # Конфигурация с user_id админа из БД и autoapprove по умолчанию
        configurable = {
            "user_id": SYSTEM_ADMIN_USER_ID,
            "autoapprove": True
        }
        
        
        # Стримим сообщения от LangGraph
        result_state, final_markdown = await stream_langgraph_messages(
            thread_id=thread_id,
            message=langgraph_message,
            configurable=configurable,
            tracker=tracker,
            bot=bot,
            chat_id=message.chat.id
        )
        
        # Отправляем markdown файл только к финальному ответу
        logger.info(f"Проверка финального markdown для пользователя {user_id}, длина: {len(final_markdown) if final_markdown else 0}")
        if final_markdown:
            logger.info(f"Отправка markdown файла пользователю {user_id}, длина: {len(final_markdown)}")
            # Повторные попытки отправки markdown файла
            max_retries = 3
            retry_delay = 1.0
            for attempt in range(max_retries):
                try:
                    markdown_bytes = final_markdown.encode('utf-8')
                    markdown_file = BufferedInputFile(
                        file=markdown_bytes,
                        filename="response.md"
                    )
                    
                    await bot.send_document(
                        chat_id=message.chat.id,
                        document=markdown_file,
                        caption="📄 Полный ответ в формате Markdown",
                        reply_markup=get_reply_keyboard()
                    )
                    logger.info(f"Markdown файл успешно отправлен пользователю {user_id}")
                    break  # Успешно отправлено
                except (TelegramNetworkError, TelegramBadRequest, Exception) as e:
                    logger.warning(f"Ошибка при отправке markdown файла (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"Не удалось отправить markdown файл после {max_retries} попыток: {e}")
        else:
            logger.warning(f"Финальный markdown пуст для пользователя {user_id}, файл не будет отправлен")
        
        # Удаляем сообщение "Обрабатываю запрос..." только после получения результата
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception as e:
                pass
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения от пользователя {user_id}: {e}", exc_info=True)
        
        # Удаляем сообщение "Обрабатываю запрос..." если оно было отправлено
        if processing_msg:
            try:
                await processing_msg.delete()
            except Exception:
                pass
        
        # Отправляем сообщение об ошибке
        error_message = f"❌ Произошла ошибка при обработке запроса: {str(e)[:500]}"
        try:
            await message.answer(error_message)
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение об ошибке: {send_error}")


async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск Telegram бота...")
    logger.info(f"LangGraph API URL: {LANGGRAPH_API_URL}")
    logger.info(f"Telegram Admin User ID: {ADMIN_USER_ID}")
    logger.info(f"System Admin User ID (для запросов): {SYSTEM_ADMIN_USER_ID}")
    
    # Запускаем бота
    logger.info("✅ Telegram бот запущен и готов к работе")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
