"""
Универсальный модуль для работы с бесплатными моделями OpenRouter.ai

Функциональность:
- Получение списка бесплатных моделей через API
- Автоматическое обновление списка раз в сутки
- Тестирование моделей на работоспособность
- Управление состоянием моделей (включено/отключено)
- Проверка лимитов API
"""

import json
import os
import sys
import time
import io
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import requests
from openai import OpenAI


# Настраиваем вывод в UTF-8 для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class OpenRouterFreeModels:
    """Класс для управления бесплатными моделями OpenRouter.ai"""
    
    def __init__(self, api_key: str, config_dir: str = "."):
        """
        Инициализация модуля
        
        Args:
            api_key: API ключ OpenRouter.ai
            config_dir: Директория для хранения конфигурационных файлов
        """
        self.api_key = api_key
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        
        # Пути к файлам конфигурации
        self.models_file = self.config_dir / "free_models_list.txt"
        self.working_models_file = self.config_dir / "working_models_free_only.txt"
        self.state_file = self.config_dir / "models_state.json"
        
        # Инициализация клиента OpenAI для работы с OpenRouter
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        
        # Загрузка состояния
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Загрузка состояния из файла"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        # Состояние по умолчанию
        return {
            "last_check": None,
            "models": {},
            "last_update": None
        }
    
    def _save_state(self):
        """Сохранение состояния в файл"""
        self.state["last_update"] = datetime.now().isoformat()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    def _determine_model_types(self, input_modalities: List[str], output_modalities: List[str]) -> List[str]:
        """
        Определение типов модели на основе modalities
        
        Args:
            input_modalities: Список типов входных данных
            output_modalities: Список типов выходных данных
            
        Returns:
            Список типов модели (текст, графика, музыка, видео)
        """
        all_modalities = set(input_modalities + output_modalities)
        types = []
        
        if 'text' in all_modalities:
            types.append('текст')
        if 'image' in all_modalities:
            types.append('графика')
        if 'audio' in all_modalities:
            types.append('музыка')
        if 'video' in all_modalities:
            types.append('видео')
        
        # Если типы не определены, по умолчанию считаем текстовой
        if not types:
            types.append('текст')
        
        return types
    
    def get_free_models_from_api(self) -> Dict[str, Dict]:
        """
        Получение списка бесплатных моделей через API OpenRouter с информацией о типах
        Фильтрует только модели с :free в конце
        Использует параметры из ссылки: input_modalities=text, max_price=0
        
        Returns:
            Словарь {model_id: {input_modalities, output_modalities, types, ...}}
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            
            # Получаем список моделей с параметрами из ссылки:
            # https://openrouter.ai/models?fmt=cards&input_modalities=text&max_price=0
            # Фильтруем по текстовому вводу и максимальной цене 0 (бесплатные)
            response = requests.get(
                'https://openrouter.ai/api/v1/models',
                headers=headers,
                params={
                    'max_price': 0,
                    'input_modalities': 'text'
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                models_info = {}
                
                # Извлекаем информацию о моделях, фильтруя только :free
                if 'data' in data:
                    for model in data['data']:
                        model_id = model.get('id', '')
                        # Фильтруем только модели с :free в конце
                        if model_id and model_id.endswith(':free'):
                            input_modalities = model.get('input_modalities', [])
                            output_modalities = model.get('output_modalities', [])
                            
                            # Определяем типы модели
                            types = self._determine_model_types(
                                input_modalities if isinstance(input_modalities, list) else [],
                                output_modalities if isinstance(output_modalities, list) else []
                            )
                            
                            models_info[model_id] = {
                                'input_modalities': input_modalities if isinstance(input_modalities, list) else [],
                                'output_modalities': output_modalities if isinstance(output_modalities, list) else [],
                                'types': types,
                                'name': model.get('name', ''),
                                'description': model.get('description', ''),
                                'context_length': model.get('context_length', 0),
                                'architecture': model.get('architecture', {})
                            }
                
                return models_info
            else:
                print(f"Ошибка при получении списка моделей: {response.status_code}")
                print(f"Ответ: {response.text[:200]}")
                return {}
                
        except Exception as e:
            print(f"Исключение при получении списка моделей: {e}")
            return {}
    
    def should_update_models(self) -> bool:
        """
        Проверка, нужно ли обновлять список моделей
        (раз в сутки)
        
        Returns:
            True если нужно обновить, False иначе
        """
        if not self.state.get("last_check"):
            return True
        
        try:
            last_check = datetime.fromisoformat(self.state["last_check"])
            # Проверяем, прошло ли более 24 часов
            return datetime.now() - last_check > timedelta(hours=24)
        except (ValueError, TypeError):
            return True
    
    def update_models_list(self, force: bool = False) -> Tuple[List[str], List[str], List[str]]:
        """
        Обновление списка моделей
        
        Args:
            force: Принудительное обновление даже если не прошло 24 часа
            
        Returns:
            Кортеж (новые модели, удаленные модели, все модели)
        """
        if not force and not self.should_update_models():
            print("Обновление не требуется (последняя проверка была менее 24 часов назад)")
            current_models = self._load_models_from_file()
            # Если файл пуст, но есть модели в состоянии, используем их
            if not current_models:
                current_models = self.get_enabled_models()
            return [], [], current_models
        
        print("Получение списка бесплатных моделей с OpenRouter.ai...")
        new_models_info = self.get_free_models_from_api()
        
        if not new_models_info:
            print("Не удалось получить список моделей через API. Используем существующий.")
            current_models = self._load_models_from_file()
            # Если файл пуст, но есть модели в состоянии, используем их
            if not current_models:
                current_models = self.get_enabled_models()
            return [], [], current_models
        
        # Получаем список ID моделей, отсортированный по размеру (от больших к малым)
        # Сортируем по context_length от больших к малым (приоритет большим)
        new_models = sorted(
            new_models_info.keys(),
            key=lambda m: new_models_info.get(m, {}).get("context_length", 0),
            reverse=True
        )
        
        # Загружаем текущий список моделей
        current_models = set(self._load_models_from_file())
        new_models_set = set(new_models)
        
        # Определяем новые и удаленные модели
        added_models = sorted(new_models_set - current_models)
        removed_models = sorted(current_models - new_models_set)
        
        # Обновляем состояние моделей с информацией о типах
        # Включаем только модели с :free
        for model_id, model_info in new_models_info.items():
            if model_id not in self.state["models"]:
                # Новая модель с :free - помечаем как включенную
                self.state["models"][model_id] = {
                    "enabled": True,
                    "added_date": datetime.now().isoformat(),
                    "last_tested": None,
                    "working": None,
                    "status": "новый",
                    "types": model_info.get("types", ["текст"]),
                    "input_modalities": model_info.get("input_modalities", []),
                    "output_modalities": model_info.get("output_modalities", []),
                    "name": model_info.get("name", ""),
                    "description": model_info.get("description", ""),
                    "context_length": model_info.get("context_length", 0)
                }
            else:
                # Существующая модель - обновляем информацию о типах
                self.state["models"][model_id]["types"] = model_info.get("types", ["текст"])
                self.state["models"][model_id]["input_modalities"] = model_info.get("input_modalities", [])
                self.state["models"][model_id]["output_modalities"] = model_info.get("output_modalities", [])
                self.state["models"][model_id]["name"] = model_info.get("name", "")
                self.state["models"][model_id]["description"] = model_info.get("description", "")
                self.state["models"][model_id]["context_length"] = model_info.get("context_length", 0)
                
                # Проверяем, была ли она отключена
                if not self.state["models"][model_id].get("enabled", True):
                    # Модель снова появилась - включаем её
                    self.state["models"][model_id]["enabled"] = True
                    self.state["models"][model_id]["re_enabled_date"] = datetime.now().isoformat()
                    self.state["models"][model_id]["status"] = "включена"
                else:
                    # Обновляем статус
                    if self.state["models"][model_id].get("working") is True:
                        self.state["models"][model_id]["status"] = "работает"
                    elif self.state["models"][model_id].get("working") is False:
                        self.state["models"][model_id]["status"] = "не работает"
                    else:
                        self.state["models"][model_id]["status"] = "не тестировалась"
        
        # Отключаем удаленные модели и модели без :free
        for model in removed_models:
            if model in self.state["models"]:
                self.state["models"][model]["enabled"] = False
                self.state["models"][model]["disabled_date"] = datetime.now().isoformat()
                self.state["models"][model]["status"] = "отключена"
        
        # Отключаем все модели без :free в конце
        for model_id in list(self.state["models"].keys()):
            if not model_id.endswith(':free'):
                self.state["models"][model_id]["enabled"] = False
                if "disabled_date" not in self.state["models"][model_id]:
                    self.state["models"][model_id]["disabled_date"] = datetime.now().isoformat()
                self.state["models"][model_id]["status"] = "отключена (не :free)"
        
        # Сохраняем новый список моделей
        self._save_models_to_file(new_models)
        
        # Обновляем время последней проверки
        self.state["last_check"] = datetime.now().isoformat()
        self._save_state()
        
        print(f"Обновление завершено:")
        print(f"  Всего моделей: {len(new_models)}")
        print(f"  Новых моделей: {len(added_models)}")
        print(f"  Удаленных моделей: {len(removed_models)}")
        
        if added_models:
            print(f"\nНовые модели:")
            for model in added_models:
                types = new_models_info.get(model, {}).get("types", ["текст"])
                print(f"  + {model} (типы: {', '.join(types)})")
        
        if removed_models:
            print(f"\nУдаленные модели:")
            for model in removed_models:
                print(f"  - {model}")
        
        return added_models, removed_models, new_models
    
    def _load_models_from_file(self) -> List[str]:
        """Загрузка списка моделей из файла"""
        if not self.models_file.exists():
            return []
        
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1251']
        for enc in encodings:
            try:
                with open(self.models_file, 'r', encoding=enc) as f:
                    models = [line.strip() for line in f if line.strip()]
                    return models
            except (UnicodeDecodeError, UnicodeError, IOError):
                continue
        
        return []
    
    def _save_models_to_file(self, models: List[str]):
        """Сохранение списка моделей в файл"""
        with open(self.models_file, 'w', encoding='utf-8') as f:
            for model in models:
                f.write(model + '\n')
    
    def get_enabled_models(self, sorted_by_size: bool = True) -> List[str]:
        """
        Получение списка включенных моделей
        
        Args:
            sorted_by_size: Если True, сортирует модели по размеру (context_length) от больших к малым
        
        Returns:
            Список идентификаторов включенных моделей
        """
        enabled = []
        for model, info in self.state["models"].items():
            if info.get("enabled", True):
                enabled.append(model)
        
        if sorted_by_size:
            # Сортируем по context_length от больших к малым (приоритет большим)
            enabled.sort(key=lambda m: self.state["models"].get(m, {}).get("context_length", 0), reverse=True)
        else:
            enabled.sort()
        
        return enabled
    
    def get_sorted_models_by_priority(self, models: Optional[List[str]] = None) -> List[str]:
        """
        Получение отсортированного списка моделей по приоритету
        Приоритет: большие модели (больший context_length) идут первыми
        
        Args:
            models: Список моделей для сортировки (если None, используются все включенные)
            
        Returns:
            Отсортированный список моделей от больших к малым
        """
        if models is None:
            models = self.get_enabled_models(sorted_by_size=False)
        
        # Сортируем по context_length от больших к малым
        # Также учитываем статус: работающие модели имеют приоритет
        def sort_key(model_id: str) -> tuple:
            info = self.state["models"].get(model_id, {})
            context_length = info.get("context_length", 0)
            # Работающие модели имеют приоритет
            is_working = info.get("working", False)
            # Возвращаем кортеж: (приоритет работы, context_length)
            # True > False при сортировке, поэтому работающие будут первыми
            return (not is_working, -context_length)  # Отрицательное для сортировки по убыванию
        
        return sorted(models, key=sort_key)
    
    def get_models_by_type(self, model_type: str) -> List[str]:
        """
        Получение списка моделей по типу
        
        Args:
            model_type: Тип модели (текст, графика, музыка, видео)
            
        Returns:
            Список идентификаторов моделей указанного типа
        """
        models = []
        for model_id, info in self.state["models"].items():
            if info.get("enabled", True):
                types = info.get("types", ["текст"])
                if model_type.lower() in [t.lower() for t in types]:
                    models.append(model_id)
        return sorted(models)
    
    def get_models_by_status(self, status: str) -> List[str]:
        """
        Получение списка моделей по статусу
        
        Args:
            status: Статус модели (работает, не работает, не тестировалась, отключена, новый)
            
        Returns:
            Список идентификаторов моделей с указанным статусом
        """
        models = []
        for model_id, info in self.state["models"].items():
            if info.get("status", "неизвестно") == status:
                models.append(model_id)
        return sorted(models)
    
    def test_model(self, model: str, timeout: int = 30) -> Tuple[bool, Optional[str]]:
        """
        Тестирование модели на работоспособность
        
        Args:
            model: Идентификатор модели
            timeout: Таймаут запроса в секундах
            
        Returns:
            Кортеж (успешно ли тест, сообщение об ошибке или None)
        """
        try:
            completion = self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": "Hi"
                    }
                ],
                timeout=timeout,
                max_tokens=10
            )
            
            if completion.choices and completion.choices[0].message.content:
                return True, None
            else:
                return False, "Пустой ответ"
                
        except Exception as e:
            error_msg = str(e)
            # Сокращаем длинные сообщения
            if len(error_msg) > 100:
                error_msg = error_msg[:100] + "..."
            return False, error_msg
    
    def test_all_models(self, models: Optional[List[str]] = None, delay: float = 0.5, 
                       priority_order: bool = True) -> Dict[str, bool]:
        """
        Тестирование всех моделей или указанного списка
        
        Args:
            models: Список моделей для тестирования (если None, тестируются все включенные)
            delay: Задержка между запросами в секундах
            priority_order: Если True, тестирует модели в порядке приоритета (большие первыми)
            
        Returns:
            Словарь {модель: успешно ли тест}
        """
        if models is None:
            if priority_order:
                models = self.get_sorted_models_by_priority()
            else:
                models = self.get_enabled_models(sorted_by_size=False)
        elif priority_order:
            models = self.get_sorted_models_by_priority(models)
        
        if not models:
            print("Нет моделей для тестирования")
            return {}
        
        results = {}
        working_models = []
        failed_models = []
        
        print(f"Тестирую {len(models)} моделей...\n")
        
        for i, model in enumerate(models, 1):
            print(f"[{i}/{len(models)}] Тестирую {model}...", end=" ", flush=True)
            
            success, error = self.test_model(model)
            results[model] = success
            
            if success:
                print("OK")
                working_models.append(model)
                # Обновляем состояние модели
                if model in self.state["models"]:
                    self.state["models"][model]["working"] = True
                    self.state["models"][model]["last_tested"] = datetime.now().isoformat()
                    self.state["models"][model]["status"] = "работает"
            else:
                error_msg = error or "Неизвестная ошибка"
                if len(error_msg) > 50:
                    error_msg = error_msg[:50] + "..."
                print(f"FAILED ({error_msg})")
                failed_models.append(model)
                # Обновляем состояние модели
                if model in self.state["models"]:
                    self.state["models"][model]["working"] = False
                    self.state["models"][model]["last_tested"] = datetime.now().isoformat()
                    self.state["models"][model]["last_error"] = error_msg
                    self.state["models"][model]["status"] = "не работает"
            
            # Задержка между запросами
            if i < len(models):
                time.sleep(delay)
        
        # Сохраняем только работающие модели в отдельный файл
        with open(self.working_models_file, 'w', encoding='utf-8') as f:
            for model in working_models:
                f.write(model + '\n')
        
        # Обновляем статусы моделей
        for model in working_models:
            if model in self.state["models"]:
                self.state["models"][model]["status"] = "работает"
        
        for model in failed_models:
            if model in self.state["models"]:
                self.state["models"][model]["status"] = "не работает"
        
        # Сохраняем обновленное состояние
        self._save_state()
        
        print(f"\n{'='*60}")
        print(f"Результаты тестирования:")
        print(f"Работающих моделей: {len(working_models)}")
        print(f"Неработающих моделей: {len(failed_models)}")
        print(f"{'='*60}")
        
        if failed_models:
            print("\nНеработающие модели:")
            for model in failed_models:
                print(f"  - {model}")
        
        return results
    
    def check_api_limits(self) -> Dict:
        """
        Проверка лимитов API ключа
        
        Returns:
            Словарь с информацией о лимитах
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            
            response = requests.get(
                'https://openrouter.ai/api/v1/key',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', {})
            else:
                print(f"Ошибка при проверке лимитов: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"Исключение при проверке лимитов: {e}")
            return {}
    
    def print_api_limits(self):
        """Вывод информации о лимитах API"""
        limits = self.check_api_limits()
        
        if not limits:
            print("Не удалось получить информацию о лимитах")
            return
        
        print("\n" + "="*60)
        print("Информация о лимитах API:")
        print("="*60)
        
        if limits.get('limit') is not None:
            print(f"Лимит кредитов: {limits.get('limit')}")
            print(f"Осталось кредитов: {limits.get('limit_remaining', 'N/A')}")
            print(f"Сброс лимита: {limits.get('limit_reset', 'N/A')}")
        else:
            print("Лимит кредитов: Неограничен")
        
        print(f"\nИспользование (все время): {limits.get('usage', 0)} кредитов")
        print(f"Использование (сегодня): {limits.get('usage_daily', 0)} кредитов")
        print(f"Использование (эта неделя): {limits.get('usage_weekly', 0)} кредитов")
        print(f"Использование (этот месяц): {limits.get('usage_monthly', 0)} кредитов")
        
        print(f"\nБесплатный тариф: {limits.get('is_free_tier', False)}")
        print("="*60)
    
    def get_model_info(self, model: str) -> Dict:
        """
        Получение информации о модели из состояния
        
        Args:
            model: Идентификатор модели
            
        Returns:
            Словарь с информацией о модели
        """
        return self.state["models"].get(model, {})
    
    def enable_model(self, model: str):
        """Включение модели"""
        if model not in self.state["models"]:
            self.state["models"][model] = {
                "types": ["текст"],
                "status": "включена"
            }
        self.state["models"][model]["enabled"] = True
        self.state["models"][model]["enabled_date"] = datetime.now().isoformat()
        # Обновляем статус в зависимости от работоспособности
        if self.state["models"][model].get("working") is True:
            self.state["models"][model]["status"] = "работает"
        elif self.state["models"][model].get("working") is False:
            self.state["models"][model]["status"] = "не работает"
        else:
            self.state["models"][model]["status"] = "включена"
        self._save_state()
    
    def disable_model(self, model: str):
        """Отключение модели"""
        if model not in self.state["models"]:
            self.state["models"][model] = {
                "types": ["текст"],
                "status": "отключена"
            }
        self.state["models"][model]["enabled"] = False
        self.state["models"][model]["disabled_date"] = datetime.now().isoformat()
        self.state["models"][model]["status"] = "отключена"
        self._save_state()
    
    def init_models_from_list(self, models: List[str]):
        """
        Инициализация списка моделей из предоставленного списка
        Используется для начальной загрузки моделей
        Фильтрует только модели с :free в конце
        
        Args:
            models: Список идентификаторов моделей
        """
        # Фильтруем только модели с :free
        free_models = [m for m in models if m.endswith(':free')]
        if len(free_models) < len(models):
            skipped = len(models) - len(free_models)
            print(f"Пропущено {skipped} моделей без :free")
        
        print(f"Инициализация {len(free_models)} моделей с :free...")
        
        # Пытаемся получить информацию о типах из API
        models_info = self.get_free_models_from_api()
        
        for model in free_models:
            if model not in self.state["models"]:
                # Пытаемся получить информацию о типах из API
                model_info = models_info.get(model, {})
                types = model_info.get("types", ["текст"])  # По умолчанию текст
                
                self.state["models"][model] = {
                    "enabled": True,
                    "added_date": datetime.now().isoformat(),
                    "last_tested": None,
                    "working": None,
                    "initialized": True,
                    "status": "не тестировалась",
                    "types": types,
                    "input_modalities": model_info.get("input_modalities", []),
                    "output_modalities": model_info.get("output_modalities", []),
                    "name": model_info.get("name", ""),
                    "description": model_info.get("description", ""),
                    "context_length": model_info.get("context_length", 0)
                }
        
        # Отключаем модели без :free, если они есть в списке
        for model in models:
            if not model.endswith(':free'):
                if model in self.state["models"]:
                    self.state["models"][model]["enabled"] = False
                    self.state["models"][model]["disabled_date"] = datetime.now().isoformat()
                    self.state["models"][model]["status"] = "отключена (не :free)"
        
        # Сохраняем список только моделей с :free
        self._save_models_to_file(free_models)
        self._save_state()
        
        print(f"Инициализировано {len(free_models)} моделей с :free")


def main():
    """Пример использования модуля"""
    # API ключ - укажите свой ключ OpenRouter или используйте переменную окружения
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    
    # Создаем экземпляр модуля
    manager = OpenRouterFreeModels(api_key)
    
    # Проверяем лимиты API
    manager.print_api_limits()
    
    # Обновляем список моделей (если нужно)
    added, removed, all_models = manager.update_models_list()
    
    # Тестируем все включенные модели
    if all_models:
        print(f"\nНайдено {len(all_models)} бесплатных моделей")
        print("Начинаю тестирование...")
        results = manager.test_all_models()
        
        # Выводим статистику по типам моделей
        print("\n" + "="*60)
        print("Статистика по типам моделей:")
        print("="*60)
        type_stats = {}
        for model_id in all_models:
            model_info = manager.get_model_info(model_id)
            types = model_info.get("types", ["текст"])
            status = model_info.get("status", "неизвестно")
            for model_type in types:
                if model_type not in type_stats:
                    type_stats[model_type] = {"всего": 0, "работает": 0, "не работает": 0}
                type_stats[model_type]["всего"] += 1
                if status == "работает":
                    type_stats[model_type]["работает"] += 1
                elif status == "не работает":
                    type_stats[model_type]["не работает"] += 1
        
        for model_type, stats in sorted(type_stats.items()):
            print(f"{model_type.capitalize()}: всего {stats['всего']}, работает {stats['работает']}, не работает {stats['не работает']}")
    else:
        print("Нет моделей для тестирования")


if __name__ == "__main__":
    main()
