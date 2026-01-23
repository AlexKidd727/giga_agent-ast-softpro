"""
Хранение конфигураций почтовых ящиков
Использует систему секретов проекта через state["secrets"]
"""

from typing import Dict, List, Optional
import logging

from giga_agent.agents.email_agent.utils.email_providers import get_default_email_settings

logger = logging.getLogger(__name__)


class EmailStorage:
    """Класс для работы с конфигурациями почтовых ящиков"""
    
    @staticmethod
    def get_email_config_from_secrets(secrets: List[Dict], email_account: Optional[str] = None) -> Optional[Dict]:
        """
        Получение конфигурации почтового ящика из секретов
        
        Args:
            secrets: Список секретов из state["secrets"]
            email_account: Email адрес ящика (если None, берется первый доступный)
        
        Returns:
            Конфигурация ящика или None
        """
        # Добавляем подробное логирование для отладки
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets вызван: email_account={email_account}")
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: secrets type={type(secrets)}, secrets length={len(secrets) if secrets else 0}")
        
        if not secrets:
            logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Секреты не переданы или пусты")
            return None
        
        # Проверяем, что secrets это список
        if not isinstance(secrets, list):
            logger.error(f"[EMAIL_STORAGE] get_email_config_from_secrets: ОШИБКА! Секреты должны быть списком, получен тип: {type(secrets)}")
            return None
        
        # Логируем первые несколько секретов для отладки (без значений паролей)
        if secrets:
            secret_names = [s.get("name", "unknown") for s in secrets[:20]]
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: имена секретов (первые 20): {secret_names}")
        
        # Ищем секреты, связанные с почтой
        # Собираем все секреты, которые могут быть связаны с почтой:
        # 1. Секреты с "email" или "mail" в имени
        # 2. Секреты с "_password", "_imap_host", "_smtp_host", "_imap_port", "_smtp_port" в имени
        # 3. Секреты, где значение содержит "@" и "." (email адрес)
        email_secrets = {}
        email_related_keywords = ["email", "mail", "password", "imap", "smtp", "port"]
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            value = secret.get("value", "")
            
            # Проверяем, связан ли секрет с почтой
            is_email_related = False
            
            # Проверяем ключевые слова в имени
            for keyword in email_related_keywords:
                if keyword in name:
                    is_email_related = True
                    break
            
            # Проверяем, является ли значение email адресом
            if "@" in value and "." in value:
                is_email_related = True
            
            if is_email_related:
                email_secrets[secret.get("name")] = secret.get("value")
        
        if not email_secrets:
            logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Не найдено секретов, связанных с почтой. Всего секретов: {len(secrets)}")
            # Логируем все имена секретов для отладки
            all_secret_names = [s.get("name", "unknown") for s in secrets]
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: все имена секретов: {all_secret_names}")
            return None
        
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: найдено {len(email_secrets)} email-связанных секретов")
        email_secret_names = list(email_secrets.keys())[:20]
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: имена email-связанных секретов (первые 20): {email_secret_names}")
        
        # Если указан конкретный ящик, ищем его конфигурацию
        if email_account:
            # Формируем ключи для поиска
            account_lower = email_account.lower().replace("@", "_").replace(".", "_")
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: ищем конфигурацию для конкретного ящика: {email_account}")
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: account_lower={account_lower}")
            
            # Ищем конфигурацию для этого ящика
            password_key1 = f"{account_lower}_password"
            password_key2 = "email_password"
            password = email_secrets.get(password_key1) or email_secrets.get(password_key2)
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: поиск пароля: {password_key1}={bool(email_secrets.get(password_key1))}, {password_key2}={bool(email_secrets.get(password_key2))}, результат={bool(password)}")
            
            imap_host_key1 = f"{account_lower}_imap_host"
            imap_host_key2 = "imap_host"
            imap_host = email_secrets.get(imap_host_key1) or email_secrets.get(imap_host_key2)
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: поиск imap_host: {imap_host_key1}={bool(email_secrets.get(imap_host_key1))}, {imap_host_key2}={bool(email_secrets.get(imap_host_key2))}, результат={imap_host}")
            
            smtp_host_key1 = f"{account_lower}_smtp_host"
            smtp_host_key2 = "smtp_host"
            smtp_host = email_secrets.get(smtp_host_key1) or email_secrets.get(smtp_host_key2)
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: поиск smtp_host: {smtp_host_key1}={bool(email_secrets.get(smtp_host_key1))}, {smtp_host_key2}={bool(email_secrets.get(smtp_host_key2))}, результат={smtp_host}")
            
            config = {
                "email": email_account,
                "password": password,
                "imap_host": imap_host,
                "smtp_host": smtp_host,
                "imap_port": int(email_secrets.get(f"{account_lower}_imap_port") or email_secrets.get("imap_port", "993")),
                "smtp_port": int(email_secrets.get(f"{account_lower}_smtp_port") or email_secrets.get("smtp_port", "587")),
            }
            
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: сформированная конфигурация для {email_account}: email={config['email']}, password={'***' if config['password'] else None}, imap_host={config['imap_host']}, smtp_host={config['smtp_host']}, imap_port={config['imap_port']}, smtp_port={config['smtp_port']}")
            
            # Если не хватает настроек сервера, используем типовые настройки
            if config["password"] and not config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: imap_host не найден, используем типовые настройки для {email_account}")
                default_settings = get_default_email_settings(email_account)
                config["imap_host"] = default_settings["imap_host"]
                config["imap_port"] = default_settings["imap_port"]
                if not config["smtp_host"]:
                    config["smtp_host"] = default_settings["smtp_host"]
                    config["smtp_port"] = default_settings["smtp_port"]
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: применены типовые настройки: imap_host={config['imap_host']}, smtp_host={config['smtp_host']}")
            
            # Проверяем, что есть обязательные поля
            if config["password"] and config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: УСПЕШНО найдена полная конфигурация для ящика: {email_account}")
                return config
            else:
                logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Неполная конфигурация для {email_account}: password={bool(config['password'])}, imap_host={bool(config['imap_host'])}, smtp_host={bool(config['smtp_host'])}")
        
        # Если не указан конкретный ящик, пытаемся найти первый доступный
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: email_account не указан, ищем первый доступный ящик")
        
        # ВАЖНО: Не полагаемся только на email_account из секретов, так как он может быть перезаписан
        # Вместо этого ищем все доступные ящики и выбираем первый с полной конфигурацией
        all_accounts = EmailStorage.get_all_email_accounts(secrets)
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: найдено доступных ящиков: {len(all_accounts)} - {all_accounts}")
        
        # Сортируем ящики по приоритету: сначала alexis@ts-group.ru, потом остальные
        # Это гарантирует, что при отсутствии указания в запросе будет выбран правильный ящик
        priority_accounts = []
        other_accounts = []
        for account in all_accounts:
            if "alexis@ts-group.ru" in account.lower():
                priority_accounts.insert(0, account)  # Добавляем в начало
            else:
                other_accounts.append(account)
        sorted_accounts = priority_accounts + other_accounts
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: отсортированные ящики по приоритету: {sorted_accounts}")
        
        # Пробуем каждый доступный ящик, начиная с приоритетных
        for potential_email in sorted_accounts:
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: проверяем ящик: {potential_email}")
            account_lower = potential_email.lower().replace("@", "_").replace(".", "_")
            
            password = email_secrets.get(f"{account_lower}_password") or email_secrets.get("email_password")
            imap_host = email_secrets.get(f"{account_lower}_imap_host") or email_secrets.get("imap_host")
            smtp_host = email_secrets.get(f"{account_lower}_smtp_host") or email_secrets.get("smtp_host")
            
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: для {potential_email}: password={bool(password)}, imap_host={imap_host}, smtp_host={smtp_host}")
            
            config = {
                "email": potential_email,
                "password": password,
                "imap_host": imap_host,
                "smtp_host": smtp_host,
                "imap_port": int(email_secrets.get(f"{account_lower}_imap_port") or email_secrets.get("imap_port", "993")),
                "smtp_port": int(email_secrets.get(f"{account_lower}_smtp_port") or email_secrets.get("smtp_port", "587")),
            }
            
            # Если не хватает настроек сервера, используем типовые настройки
            if config["password"] and not config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: imap_host не найден, используем типовые настройки для {potential_email}")
                default_settings = get_default_email_settings(potential_email)
                config["imap_host"] = default_settings["imap_host"]
                config["imap_port"] = default_settings["imap_port"]
                if not config["smtp_host"]:
                    config["smtp_host"] = default_settings["smtp_host"]
                    config["smtp_port"] = default_settings["smtp_port"]
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: применены типовые настройки: imap_host={config['imap_host']}, smtp_host={config['smtp_host']}")
            
            if config["password"] and config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: УСПЕШНО найдена конфигурация для ящика: {potential_email}")
                return config
            else:
                logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Неполная конфигурация для {potential_email}: password={bool(config['password'])}, imap_host={bool(config['imap_host'])}")
        
        # Fallback: если не нашли через get_all_email_accounts, пробуем email_account из секретов
        if "email_account" in email_secrets:
            potential_email = email_secrets["email_account"]
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: fallback - используем email_account секрет: {potential_email}")
            account_lower = potential_email.lower().replace("@", "_").replace(".", "_")
            
            password = email_secrets.get(f"{account_lower}_password") or email_secrets.get("email_password")
            imap_host = email_secrets.get(f"{account_lower}_imap_host") or email_secrets.get("imap_host")
            smtp_host = email_secrets.get(f"{account_lower}_smtp_host") or email_secrets.get("smtp_host")
            
            logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: для {potential_email}: password={bool(password)}, imap_host={imap_host}, smtp_host={smtp_host}")
            
            config = {
                "email": potential_email,
                "password": password,
                "imap_host": imap_host,
                "smtp_host": smtp_host,
                "imap_port": int(email_secrets.get(f"{account_lower}_imap_port") or email_secrets.get("imap_port", "993")),
                "smtp_port": int(email_secrets.get(f"{account_lower}_smtp_port") or email_secrets.get("smtp_port", "587")),
            }
            
            # Если не хватает настроек сервера, используем типовые настройки
            if config["password"] and not config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: imap_host не найден, используем типовые настройки для {potential_email}")
                default_settings = get_default_email_settings(potential_email)
                config["imap_host"] = default_settings["imap_host"]
                config["imap_port"] = default_settings["imap_port"]
                if not config["smtp_host"]:
                    config["smtp_host"] = default_settings["smtp_host"]
                    config["smtp_port"] = default_settings["smtp_port"]
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: применены типовые настройки: imap_host={config['imap_host']}, smtp_host={config['smtp_host']}")
            
            if config["password"] and config["imap_host"]:
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: УСПЕШНО найдена конфигурация для ящика через email_account (fallback): {potential_email}")
                return config
            else:
                logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Неполная конфигурация для {potential_email} через email_account (fallback): password={bool(config['password'])}, imap_host={bool(config['imap_host'])}")
        
        # Если email_account не найден, ищем секреты с email адресом в значении
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: email_account не найден, ищем секреты с суффиксом _email")
        # Ищем секреты с суффиксом _email (например, user_example_com_email)
        for secret_name, secret_value in email_secrets.items():
            if secret_name.endswith("_email") and "@" in secret_value and "." in secret_value:
                # Это секрет с email адресом
                potential_email = secret_value
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: найден секрет {secret_name} с email: {potential_email}")
                account_lower = potential_email.lower().replace("@", "_").replace(".", "_")
                
                password = email_secrets.get(f"{account_lower}_password") or email_secrets.get("email_password")
                imap_host = email_secrets.get(f"{account_lower}_imap_host") or email_secrets.get("imap_host")
                smtp_host = email_secrets.get(f"{account_lower}_smtp_host") or email_secrets.get("smtp_host")
                
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: для {potential_email}: password={bool(password)}, imap_host={imap_host}, smtp_host={smtp_host}")
                
                config = {
                    "email": potential_email,
                    "password": password,
                    "imap_host": imap_host,
                    "smtp_host": smtp_host,
                    "imap_port": int(email_secrets.get(f"{account_lower}_imap_port") or email_secrets.get("imap_port", "993")),
                    "smtp_port": int(email_secrets.get(f"{account_lower}_smtp_port") or email_secrets.get("smtp_port", "587")),
                }
                
                # Если не хватает настроек сервера, используем типовые настройки
                if config["password"] and not config["imap_host"]:
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: imap_host не найден, используем типовые настройки для {potential_email}")
                    default_settings = get_default_email_settings(potential_email)
                    config["imap_host"] = default_settings["imap_host"]
                    config["imap_port"] = default_settings["imap_port"]
                    if not config["smtp_host"]:
                        config["smtp_host"] = default_settings["smtp_host"]
                        config["smtp_port"] = default_settings["smtp_port"]
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: применены типовые настройки: imap_host={config['imap_host']}, smtp_host={config['smtp_host']}")
                
                if config["password"] and config["imap_host"]:
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: УСПЕШНО найдена конфигурация для ящика через {secret_name}: {potential_email}")
                    return config
                else:
                    logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Неполная конфигурация для {potential_email} через {secret_name}: password={bool(config['password'])}, imap_host={bool(config['imap_host'])}")
        
        # Последняя попытка - ищем любое значение с email адресом
        logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: последняя попытка - ищем любое значение с email адресом")
        for secret_name, secret_value in email_secrets.items():
            if "@" in secret_value and "." in secret_value and "," not in secret_value and len(secret_value) < 100:
                # Возможно, это email адрес (не список)
                potential_email = secret_value
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: найден потенциальный email в секрете {secret_name}: {potential_email}")
                account_lower = potential_email.lower().replace("@", "_").replace(".", "_")
                
                password = email_secrets.get(f"{account_lower}_password") or email_secrets.get("email_password")
                imap_host = email_secrets.get(f"{account_lower}_imap_host") or email_secrets.get("imap_host")
                smtp_host = email_secrets.get(f"{account_lower}_smtp_host") or email_secrets.get("smtp_host")
                
                logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: для {potential_email}: password={bool(password)}, imap_host={imap_host}, smtp_host={smtp_host}")
                
                config = {
                    "email": potential_email,
                    "password": password,
                    "imap_host": imap_host,
                    "smtp_host": smtp_host,
                    "imap_port": int(email_secrets.get(f"{account_lower}_imap_port") or email_secrets.get("imap_port", "993")),
                    "smtp_port": int(email_secrets.get(f"{account_lower}_smtp_port") or email_secrets.get("smtp_port", "587")),
                }
                
                # Если не хватает настроек сервера, используем типовые настройки
                if config["password"] and not config["imap_host"]:
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: imap_host не найден, используем типовые настройки для {potential_email}")
                    default_settings = get_default_email_settings(potential_email)
                    config["imap_host"] = default_settings["imap_host"]
                    config["imap_port"] = default_settings["imap_port"]
                    if not config["smtp_host"]:
                        config["smtp_host"] = default_settings["smtp_host"]
                        config["smtp_port"] = default_settings["smtp_port"]
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: применены типовые настройки: imap_host={config['imap_host']}, smtp_host={config['smtp_host']}")
                
                if config["password"] and config["imap_host"]:
                    logger.info(f"[EMAIL_STORAGE] get_email_config_from_secrets: УСПЕШНО найдена конфигурация для ящика: {potential_email}")
                    return config
                else:
                    logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ВНИМАНИЕ! Неполная конфигурация для {potential_email}: password={bool(config['password'])}, imap_host={bool(config['imap_host'])}")
        
        logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: ОШИБКА! Не удалось найти полную конфигурацию почтового ящика")
        logger.warning(f"[EMAIL_STORAGE] get_email_config_from_secrets: доступные email-связанные секреты: {list(email_secrets.keys())}")
        return None
    
    @staticmethod
    def get_all_email_accounts(secrets: List[Dict]) -> List[str]:
        """
        Получение списка всех доступных почтовых ящиков
        
        Args:
            secrets: Список секретов из state["secrets"]
        
        Returns:
            Список email адресов
        """
        if not secrets:
            return []
        
        accounts = []
        email_secrets = {}
        
        for secret in secrets:
            name = secret.get("name", "").lower()
            if "email" in name or "mail" in name:
                email_secrets[secret.get("name")] = secret.get("value")
        
        # Ищем уникальные email адреса
        # Исключаем списки email адресов
        found_emails = set()
        for secret_name, secret_value in email_secrets.items():
            if "@" in secret_value and "." in secret_value:
                # Проверяем, что это не список email адресов (не содержит запятые)
                # и не слишком длинный (списки обычно длиннее одного email)
                if "," not in secret_value and len(secret_value) < 100:
                    found_emails.add(secret_value)
        
        # Также ищем секреты с суффиксом _email (например, alexis_ts-group_ru_email)
        # которые содержат полный email адрес
        for secret in secrets:
            secret_name = secret.get("name", "").lower()
            secret_value = secret.get("value", "")
            # Ищем секреты типа "alexis_ts-group_ru_email" или "astuden_rambler_ru_email"
            if secret_name.endswith("_email") and "@" in secret_value and "." in secret_value:
                if "," not in secret_value and len(secret_value) < 100:
                    found_emails.add(secret_value)
                    logger.info(f"[EMAIL_STORAGE] get_all_email_accounts: найден ящик через секрет {secret.get('name')}: {secret_value}")
        
        logger.info(f"[EMAIL_STORAGE] get_all_email_accounts: найдено уникальных ящиков: {len(found_emails)} - {list(found_emails)}")
        return list(found_emails)
    
    @staticmethod
    def find_email_account_by_name(secrets: List[Dict], account_name: str) -> Optional[str]:
        """
        Поиск email адреса по частичному совпадению имени
        
        Args:
            secrets: Список секретов из state["secrets"]
            account_name: Часть имени ящика (например, "alexis" для поиска "alexis@ts-group.ru")
        
        Returns:
            Полный email адрес или None
        """
        if not secrets or not account_name:
            return None
        
        account_name_lower = account_name.lower().strip()
        logger.info(f"[EMAIL_STORAGE] find_email_account_by_name: ищем ящик по имени '{account_name_lower}'")
        
        # Получаем все доступные ящики
        all_accounts = EmailStorage.get_all_email_accounts(secrets)
        logger.info(f"[EMAIL_STORAGE] find_email_account_by_name: найдено доступных ящиков: {len(all_accounts)}")
        
        # Ищем ящик, который содержит указанное имя
        for email in all_accounts:
            email_lower = email.lower()
            # Проверяем, содержит ли email указанное имя
            # Например, "alexis" должно совпадать с "alexis@ts-group.ru"
            if account_name_lower in email_lower:
                # Проверяем, что это не случайное совпадение
                # Имя должно быть в начале email (до @) или быть частью домена
                email_parts = email_lower.split("@")
                if len(email_parts) == 2:
                    local_part = email_parts[0]
                    domain_part = email_parts[1]
                    # Проверяем, что имя совпадает с локальной частью или является её началом
                    if local_part.startswith(account_name_lower) or account_name_lower == local_part:
                        logger.info(f"[EMAIL_STORAGE] find_email_account_by_name: найдено совпадение: '{account_name_lower}' -> '{email}'")
                        return email
        
        logger.warning(f"[EMAIL_STORAGE] find_email_account_by_name: не найдено ящика по имени '{account_name_lower}'")
        return None
    
    @staticmethod
    def validate_config(config: Dict) -> bool:
        """
        Валидация конфигурации ящика
        
        Args:
            config: Конфигурация ящика
        
        Returns:
            True если конфигурация валидна
        """
        required_fields = ["email", "password", "imap_host"]
        
        for field in required_fields:
            if not config.get(field):
                logger.warning(f"Отсутствует обязательное поле: {field}")
                return False
        
        # Проверяем формат email
        email = config.get("email", "")
        if "@" not in email or "." not in email:
            logger.warning(f"Неверный формат email: {email}")
            return False
        
        return True

