"""
Менеджер моделей OpenRouter с автоматическим переключением при недоступности

Функциональность:
- Автоматическое переключение на следующую доступную модель при ошибках
- Кэширование работоспособности моделей
- Отслеживание неудачных попыток
- Интеграция с OpenRouterFreeModels
- Персистентное сохранение выбранной модели (JSON + Redis)
- Восстановление выбранной модели между сессиями
"""

import os
import logging
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import json
from datetime import datetime, timedelta

from .openrouter_free_models import OpenRouterFreeModels

logger = logging.getLogger(__name__)

# Ключи для хранения моделей в Redis
# Глобальный ключ (для обратной совместимости)
REDIS_CURRENT_MODEL_KEY = "openrouter:current_model"
# Ключ для пользовательской модели: openrouter:user_model:{user_id}
REDIS_USER_MODEL_KEY_PREFIX = "openrouter:user_model:"
REDIS_MODEL_TTL = 86400 * 30  # 30 дней для пользовательских моделей

# Глобальный синхронный клиент Redis для менеджера моделей
_sync_redis_client = None


def _get_sync_redis_client():
    """Получение синхронного клиента Redis"""
    global _sync_redis_client
    
    if _sync_redis_client is not None:
        return _sync_redis_client
    
    try:
        import redis
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        _sync_redis_client = redis.from_url(redis_uri, decode_responses=True)
        # Проверяем подключение
        _sync_redis_client.ping()
        logger.info(f"[OPENROUTER_MANAGER] Синхронное подключение к Redis установлено: {redis_uri}")
        return _sync_redis_client
    except ImportError:
        logger.debug("[OPENROUTER_MANAGER] Redis библиотека не установлена")
        return None
    except Exception as e:
        logger.debug(f"[OPENROUTER_MANAGER] Не удалось подключиться к Redis: {e}")
        return None


