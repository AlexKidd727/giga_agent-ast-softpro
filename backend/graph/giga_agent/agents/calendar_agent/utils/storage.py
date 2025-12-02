"""
Менеджер хранения данных для Google Calendar Agent
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class CalendarStorage:
    """Управление хранением данных календаря"""
    
    def __init__(self, storage_dir: str = "db/calendar"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.users_file = self.storage_dir / "users.json"
        self.tokens_file = self.storage_dir / "tokens.json"
        
        # Инициализируем файлы если их нет
        self._init_storage()
    
    def _init_storage(self):
        """Инициализация файлов хранения"""
        if not self.users_file.exists():
            self._save_json(self.users_file, {})
        if not self.tokens_file.exists():
            self._save_json(self.tokens_file, {})
    
    def _load_json(self, file_path: Path) -> Dict:
        """Загрузка JSON из файла"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Ошибка загрузки {file_path}: {e}")
            return {}
    
    def _save_json(self, file_path: Path, data: Dict):
        """Сохранение JSON в файл"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения {file_path}: {e}")
    
    def save_user_tokens(self, user_id: str, tokens: Dict[str, Any]):
        """Сохранение токенов пользователя"""
        tokens_data = self._load_json(self.tokens_file)
        
        # Добавляем время истечения токена
        if 'expires_in' in tokens:
            expires_at = datetime.now() + timedelta(seconds=tokens['expires_in'])
            tokens['expires_at'] = expires_at.isoformat()
        
        tokens_data[user_id] = tokens
        self._save_json(self.tokens_file, tokens_data)
        logger.info(f"💾 Токены сохранены для пользователя {user_id}")
    
    def get_user_tokens(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получение токенов пользователя"""
        tokens_data = self._load_json(self.tokens_file)
        return tokens_data.get(user_id)
    
    def save_user_profile(self, user_id: str, profile: Dict[str, Any]):
        """Сохранение профиля пользователя"""
        users_data = self._load_json(self.users_file)
        
        if user_id not in users_data:
            users_data[user_id] = {}
        
        users_data[user_id].update(profile)
        users_data[user_id]['last_updated'] = datetime.now().isoformat()
        
        self._save_json(self.users_file, users_data)
        logger.info(f"👤 Профиль сохранен для пользователя {user_id}")
    
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получение профиля пользователя"""
        users_data = self._load_json(self.users_file)
        return users_data.get(user_id)
    
    def set_user_calendar_id(self, user_id: str, calendar_id: str):
        """Установка ID календаря для пользователя"""
        profile = self.get_user_profile(user_id) or {}
        profile['calendar_id'] = calendar_id
        self.save_user_profile(user_id, profile)
    
    def get_user_calendar_id(self, user_id: str) -> str:
        """Получение ID календаря пользователя"""
        profile = self.get_user_profile(user_id)
        if profile:
            return profile.get('calendar_id', 'primary')
        return 'primary'
    
    def save_device_code(self, user_id: str, device_data: Dict[str, Any]):
        """Сохранение данных Device Flow"""
        users_data = self._load_json(self.users_file)
        
        if user_id not in users_data:
            users_data[user_id] = {}
        
        # Добавляем время истечения
        if 'expires_in' in device_data:
            expires_at = datetime.now() + timedelta(seconds=device_data['expires_in'])
            device_data['expires_at'] = expires_at.isoformat()
        
        users_data[user_id]['device_flow'] = device_data
        self._save_json(self.users_file, users_data)
        logger.info(f"📱 Device code сохранен для пользователя {user_id}")
    
    def get_device_code(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получение данных Device Flow"""
        profile = self.get_user_profile(user_id)
        if profile:
            return profile.get('device_flow')
        return None
    
    def clear_device_code(self, user_id: str):
        """Очистка данных Device Flow"""
        users_data = self._load_json(self.users_file)
        if user_id in users_data and 'device_flow' in users_data[user_id]:
            del users_data[user_id]['device_flow']
            self._save_json(self.users_file, users_data)
            logger.info(f"🗑️ Device code очищен для пользователя {user_id}")
    
    def is_token_valid(self, user_id: str) -> bool:
        """Проверка валидности токена"""
        tokens = self.get_user_tokens(user_id)
        if not tokens or 'access_token' not in tokens:
            return False
        
        # Проверяем срок действия
        expires_at = tokens.get('expires_at')
        if expires_at:
            try:
                expire_time = datetime.fromisoformat(expires_at)
                return datetime.now() < expire_time
            except ValueError:
                pass
        
        # Если нет информации о сроке, считаем токен валидным
        return True
    
    def delete_user_data(self, user_id: str):
        """Удаление всех данных пользователя"""
        # Удаляем токены
        tokens_data = self._load_json(self.tokens_file)
        if user_id in tokens_data:
            del tokens_data[user_id]
            self._save_json(self.tokens_file, tokens_data)
        
        # Удаляем профиль
        users_data = self._load_json(self.users_file)
        if user_id in users_data:
            del users_data[user_id]
            self._save_json(self.users_file, users_data)
        
        logger.info(f"🗑️ Все данные удалены для пользователя {user_id}")

# Глобальный экземпляр хранилища
storage = CalendarStorage()
