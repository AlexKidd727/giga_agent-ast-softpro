"""
Инструмент персонализации для сохранения предпочтений, правил и фактов пользователя.

Используется, когда пользователь просит:
- "запомни", "возьми за правило", "запомни на будущее"
- "возьми за образец", "используй это как шаблон"
- "для меня важно", "я предпочитаю"
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Optional

from langchain_core.tools import tool
from pydantic import Field

# Импортируем InjectedState после других импортов, чтобы избежать проблем с Pydantic
from langgraph.prebuilt import InjectedState

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
async def personalize(
    fact_or_rule: Annotated[
        str,
        Field(
            description=(
                "Факт, правило или предпочтение, которое нужно сохранить. "
                "Например: 'Я предпочитаю темную тему', 'Всегда используй Python 3.11', "
                "'Мой любимый язык программирования - Python'"
            )
        ),
    ],
    key: Annotated[
        Optional[str],
        Field(
            description=(
                "Ключ для сохранения предпочтения. Если не указан, будет автоматически "
                "сгенерирован на основе факта. Например: 'theme_preference', 'python_version', "
                "'favorite_language'. Должен быть коротким и понятным."
            ),
        ),
    ] = None,
    state: "Annotated[dict, InjectedState]" = None,
) -> str:
    """
    Сохраняет факт, правило или предпочтение пользователя в его базовые предпочтения (basePreferences).
    
    Этот инструмент используется, когда пользователь просит запомнить что-то для будущего использования.
    Сохраненные предпочтения будут автоматически учитываться агентом при выполнении последующих задач.
    
    Args:
        fact_or_rule: Факт, правило или предпочтение для сохранения
        key: Опциональный ключ для сохранения. Если не указан, будет сгенерирован автоматически
        state: Состояние агента (автоматически инжектируется), содержит user_id
    
    Returns:
        Сообщение о результате сохранения предпочтения
    """
    if not state:
        return "Ошибка: не удалось получить состояние агента. Предпочтение не сохранено."
    
    # Получаем user_id из state
    user_id = state.get("user_id")
    logger.info(f"[PERSONALIZE] user_id из state: {user_id}")
    
    # Если user_id невалидный или отсутствует, пытаемся получить из Redis по thread_id
    if not user_id or user_id in ["default_user", "anonymous", "guest", ""]:
        thread_id = state.get("thread_id")
        if thread_id:
            try:
                from giga_agent.utils.redis_cache import get_user_id_from_session_by_thread
                cached_user_id = await get_user_id_from_session_by_thread(thread_id)
                if cached_user_id:
                    user_id = cached_user_id
                    logger.info(f"[PERSONALIZE] user_id={user_id} получен из Redis для thread_id={thread_id}")
            except Exception as e:
                logger.warning(f"[PERSONALIZE] Ошибка при получении user_id из Redis: {e}")
    
    # Нормализуем user_id (убираем невалидные значения)
    if user_id:
        from giga_agent.utils.user_tokens import _normalize_user_id
        user_id_before = user_id
        user_id = _normalize_user_id(user_id)
        if user_id != user_id_before:
            logger.info(f"[PERSONALIZE] user_id нормализован: {user_id_before} → {user_id}")
    
    # Проверяем, что user_id валиден
    if not user_id:
        return (
            "Не удалось определить пользователя. "
            "Предпочтение не может быть сохранено. "
            "Убедитесь, что вы авторизованы."
        )
    
    if not fact_or_rule or not fact_or_rule.strip():
        return "Ошибка: факт или правило не может быть пустым."
    
    try:
        from giga_agent.tasks_app import AsyncSessionLocal, User
        from sqlmodel import select
        
        async with AsyncSessionLocal() as session:
            # Получаем пользователя
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error(f"[PERSONALIZE] Пользователь не найден: user_id={user_id}")
                return f"Ошибка: пользователь с ID {user_id} не найден."
            
            logger.info(
                f"[PERSONALIZE] Начало сохранения предпочтения для user_id={user_id}, "
                f"fact_or_rule={fact_or_rule[:100]}, key={key}"
            )
            
            # Парсим существующие предпочтения
            preferences_dict = {}
            if user.user_preferences:
                try:
                    preferences_dict = json.loads(user.user_preferences)
                except json.JSONDecodeError:
                    logger.warning(
                        f"[PERSONALIZE] Не удалось распарсить user_preferences для user_id={user_id}, "
                        "создаем новый объект"
                    )
                    preferences_dict = {}
            
            # Инициализируем basePreferences, если его нет
            if "basePreferences" not in preferences_dict:
                preferences_dict["basePreferences"] = {}
            
            base_prefs = preferences_dict["basePreferences"]
            if not isinstance(base_prefs, dict):
                base_prefs = {}
                preferences_dict["basePreferences"] = base_prefs
            
            # Генерируем ключ, если не указан
            if not key or not key.strip():
                # Простая генерация ключа на основе первых слов факта
                words = fact_or_rule.strip().lower().split()[:3]
                key = "_".join(words).replace(",", "").replace(".", "").replace(":", "")
                # Ограничиваем длину ключа
                key = key[:50] if len(key) > 50 else key
                # Если ключ слишком короткий, используем дефолтный
                if len(key) < 3:
                    key = "preference_" + str(len(base_prefs) + 1)
            
            # Нормализуем ключ (убираем пробелы, специальные символы)
            key = key.strip().replace(" ", "_").replace("-", "_")
            # Убираем все кроме букв, цифр и подчеркиваний
            key = "".join(c for c in key if c.isalnum() or c == "_")
            if not key or not key[0].isalpha():
                key = "preference_" + key if key else "preference_1"
            
            # Сохраняем предпочтение
            base_prefs[key] = fact_or_rule.strip()
            
            # Обновляем предпочтения пользователя
            user.user_preferences = json.dumps(preferences_dict, ensure_ascii=False)
            
            # ВАЖНО: Явно добавляем объект в сессию для отслеживания изменений
            # Это гарантирует, что SQLAlchemy сохранит изменения в БД
            session.add(user)
            
            # Коммитим изменения
            await session.commit()
            
            # Обновляем объект из БД для проверки сохранения
            await session.refresh(user)
            
            # Проверяем, что предпочтения действительно сохранены
            saved_prefs = json.loads(user.user_preferences) if user.user_preferences else {}
            saved_base_prefs = saved_prefs.get("basePreferences", {})
            if key not in saved_base_prefs:
                logger.error(
                    f"[PERSONALIZE] КРИТИЧЕСКАЯ ОШИБКА: Предпочтение не сохранено в БД! "
                    f"user_id={user_id}, key={key}"
                )
                return (
                    f"⚠️ Ошибка: предпочтение не было сохранено в базу данных. "
                    f"Попробуйте еще раз или обратитесь к администратору."
                )
            
            logger.info(
                f"[PERSONALIZE] Сохранено предпочтение для user_id={user_id}: "
                f"key={key}, value={fact_or_rule[:100]}, "
                f"всего предпочтений в basePreferences: {len(saved_base_prefs)}"
            )
            
            return (
                f"✅ Предпочтение сохранено! "
                f"Ключ: '{key}'. "
                f"Значение: '{fact_or_rule.strip()}'. "
                f"Это предпочтение будет учитываться при выполнении будущих задач."
            )
    
    except Exception as e:
        logger.error(f"[PERSONALIZE] Ошибка при сохранении предпочтения: {e}", exc_info=True)
        return f"Ошибка при сохранении предпочтения: {str(e)}"