class OpenRouterModelManager:
    """Менеджер моделей OpenRouter с автоматическим переключением"""
    
    def __init__(self, api_key: Optional[str] = None, config_dir: Optional[str] = None):
        """
        Инициализация менеджера моделей
        
        Args:
            api_key: API ключ OpenRouter (если None, берется из OPENROUTER_API_KEY)
            config_dir: Директория для хранения конфигурации
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY не установлен")
        
        # Определяем директорию конфигурации
        if config_dir is None:
            # Используем директорию openrouter_data рядом с openrouter_free_models.py
            base_dir = Path(__file__).parent
            config_dir = str(base_dir / "openrouter_data")
        
        # Инициализируем менеджер бесплатных моделей
        self.models_manager = OpenRouterFreeModels(self.api_key, config_dir=config_dir)
        
        # Файл для хранения состояния переключений
        self.state_file = Path(config_dir) / "model_switching_state.json"
        self.switching_state = self._load_switching_state()
        
        # Максимальное количество неудачных попыток перед переключением
        self.max_failures = int(os.getenv("OPENROUTER_MAX_FAILURES", "3"))
        
        # Время, через которое модель считается снова доступной (в секундах)
        self.retry_after_seconds = int(os.getenv("OPENROUTER_RETRY_AFTER_SECONDS", "300"))  # 5 минут
    
    def _get_redis_client(self):
        """Получение синхронного клиента Redis"""
        return _get_sync_redis_client()
    
    def _get_user_redis_key(self, user_id: Optional[str]) -> str:
        """Получение ключа Redis для пользователя"""
        if user_id:
            return f"{REDIS_USER_MODEL_KEY_PREFIX}{user_id}"
        return REDIS_CURRENT_MODEL_KEY
    
    def _load_current_model_from_redis(self, user_id: Optional[str] = None) -> Optional[str]:
        """
        Загрузка текущей модели из Redis (с fallback на файл)
        
        Args:
            user_id: ID пользователя (если None, загружается глобальная модель)
        """
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                # Сначала пробуем загрузить модель пользователя
                if user_id:
                    user_key = self._get_user_redis_key(user_id)
                    model = redis_client.get(user_key)
                    if model:
                        logger.info(f"[OPENROUTER_MANAGER] Загружена модель пользователя {user_id} из Redis: {model}")
                        return model
                
                # Если модели пользователя нет, пробуем глобальную (для обратной совместимости)
                model = redis_client.get(REDIS_CURRENT_MODEL_KEY)
                if model:
                    logger.info(f"[OPENROUTER_MANAGER] Загружена глобальная модель из Redis: {model}")
                    return model
        except Exception as e:
            logger.debug(f"Ошибка при загрузке модели из Redis: {e}")
        
        # Fallback: загружаем из файла если Redis недоступен и есть user_id
        if user_id:
            file_model = self._load_user_model_from_file(user_id)
            if file_model:
                return file_model
        
        return None
    
    def _get_user_model_file(self, user_id: str) -> Path:
        """Получение пути к файлу с моделью пользователя (fallback когда Redis недоступен)"""
        return self.state_file.parent / f"user_model_{user_id}.json"
    
    def _save_user_model_to_file(self, user_id: str, model_id: str):
        """Сохранение модели пользователя в файл (fallback когда Redis недоступен)"""
        try:
            user_file = self._get_user_model_file(user_id)
            user_file.parent.mkdir(parents=True, exist_ok=True)
            with open(user_file, 'w', encoding='utf-8') as f:
                json.dump({"model_id": model_id, "updated_at": datetime.now().isoformat()}, f)
            logger.info(f"[OPENROUTER_MANAGER] Модель пользователя {user_id} сохранена в файл: {model_id}")
        except Exception as e:
            logger.warning(f"[OPENROUTER_MANAGER] Ошибка сохранения модели в файл: {e}")
    
    def _load_user_model_from_file(self, user_id: str) -> Optional[str]:
        """Загрузка модели пользователя из файла (fallback когда Redis недоступен)"""
        try:
            user_file = self._get_user_model_file(user_id)
            if user_file.exists():
                with open(user_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                model_id = data.get("model_id")
                if model_id:
                    logger.info(f"[OPENROUTER_MANAGER] Модель пользователя {user_id} загружена из файла: {model_id}")
                    return model_id
        except Exception as e:
            logger.debug(f"[OPENROUTER_MANAGER] Ошибка загрузки модели из файла: {e}")
        return None
    
    def _delete_user_model_file(self, user_id: str):
        """Удаление файла с моделью пользователя"""
        try:
            user_file = self._get_user_model_file(user_id)
            if user_file.exists():
                user_file.unlink()
                logger.info(f"[OPENROUTER_MANAGER] Файл модели пользователя {user_id} удален")
        except Exception as e:
            logger.debug(f"[OPENROUTER_MANAGER] Ошибка удаления файла модели: {e}")

    def _save_current_model_to_redis(self, model_id: str, user_id: Optional[str] = None):
        """
        Сохранение текущей модели в Redis (с fallback на файл)
        
        Args:
            model_id: ID модели
            user_id: ID пользователя (если None, сохраняется глобально)
        """
        saved_to_redis = False
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                key = self._get_user_redis_key(user_id)
                redis_client.setex(key, REDIS_MODEL_TTL, model_id)
                saved_to_redis = True
                if user_id:
                    logger.info(f"[OPENROUTER_MANAGER] Модель сохранена в Redis для пользователя {user_id}: {model_id}")
                else:
                    logger.info(f"[OPENROUTER_MANAGER] Глобальная модель сохранена в Redis: {model_id}")
        except Exception as e:
            logger.debug(f"Ошибка при сохранении модели в Redis: {e}")
        
        # Fallback: сохраняем в файл если Redis недоступен и есть user_id
        if not saved_to_redis and user_id:
            self._save_user_model_to_file(user_id, model_id)
    
    def _load_switching_state(self) -> Dict:
        """Загрузка состояния переключений из файла"""
        state = {
            "failed_models": {},  # {model_id: {"failures": int, "last_failure": str, "disabled_until": str}}
            "current_model": None,
            "switching_history": []  # История переключений
        }
        
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Ошибка при загрузке состояния переключений: {e}")
        
        # Проверяем Redis на наличие более актуальной модели
        redis_model = self._load_current_model_from_redis()
        if redis_model:
            state["current_model"] = redis_model
        
        return state
    
    def _save_switching_state(self):
        """Сохранение состояния переключений в файл (без записи в глобальный Redis)"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.switching_state, f, ensure_ascii=False, indent=2)
            
            # ВАЖНО: НЕ сохраняем в глобальный Redis ключ openrouter:current_model
            # Модели теперь привязаны к пользователям и сохраняются через set_user_model
            # Глобальный ключ использовался для обратной совместимости, но создает проблемы
            # при очистке кэша, так как перезаписывается при каждом вызове get_available_model
        except IOError as e:
            logger.warning(f"Ошибка при сохранении состояния переключений: {e}")
    
    def _is_model_available(self, model_id: str) -> bool:
        """
        Проверка, доступна ли модель для использования
        
        Args:
            model_id: Идентификатор модели
            
        Returns:
            True если модель доступна, False иначе
        """
        if model_id not in self.switching_state["failed_models"]:
            return True
        
        model_state = self.switching_state["failed_models"][model_id]
        
        # Проверяем, не истекло ли время блокировки
        disabled_until = model_state.get("disabled_until")
        if disabled_until:
            try:
                disabled_until_dt = datetime.fromisoformat(disabled_until)
                if datetime.now() < disabled_until_dt:
                    return False  # Модель все еще заблокирована
                else:
                    # Время блокировки истекло, удаляем из заблокированных
                    del self.switching_state["failed_models"][model_id]
                    self._save_switching_state()
                    return True
            except (ValueError, TypeError):
                # Некорректная дата, считаем что модель доступна
                return True
        
        # Если количество неудач меньше максимума, модель доступна
        failures = model_state.get("failures", 0)
        return failures < self.max_failures
    
    def record_model_failure(self, model_id: str, error: Optional[str] = None):
        """
        Запись неудачной попытки использования модели
        
        Args:
            model_id: Идентификатор модели
            error: Сообщение об ошибке (опционально)
        """
        if model_id not in self.switching_state["failed_models"]:
            self.switching_state["failed_models"][model_id] = {
                "failures": 0,
                "last_failure": None,
                "disabled_until": None,
                "errors": []
            }
        
        model_state = self.switching_state["failed_models"][model_id]
        model_state["failures"] = model_state.get("failures", 0) + 1
        model_state["last_failure"] = datetime.now().isoformat()
        
        if error:
            errors = model_state.get("errors", [])
            errors.append({
                "error": error[:200],  # Ограничиваем длину
                "timestamp": datetime.now().isoformat()
            })
            # Храним только последние 10 ошибок
            model_state["errors"] = errors[-10:]
        
        # Если количество неудач достигло максимума, блокируем модель на время
        if model_state["failures"] >= self.max_failures:
            disabled_until = datetime.now() + timedelta(seconds=self.retry_after_seconds)
            model_state["disabled_until"] = disabled_until.isoformat()
            logger.warning(
                f"Модель {model_id} заблокирована до {disabled_until.isoformat()} "
                f"из-за {model_state['failures']} неудачных попыток"
            )
        
        self._save_switching_state()
    
    def record_model_success(self, model_id: str):
        """
        Запись успешного использования модели (сбрасывает счетчик неудач)
        
        Args:
            model_id: Идентификатор модели
        """
        if model_id in self.switching_state["failed_models"]:
            # Сбрасываем счетчик неудач
            self.switching_state["failed_models"][model_id]["failures"] = 0
            self.switching_state["failed_models"][model_id]["disabled_until"] = None
            self._save_switching_state()
            logger.info(f"Модель {model_id} успешно использована, счетчик неудач сброшен")
    
    def get_available_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
        """
        Получение доступной модели для использования
        
        Args:
            preferred_model: Предпочтительная модель (если доступна)
            
        Returns:
            Идентификатор доступной модели или None
        """
        # Если предпочтительная модель указана и доступна, используем её
        if preferred_model and self._is_model_available(preferred_model):
            self.switching_state["current_model"] = preferred_model
            self._save_switching_state()
            return preferred_model
        
        # Получаем список доступных моделей
        working_models = self.models_manager.get_working_free_models()
        
        # Если нет рабочих моделей, используем все включенные
        if not working_models:
            working_models = self.models_manager.get_enabled_models(sorted_by_size=True)
        
        # Фильтруем только доступные модели
        available_models = [m for m in working_models if self._is_model_available(m)]
        
        if not available_models:
            logger.warning("Нет доступных моделей для использования")
            return None
        
        # Выбираем первую доступную модель
        selected_model = available_models[0]
        self.switching_state["current_model"] = selected_model
        
        # Записываем в историю переключений
        if preferred_model and preferred_model != selected_model:
            self.switching_state["switching_history"].append({
                "from": preferred_model,
                "to": selected_model,
                "timestamp": datetime.now().isoformat(),
                "reason": "preferred_model_unavailable"
            })
            # Храним только последние 100 переключений
            self.switching_state["switching_history"] = self.switching_state["switching_history"][-100:]
            logger.info(f"Переключение с {preferred_model} на {selected_model}")
        
        self._save_switching_state()
        return selected_model
    
    def get_next_model(self, current_model: str) -> Optional[str]:
        """
        Получение следующей модели для переключения
        
        Args:
            current_model: Текущая модель
            
        Returns:
            Идентификатор следующей доступной модели или None
        """
        # Записываем текущую модель как недоступную
        self.record_model_failure(current_model)
        
        # Получаем следующую доступную модель
        return self.get_available_model()
    
    def get_working_models_list(self) -> List[Dict]:
        """
        Получение списка рабочих бесплатных моделей с информацией о доступности
        
        Returns:
            Список словарей с информацией о моделях:
            {
                'id': str,
                'name': str,
                'context_length': int,
                'working': bool,
                'status': str,
                'available': bool,
                'failures': int,
                'disabled_until': str или None
            }
        """
        available_models = self.models_manager.get_available_free_models()
        
        result = []
        for model_info in available_models:
            model_id = model_info['id']
            is_available = self._is_model_available(model_id)
            
            model_state = self.switching_state["failed_models"].get(model_id, {})
            
            result.append({
                **model_info,
                'available': is_available,
                'failures': model_state.get("failures", 0),
                'disabled_until': model_state.get("disabled_until"),
                'last_failure': model_state.get("last_failure")
            })
        
        return result
    
    def get_detailed_limits(self) -> Dict:
        """
        Получение детальной информации о лимитах API
        
        Returns:
            Словарь с информацией о лимитах
        """
        return self.models_manager.get_detailed_limits()
    
    def reset_model_failures(self, model_id: str):
        """
        Сброс счетчика неудач для модели
        
        Args:
            model_id: Идентификатор модели
        """
        if model_id in self.switching_state["failed_models"]:
            del self.switching_state["failed_models"][model_id]
            self._save_switching_state()
            logger.info(f"Счетчик неудач для модели {model_id} сброшен")
    
    def get_switching_history(self, limit: int = 20) -> List[Dict]:
        """
        Получение истории переключений
        
        Args:
            limit: Максимальное количество записей
            
        Returns:
            Список записей истории переключений
        """
        history = self.switching_state.get("switching_history", [])
        return history[-limit:]
    
    def get_persisted_model(self, user_id: Optional[str] = None) -> Optional[str]:
        """
        Получение сохраненной модели (из Redis или файла)
        
        Эта модель была выбрана пользователем через switch_openrouter_model
        и должна использоваться вместо модели из переменных окружения.
        
        Args:
            user_id: ID пользователя (если None, возвращается глобальная модель)
        
        Returns:
            Идентификатор сохраненной модели или None
        """
        # Сначала проверяем Redis (более актуальные данные)
        redis_model = self._load_current_model_from_redis(user_id=user_id)
        if redis_model:
            return redis_model
        
        # Затем проверяем файл состояния (только для глобальной модели)
        if not user_id:
            current_model = self.switching_state.get("current_model")
            if current_model:
                return current_model
        
        return None
    
    def set_user_model(self, user_id: str, model_id: str) -> bool:
        """
        Установка модели для конкретного пользователя
        
        Args:
            user_id: ID пользователя
            model_id: ID модели OpenRouter
            
        Returns:
            True если успешно, False в противном случае
        """
        if not user_id or not model_id:
            return False
        
        # Проверяем, что модель доступна
        if not self._is_model_available(model_id):
            logger.warning(f"[OPENROUTER_MANAGER] Модель {model_id} недоступна для пользователя {user_id}")
            return False
        
        # Сохраняем в Redis
        self._save_current_model_to_redis(model_id, user_id=user_id)
        logger.info(f"[OPENROUTER_MANAGER] Модель {model_id} установлена для пользователя {user_id}")
        return True
    
    def apply_persisted_model_to_env(self, tag: str = None, user_id: Optional[str] = None) -> bool:
        """
        Применение сохраненной модели к переменным окружения
        
        Если пользователь ранее переключился на другую модель через switch_openrouter_model,
        эта функция применит сохраненную модель к переменным окружения.
        
        Args:
            tag: Тег модели (None для основной модели GIGA_AGENT_LLM)
            user_id: ID пользователя (если None, применяется глобальная модель)
            
        Returns:
            True если модель была применена, False если нет сохраненной модели
        """
        persisted_model = self.get_persisted_model(user_id=user_id)
        if not persisted_model:
            return False
        
        # Проверяем, что модель доступна
        if not self._is_model_available(persisted_model):
            logger.warning(f"[OPENROUTER_MANAGER] Сохраненная модель {persisted_model} недоступна, не применяем")
            return False
        
        # Формируем ключ переменной окружения
        env_key = f"GIGA_AGENT_LLM_{tag.upper()}" if tag else "GIGA_AGENT_LLM"
        current_env = os.getenv(env_key, "")
        
        # Формируем полное значение для env
        full_model_str = f"openrouter:{persisted_model}"
        
        # Проверяем, нужно ли обновлять
        if current_env == full_model_str:
            logger.debug(f"[OPENROUTER_MANAGER] Модель уже установлена: {full_model_str}")
            return True
        
        # Применяем сохраненную модель
        os.environ[env_key] = full_model_str
        if user_id:
            logger.info(f"[OPENROUTER_MANAGER] Применена модель пользователя {user_id}: {full_model_str} (было: {current_env})")
        else:
            logger.info(f"[OPENROUTER_MANAGER] Применена глобальная модель: {full_model_str} (было: {current_env})")
        
        return True
    
    def clear_persisted_model(self, user_id: Optional[str] = None):
        """
        Очистка сохраненной модели (сброс к модели из переменных окружения)
        
        Args:
            user_id: ID пользователя (если None, очищается глобальная модель)
        """
        # Очищаем глобальное состояние только если не указан user_id
        if not user_id:
            self.switching_state["current_model"] = None
            self._save_switching_state()
        
        # Очищаем Redis
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                key = self._get_user_redis_key(user_id)
                redis_client.delete(key)
                if user_id:
                    logger.info(f"[OPENROUTER_MANAGER] Модель пользователя {user_id} очищена из Redis")
                else:
                    logger.info("[OPENROUTER_MANAGER] Глобальная модель очищена из Redis")
        except Exception as e:
            logger.debug(f"Ошибка при очистке модели из Redis: {e}")
        
        # Также очищаем файл пользовательской модели (fallback)
        if user_id:
            self._delete_user_model_file(user_id)
        
        logger.info(f"[OPENROUTER_MANAGER] Сохраненная модель очищена (user_id={user_id})")
    
    def get_user_model_info(self, user_id: str) -> Optional[Dict]:
        """
        Получение информации о модели пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Словарь с информацией о модели или None
        """
        if not user_id:
            return None
        
        model_id = self.get_persisted_model(user_id=user_id)
        if not model_id:
            return None
        
        # Получаем информацию о модели
        models = self.get_working_models_list()
        for model in models:
            if model['id'] == model_id:
                return {
                    'user_id': user_id,
                    'model_id': model_id,
                    'model_name': model.get('name', 'N/A'),
                    'context_length': model.get('context_length', 0),
                    'available': model.get('available', True)
                }
        
        return {
            'user_id': user_id,
            'model_id': model_id,
            'model_name': 'Unknown',
            'context_length': 0,
            'available': self._is_model_available(model_id)
        }


