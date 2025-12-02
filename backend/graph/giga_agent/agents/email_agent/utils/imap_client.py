"""
Асинхронный клиент для работы с IMAP
Основан на коде из PostFilter
"""

import asyncio
import imaplib
import email
from email import policy
from email.parser import BytesParser
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class IMAPClient:
    """Асинхронный клиент для работы с IMAP сервером"""
    
    def __init__(self, host: str, email: str, password: str):
        """
        Инициализация IMAP клиента
        
        Args:
            host: IMAP сервер (например, imap.hoster.ru)
            email: Email адрес
            password: Пароль
        """
        logger.info(f"[IMAP_CLIENT] IMAPClient.__init__: host={host}, email={email}, password={'***' if password else None}")
        self.host = host
        self.email = email
        self.password = password
        self.mail: Optional[imaplib.IMAP4_SSL] = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> bool:
        """
        Подключение к IMAP серверу
        
        Returns:
            True если подключение успешно, False иначе
        """
        logger.info(f"[IMAP_CLIENT] connect: начинаем подключение к IMAP: host={self.host}, email={self.email}")
        try:
            # Выполняем синхронную операцию в executor
            loop = asyncio.get_event_loop()
            logger.info(f"[IMAP_CLIENT] connect: создаем IMAP4_SSL соединение с {self.host}")
            self.mail = await loop.run_in_executor(
                None,
                lambda: imaplib.IMAP4_SSL(self.host)
            )
            logger.info(f"[IMAP_CLIENT] connect: выполняем login для {self.email}")
            await loop.run_in_executor(
                None,
                lambda: self.mail.login(self.email, self.password)
            )
            logger.info(f"[IMAP_CLIENT] connect: УСПЕШНО подключились к IMAP для {self.email} на {self.host}")
            return True
        except Exception as e:
            logger.error(f"[IMAP_CLIENT] connect: ОШИБКА подключения к IMAP для {self.email} на {self.host}: {e}", exc_info=True)
            return False
    
    async def disconnect(self):
        """Отключение от IMAP сервера"""
        if self.mail:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.mail.logout)
            except Exception as e:
                logger.warning(f"Ошибка при отключении от IMAP: {e}")
            finally:
                self.mail = None
    
    async def select_folder(self, folder: str = "inbox") -> bool:
        """
        Выбор папки
        
        Args:
            folder: Название папки (по умолчанию "inbox")
        
        Returns:
            True если папка выбрана успешно
        """
        if not self.mail:
            await self.connect()
        
        try:
            loop = asyncio.get_event_loop()
            status, _ = await loop.run_in_executor(
                None,
                lambda: self.mail.select(folder)
            )
            return status == 'OK'
        except Exception as e:
            logger.error(f"Ошибка выбора папки {folder}: {e}")
            return False
    
    async def search_unseen(self) -> List[bytes]:
        """
        Поиск непрочитанных писем
        
        Returns:
            Список ID непрочитанных писем
        """
        if not self.mail:
            await self.select_folder()
        
        try:
            loop = asyncio.get_event_loop()
            status, messages = await loop.run_in_executor(
                None,
                lambda: self.mail.search(None, 'UNSEEN')
            )
            if status != 'OK':
                return []
            
            message_ids = messages[0].split() if messages[0] else []
            return message_ids
        except Exception as e:
            logger.error(f"Ошибка поиска непрочитанных писем: {e}")
            return []
    
    async def search_all(self, folder: str = "inbox") -> List[bytes]:
        """
        Поиск всех писем в папке
        
        Args:
            folder: Название папки
        
        Returns:
            Список ID всех писем
        """
        await self.select_folder(folder)
        
        try:
            loop = asyncio.get_event_loop()
            status, messages = await loop.run_in_executor(
                None,
                lambda: self.mail.search(None, 'ALL')
            )
            if status != 'OK':
                return []
            
            message_ids = messages[0].split() if messages[0] else []
            return message_ids
        except Exception as e:
            logger.error(f"Ошибка поиска всех писем: {e}")
            return []
    
    async def search_by_from(self, from_email: str, folder: str = "inbox") -> List[bytes]:
        """
        Поиск писем от конкретного отправителя
        
        Args:
            from_email: Email адрес отправителя
            folder: Название папки
        
        Returns:
            Список ID писем от указанного отправителя
        """
        await self.select_folder(folder)
        
        try:
            loop = asyncio.get_event_loop()
            # Используем IMAP команду FROM для поиска по отправителю
            # FROM "email@example.com" или FROM email@example.com
            search_criteria = f'FROM "{from_email}"'
            status, messages = await loop.run_in_executor(
                None,
                lambda: self.mail.search(None, 'CHARSET', 'UTF-8', search_criteria)
            )
            if status != 'OK':
                # Пробуем без кавычек
                try:
                    search_criteria = f'FROM {from_email}'
                    status, messages = await loop.run_in_executor(
                        None,
                        lambda: self.mail.search(None, search_criteria)
                    )
                except:
                    pass
            
            if status != 'OK':
                return []
            
            message_ids = messages[0].split() if messages[0] else []
            return message_ids
        except Exception as e:
            logger.error(f"Ошибка поиска писем от {from_email}: {e}")
            return []
    
    async def search_by_keywords(self, keywords: str, folder: str = "inbox", search_in: str = "TEXT") -> List[bytes]:
        """
        Поиск писем по ключевым словам
        
        Args:
            keywords: Ключевые слова для поиска
            folder: Название папки
            search_in: Где искать: "SUBJECT" (только тема), "BODY" (только тело), "TEXT" (тема и тело)
        
        Returns:
            Список ID писем, содержащих ключевые слова
        """
        await self.select_folder(folder)
        
        try:
            loop = asyncio.get_event_loop()
            # Используем IMAP команду для поиска по тексту
            # TEXT "keyword" - ищет в теме и теле
            # SUBJECT "keyword" - ищет только в теме
            # BODY "keyword" - ищет только в теле
            
            if search_in.upper() not in ["SUBJECT", "BODY", "TEXT"]:
                search_in = "TEXT"
            
            search_criteria = f'{search_in.upper()} "{keywords}"'
            status, messages = await loop.run_in_executor(
                None,
                lambda: self.mail.search(None, 'CHARSET', 'UTF-8', search_criteria)
            )
            if status != 'OK':
                # Пробуем без кавычек
                try:
                    search_criteria = f'{search_in.upper()} {keywords}'
                    status, messages = await loop.run_in_executor(
                        None,
                        lambda: self.mail.search(None, search_criteria)
                    )
                except:
                    pass
            
            if status != 'OK':
                return []
            
            message_ids = messages[0].split() if messages[0] else []
            return message_ids
        except Exception as e:
            logger.error(f"Ошибка поиска писем по ключевым словам '{keywords}': {e}")
            return []
    
    async def search_combined(self, from_email: Optional[str] = None, keywords: Optional[str] = None, 
                             folder: str = "inbox", search_in: str = "TEXT") -> List[bytes]:
        """
        Комбинированный поиск писем по отправителю и/или ключевым словам
        
        Args:
            from_email: Email адрес отправителя (опционально)
            keywords: Ключевые слова для поиска (опционально)
            folder: Название папки
            search_in: Где искать ключевые слова: "SUBJECT", "BODY", "TEXT"
        
        Returns:
            Список ID писем, соответствующих критериям
        """
        await self.select_folder(folder)
        
        try:
            loop = asyncio.get_event_loop()
            criteria_parts = []
            
            # Добавляем критерий поиска по отправителю
            if from_email:
                criteria_parts.append(f'FROM "{from_email}"')
            
            # Добавляем критерий поиска по ключевым словам
            if keywords:
                if search_in.upper() not in ["SUBJECT", "BODY", "TEXT"]:
                    search_in = "TEXT"
                criteria_parts.append(f'{search_in.upper()} "{keywords}"')
            
            if not criteria_parts:
                # Если критериев нет, возвращаем все письма
                return await self.search_all(folder)
            
            # Объединяем критерии через AND
            search_criteria = ' '.join(criteria_parts)
            
            status, messages = await loop.run_in_executor(
                None,
                lambda: self.mail.search(None, 'CHARSET', 'UTF-8', search_criteria)
            )
            if status != 'OK':
                # Пробуем упрощенный вариант без кавычек
                try:
                    criteria_parts_simple = []
                    if from_email:
                        criteria_parts_simple.append(f'FROM {from_email}')
                    if keywords:
                        if search_in.upper() not in ["SUBJECT", "BODY", "TEXT"]:
                            search_in = "TEXT"
                        criteria_parts_simple.append(f'{search_in.upper()} {keywords}')
                    search_criteria = ' '.join(criteria_parts_simple)
                    status, messages = await loop.run_in_executor(
                        None,
                        lambda: self.mail.search(None, search_criteria)
                    )
                except:
                    pass
            
            if status != 'OK':
                return []
            
            message_ids = messages[0].split() if messages[0] else []
            return message_ids
        except Exception as e:
            logger.error(f"Ошибка комбинированного поиска писем: {e}")
            return []
    
    async def fetch_message(self, msg_id: bytes) -> Optional[email.message.EmailMessage]:
        """
        Получение письма по ID
        
        Args:
            msg_id: ID письма
        
        Returns:
            Объект письма или None
        """
        if not self.mail:
            await self.select_folder()
        
        try:
            loop = asyncio.get_event_loop()
            status, data = await loop.run_in_executor(
                None,
                lambda: self.mail.fetch(msg_id, '(RFC822)')
            )
            if status != 'OK' or not data:
                return None
            
            raw_email = data[0][1]
            msg = BytesParser(policy=policy.default).parsebytes(raw_email)
            return msg
        except Exception as e:
            logger.error(f"Ошибка получения письма {msg_id}: {e}")
            return None
    
    async def move_to_spam(self, msg_id: bytes) -> bool:
        """
        Перенос письма в папку Spam
        
        Args:
            msg_id: ID письма
        
        Returns:
            True если операция успешна
        """
        if not self.mail:
            await self.select_folder()
        
        try:
            loop = asyncio.get_event_loop()
            # Копируем в Spam
            status, _ = await loop.run_in_executor(
                None,
                lambda: self.mail.copy(msg_id, "Spam")
            )
            if status == 'OK':
                # Помечаем как удаленное
                await loop.run_in_executor(
                    None,
                    lambda: self.mail.store(msg_id, '+FLAGS', '\\Deleted')
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Ошибка переноса письма {msg_id} в Spam: {e}")
            return False
    
    async def mark_as_read(self, msg_id: bytes) -> bool:
        """
        Пометить письмо как прочитанное
        
        Args:
            msg_id: ID письма
        
        Returns:
            True если операция успешна
        """
        if not self.mail:
            await self.select_folder()
        
        try:
            loop = asyncio.get_event_loop()
            status, _ = await loop.run_in_executor(
                None,
                lambda: self.mail.store(msg_id, '+FLAGS', '\\Seen')
            )
            return status == 'OK'
        except Exception as e:
            logger.error(f"Ошибка пометки письма {msg_id} как прочитанного: {e}")
            return False
    
    async def move_to_trash(self, msg_id: bytes, folder: str = "inbox") -> bool:
        """
        Переместить письмо в корзину (Trash)
        
        Args:
            msg_id: ID письма
            folder: Текущая папка письма
        
        Returns:
            True если операция успешна
        """
        if not self.mail:
            await self.select_folder(folder)
        
        try:
            loop = asyncio.get_event_loop()
            
            # Убеждаемся, что мы в правильной папке
            await self.select_folder(folder)
            
            # Получаем список папок для поиска корзины
            status, folders = await loop.run_in_executor(
                None,
                lambda: self.mail.list()
            )
            
            # Пробуем найти папку корзины (разные названия в разных почтовых системах)
            trash_folders = ["Trash", "Deleted", "Deleted Items", "Корзина", "Удаленные", "INBOX.Trash", "INBOX.Deleted"]
            trash_folder = None
            
            if status == 'OK':
                folder_names = []
                for folder_item in folders:
                    try:
                        folder_str = folder_item.decode('utf-8', errors='ignore')
                        parts = folder_str.split('"')
                        if len(parts) >= 3:
                            folder_name = parts[-2]
                            folder_names.append(folder_name)
                            
                            # Проверяем, есть ли папка корзины (более точное сравнение)
                            for trash_name in trash_folders:
                                # Проверяем точное совпадение или вхождение (без учета регистра)
                                if trash_name.lower() == folder_name.lower() or trash_name.lower() in folder_name.lower():
                                    trash_folder = folder_name
                                    logger.info(f"[IMAP_CLIENT] move_to_trash: найдена папка корзины: {trash_folder}")
                                    break
                        # Также пробуем парсить в другом формате (для некоторых серверов)
                        if not trash_folder:
                            try:
                                # Формат: (\\HasNoChildren) "/" "INBOX"
                                if '"' in folder_str:
                                    # Извлекаем название папки между кавычками
                                    import re
                                    matches = re.findall(r'"([^"]+)"', folder_str)
                                    if matches:
                                        potential_folder = matches[-1]
                                        for trash_name in trash_folders:
                                            if trash_name.lower() == potential_folder.lower() or trash_name.lower() in potential_folder.lower():
                                                trash_folder = potential_folder
                                                logger.info(f"[IMAP_CLIENT] move_to_trash: найдена папка корзины (альтернативный формат): {trash_folder}")
                                                break
                            except:
                                pass
                    except Exception as e:
                        logger.debug(f"[IMAP_CLIENT] move_to_trash: ошибка парсинга папки {folder_item}: {e}")
                        continue
            
            # Если нашли папку корзины, перемещаем туда
            if trash_folder:
                logger.info(f"[IMAP_CLIENT] move_to_trash: перемещаем письмо {msg_id} из папки {folder} в папку {trash_folder}")
                # Убеждаемся, что мы в правильной папке перед копированием
                await self.select_folder(folder)
                
                # Копируем письмо в корзину
                status, response = await loop.run_in_executor(
                    None,
                    lambda: self.mail.copy(msg_id, trash_folder)
                )
                logger.info(f"[IMAP_CLIENT] move_to_trash: результат копирования: status={status}, response={response}")
                
                if status == 'OK':
                    # Помечаем оригинал как удаленное
                    status_store, _ = await loop.run_in_executor(
                        None,
                        lambda: self.mail.store(msg_id, '+FLAGS', '\\Deleted')
                    )
                    logger.info(f"[IMAP_CLIENT] move_to_trash: результат пометки как удаленное: status={status_store}")
                    
                    if status_store == 'OK':
                        # Выполняем expunge для окончательного удаления из текущей папки
                        status_expunge, _ = await loop.run_in_executor(
                            None,
                            lambda: self.mail.expunge()
                        )
                        logger.info(f"[IMAP_CLIENT] move_to_trash: результат expunge: status={status_expunge}")
                        return True
                    else:
                        logger.warning(f"[IMAP_CLIENT] move_to_trash: не удалось пометить письмо как удаленное, но копирование прошло успешно")
                        return True  # Копирование прошло успешно, считаем операцию успешной
                else:
                    logger.warning(f"[IMAP_CLIENT] move_to_trash: не удалось скопировать в {trash_folder}, пробуем альтернативный метод")
            
            # Если папки корзины нет или копирование не удалось, используем альтернативный метод
            # Пробуем использовать MOVE команду (если поддерживается) или просто пометить как удаленное
            logger.info(f"[IMAP_CLIENT] move_to_trash: используем альтернативный метод - помечаем как удаленное")
            await self.select_folder(folder)
            
            # Помечаем письмо как удаленное
            status, _ = await loop.run_in_executor(
                None,
                lambda: self.mail.store(msg_id, '+FLAGS', '\\Deleted')
            )
            logger.info(f"[IMAP_CLIENT] move_to_trash: результат пометки как удаленное (альтернативный метод): status={status}")
            
            if status == 'OK':
                # Выполняем expunge для окончательного удаления
                status_expunge, _ = await loop.run_in_executor(
                    None,
                    lambda: self.mail.expunge()
                )
                logger.info(f"[IMAP_CLIENT] move_to_trash: результат expunge (альтернативный метод): status={status_expunge}")
                return True
            else:
                logger.error(f"[IMAP_CLIENT] move_to_trash: не удалось пометить письмо как удаленное: status={status}")
                return False
        except Exception as e:
            logger.error(f"Ошибка перемещения письма {msg_id} в корзину: {e}", exc_info=True)
            return False
    
    async def get_folders(self) -> List[str]:
        """
        Получение списка папок
        
        Returns:
            Список названий папок
        """
        if not self.mail:
            await self.connect()
        
        try:
            loop = asyncio.get_event_loop()
            status, folders = await loop.run_in_executor(
                None,
                lambda: self.mail.list()
            )
            if status != 'OK':
                return []
            
            folder_names = []
            for folder in folders:
                # Парсим строку папки (формат: '(\\HasNoChildren) "/" "INBOX"')
                # Или с кодировкой: '(\\HasNoChildren) "/" "&BB0ENQQ2BDUEOwQwBEIENQQ7BEwEPQQwBE8-"'
                try:
                    folder_str = folder.decode('utf-8', errors='ignore')
                    parts = folder_str.split('"')
                    if len(parts) >= 3:
                        folder_name = parts[-2]
                        
                        # Декодируем modified UTF-7 encoding (используется в IMAP для кириллицы)
                        if '&' in folder_name and folder_name.endswith('-'):
                            try:
                                # Modified UTF-7: & заменяется на +, &- это просто &
                                decoded = ""
                                i = 0
                                while i < len(folder_name):
                                    if folder_name[i] == '&':
                                        if i + 1 < len(folder_name) and folder_name[i + 1] == '-':
                                            decoded += '&'
                                            i += 2
                                        else:
                                            # Находим конец закодированного блока (до -)
                                            end = folder_name.find('-', i + 1)
                                            if end == -1:
                                                decoded += folder_name[i:]
                                                break
                                            # Извлекаем закодированную часть
                                            encoded = folder_name[i + 1:end]
                                            if encoded:
                                                try:
                                                    import base64
                                                    # Заменяем , на / для base64
                                                    encoded = encoded.replace(',', '/')
                                                    # Декодируем base64
                                                    decoded_bytes = base64.b64decode(encoded + '==')
                                                    # Декодируем UTF-16-BE
                                                    decoded += decoded_bytes.decode('utf-16-be', errors='ignore')
                                                except:
                                                    decoded += folder_name[i:end + 1]
                                            i = end + 1
                                    else:
                                        decoded += folder_name[i]
                                        i += 1
                                folder_name = decoded
                            except Exception as e:
                                logger.warning(f"Ошибка декодирования папки {folder_name}: {e}")
                        
                        # Также пробуем декодировать через email.header для MIME encoded слов
                        try:
                            from email.header import decode_header
                            decoded_parts = decode_header(folder_name)
                            if decoded_parts:
                                decoded_name = ""
                                for part, encoding in decoded_parts:
                                    if isinstance(part, bytes):
                                        if encoding:
                                            decoded_name += part.decode(encoding, errors='ignore')
                                        else:
                                            decoded_name += part.decode('utf-8', errors='ignore')
                                    else:
                                        decoded_name += part
                                folder_name = decoded_name
                        except:
                            pass
                        
                        folder_names.append(folder_name)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга папки {folder}: {e}")
                    continue
            
            return folder_names
        except Exception as e:
            logger.error(f"Ошибка получения списка папок: {e}")
            return []
    
    async def __aenter__(self):
        """Поддержка async context manager"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Поддержка async context manager"""
        await self.disconnect()