async def get_verified_models_from_db(fully_functional_only: bool = True) -> List[Dict]:
    """
    Получить список проверенных моделей из базы данных PostgreSQL.
    
    Args:
        fully_functional_only: Если True, возвращает только полностью функциональные модели
        
    Returns:
        Список словарей с информацией о моделях
    """
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        
        database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@aegra-postgres:5432/postgres")
        if "asyncpg" not in database_url:
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        
        engine = create_async_engine(database_url)
        
        async with engine.connect() as conn:
            if fully_functional_only:
                query = text("""
                    SELECT model_id, model_name, context_length, avg_response_time_ms, notes, deprecation_date
                    FROM openrouter_verified_models 
                    WHERE is_fully_functional = true
                      AND (deprecation_date IS NULL OR deprecation_date > CURRENT_TIMESTAMP)
                    ORDER BY avg_response_time_ms ASC NULLS LAST
                """)
            else:
                query = text("""
                    SELECT model_id, model_name, context_length, is_fully_functional, 
                           supports_function_calling, supports_streaming, supports_system_prompt,
                           has_data_policy_issue, avg_response_time_ms, notes, deprecation_date
                    FROM openrouter_verified_models 
                    WHERE (deprecation_date IS NULL OR deprecation_date > CURRENT_TIMESTAMP)
                    ORDER BY is_fully_functional DESC, avg_response_time_ms ASC NULLS LAST
                """)
            
            result = await conn.execute(query)
            rows = result.fetchall()
            
            models = []
            for row in rows:
                model = {
                    'model_id': row[0],
                    'model_name': row[1],
                    'context_length': row[2] or 0,
                }
                if fully_functional_only:
                    model['avg_response_time_ms'] = row[3]
                    model['notes'] = row[4]
                    model['deprecation_date'] = row[5] if len(row) > 5 else None
                else:
                    model['is_fully_functional'] = row[3]
                    model['supports_function_calling'] = row[4]
                    model['supports_streaming'] = row[5]
                    model['supports_system_prompt'] = row[6]
                    model['has_data_policy_issue'] = row[7]
                    model['avg_response_time_ms'] = row[8]
                    model['notes'] = row[9]
                    model['deprecation_date'] = row[10] if len(row) > 10 else None
                models.append(model)
            
            return models
            
    except Exception as e:
        logger.error(f"[OPENROUTER_MANAGER] Ошибка при получении проверенных моделей из БД: {e}")
        return []


def get_verified_models_sync(fully_functional_only: bool = True) -> List[Dict]:
    """
    Синхронная версия получения проверенных моделей из БД.
    
    Args:
        fully_functional_only: Если True, возвращает только полностью функциональные модели
        
    Returns:
        Список словарей с информацией о моделях
    """
    try:
        import psycopg2
        
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@aegra-postgres:5432/postgres")
        # Убираем asyncpg если есть
        database_url = database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
        
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        try:
            if fully_functional_only:
                cursor.execute("""
                    SELECT model_id, model_name, context_length, avg_response_time_ms, notes, deprecation_date
                    FROM openrouter_verified_models 
                    WHERE is_fully_functional = true
                      AND (deprecation_date IS NULL OR deprecation_date > CURRENT_TIMESTAMP)
                    ORDER BY avg_response_time_ms ASC NULLS LAST
                """)
            else:
                cursor.execute("""
                    SELECT model_id, model_name, context_length, is_fully_functional, 
                           supports_function_calling, supports_streaming, supports_system_prompt,
                           has_data_policy_issue, avg_response_time_ms, notes, deprecation_date
                    FROM openrouter_verified_models 
                    WHERE (deprecation_date IS NULL OR deprecation_date > CURRENT_TIMESTAMP)
                    ORDER BY is_fully_functional DESC, avg_response_time_ms ASC NULLS LAST
                """)
            
            rows = cursor.fetchall()
            
            models = []
            for row in rows:
                model = {
                    'model_id': row[0],
                    'model_name': row[1],
                    'context_length': row[2] or 0,
                }
                if fully_functional_only:
                    model['avg_response_time_ms'] = row[3]
                    model['notes'] = row[4]
                    model['deprecation_date'] = row[5] if len(row) > 5 else None
                else:
                    model['is_fully_functional'] = row[3]
                    model['supports_function_calling'] = row[4]
                    model['supports_streaming'] = row[5]
                    model['supports_system_prompt'] = row[6]
                    model['has_data_policy_issue'] = row[7]
                    model['avg_response_time_ms'] = row[8]
                    model['notes'] = row[9]
                    model['deprecation_date'] = row[10] if len(row) > 10 else None
                models.append(model)
            
            return models
            
        finally:
            cursor.close()
            conn.close()
            
    except ImportError:
        logger.warning("[OPENROUTER_MANAGER] psycopg2 не установлен, используем asyncio")
        import asyncio
        return asyncio.run(get_verified_models_from_db(fully_functional_only))
    except Exception as e:
        logger.error(f"[OPENROUTER_MANAGER] Ошибка при получении проверенных моделей из БД: {e}")
        return []


def is_model_verified(model_id: str) -> bool:
    """
    Проверить, является ли модель проверенной и полностью функциональной.
    
    Args:
        model_id: Идентификатор модели
        
    Returns:
        True если модель проверена и полностью функциональна
    """
    verified_models = get_verified_models_sync(fully_functional_only=True)
    return any(m['model_id'] == model_id for m in verified_models)
