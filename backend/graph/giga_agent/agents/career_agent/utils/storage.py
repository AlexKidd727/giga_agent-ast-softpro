"""
Хранение данных карьерного агента с изоляцией по пользователям
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class CareerStorage:
    """Управление хранением данных карьерного агента с изоляцией по user_id"""
    
    def __init__(self, storage_dir: str = "db/career"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.resumes_file = self.storage_dir / "resumes.json"
        self.vacancies_file = self.storage_dir / "vacancies.json"
        self.applications_file = self.storage_dir / "applications.json"
        self.interviews_file = self.storage_dir / "interviews.json"
        self.progress_file = self.storage_dir / "progress.json"
        
        # Инициализируем файлы если их нет
        self._init_storage()
    
    def _init_storage(self):
        """Инициализация файлов хранения"""
        files = [
            self.resumes_file,
            self.vacancies_file,
            self.applications_file,
            self.interviews_file,
            self.progress_file
        ]
        for file_path in files:
            if not file_path.exists():
                self._save_json(file_path, {})
    
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
    
    def _validate_user_id(self, user_id: Optional[str]) -> str:
        """Валидация и нормализация user_id"""
        if not user_id or user_id in ["default_user", "anonymous", "guest", ""]:
            raise ValueError(f"Невалидный user_id: {user_id}. Данные должны быть привязаны к конкретному пользователю.")
        return str(user_id)
    
    # === Управление резюме ===
    
    def save_user_resume(self, user_id: str, resume_data: Dict[str, Any]) -> bool:
        """
        Сохранение резюме пользователя с привязкой к user_id
        
        Args:
            user_id: Идентификатор пользователя (обязательно)
            resume_data: Данные резюме
        
        Returns:
            True если успешно сохранено
        """
        try:
            user_id = self._validate_user_id(user_id)
            resumes_data = self._load_json(self.resumes_file)
            
            if user_id not in resumes_data:
                resumes_data[user_id] = {}
            
            resumes_data[user_id].update({
                **resume_data,
                "updated_at": datetime.now().isoformat()
            })
            
            # Сохраняем время создания при первом сохранении
            if "created_at" not in resumes_data[user_id]:
                resumes_data[user_id]["created_at"] = datetime.now().isoformat()
            
            self._save_json(self.resumes_file, resumes_data)
            logger.info(f"💾 Резюме сохранено для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения резюме для пользователя {user_id}: {e}")
            return False
    
    def get_user_resume(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение резюме пользователя по user_id
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Данные резюме или None
        """
        try:
            user_id = self._validate_user_id(user_id)
            resumes_data = self._load_json(self.resumes_file)
            return resumes_data.get(user_id)
        except Exception as e:
            logger.error(f"Ошибка получения резюме для пользователя {user_id}: {e}")
            return None
    
    # === Управление вакансиями ===
    
    def save_user_vacancy(self, user_id: str, vacancy_data: Dict[str, Any]) -> str:
        """
        Сохранение вакансии пользователя с привязкой к user_id
        
        Args:
            user_id: Идентификатор пользователя
            vacancy_data: Данные вакансии
        
        Returns:
            ID сохраненной вакансии
        """
        try:
            user_id = self._validate_user_id(user_id)
            vacancies_data = self._load_json(self.vacancies_file)
            
            if user_id not in vacancies_data:
                vacancies_data[user_id] = []
            
            # Генерируем ID вакансии
            vacancy_id = vacancy_data.get("id") or f"vacancy_{datetime.now().timestamp()}"
            vacancy_data["id"] = vacancy_id
            vacancy_data["user_id"] = user_id
            vacancy_data["saved_at"] = datetime.now().isoformat()
            
            # Проверяем, нет ли уже такой вакансии
            existing_index = None
            for i, v in enumerate(vacancies_data[user_id]):
                if v.get("id") == vacancy_id or v.get("source_url") == vacancy_data.get("source_url"):
                    existing_index = i
                    break
            
            if existing_index is not None:
                # Обновляем существующую
                vacancies_data[user_id][existing_index] = vacancy_data
            else:
                # Добавляем новую
                vacancies_data[user_id].append(vacancy_data)
            
            self._save_json(self.vacancies_file, vacancies_data)
            logger.info(f"💾 Вакансия сохранена для пользователя {user_id}: {vacancy_id}")
            return vacancy_id
            
        except Exception as e:
            logger.error(f"Ошибка сохранения вакансии для пользователя {user_id}: {e}")
            return ""
    
    def get_user_vacancies(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Получение всех вакансий пользователя
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Список вакансий
        """
        try:
            user_id = self._validate_user_id(user_id)
            vacancies_data = self._load_json(self.vacancies_file)
            return vacancies_data.get(user_id, [])
        except Exception as e:
            logger.error(f"Ошибка получения вакансий для пользователя {user_id}: {e}")
            return []
    
    def get_user_vacancy(self, user_id: str, vacancy_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение конкретной вакансии пользователя
        
        Args:
            user_id: Идентификатор пользователя
            vacancy_id: ID вакансии
        
        Returns:
            Данные вакансии или None
        """
        try:
            user_id = self._validate_user_id(user_id)
            vacancies = self.get_user_vacancies(user_id)
            for vacancy in vacancies:
                if vacancy.get("id") == vacancy_id:
                    return vacancy
            return None
        except Exception as e:
            logger.error(f"Ошибка получения вакансии {vacancy_id} для пользователя {user_id}: {e}")
            return None
    
    # === Управление откликами ===
    
    def save_application(self, user_id: str, application_data: Dict[str, Any]) -> str:
        """
        Сохранение отклика на вакансию с привязкой к user_id
        
        Args:
            user_id: Идентификатор пользователя
            application_data: Данные отклика
        
        Returns:
            ID сохраненного отклика
        """
        try:
            user_id = self._validate_user_id(user_id)
            applications_data = self._load_json(self.applications_file)
            
            if user_id not in applications_data:
                applications_data[user_id] = []
            
            # Генерируем ID отклика
            application_id = application_data.get("id") or f"app_{datetime.now().timestamp()}"
            application_data["id"] = application_id
            application_data["user_id"] = user_id
            application_data["applied_at"] = datetime.now().isoformat()
            application_data["status"] = application_data.get("status", "applied")
            
            # Проверяем, нет ли уже такого отклика
            existing_index = None
            for i, app in enumerate(applications_data[user_id]):
                if (app.get("vacancy_id") == application_data.get("vacancy_id") and 
                    app.get("vacancy_url") == application_data.get("vacancy_url")):
                    existing_index = i
                    break
            
            if existing_index is not None:
                # Обновляем существующий
                applications_data[user_id][existing_index].update(application_data)
            else:
                # Добавляем новый
                applications_data[user_id].append(application_data)
            
            self._save_json(self.applications_file, applications_data)
            logger.info(f"💾 Отклик сохранен для пользователя {user_id}: {application_id}")
            return application_id
            
        except Exception as e:
            logger.error(f"Ошибка сохранения отклика для пользователя {user_id}: {e}")
            return ""
    
    def get_user_applications(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Получение всех откликов пользователя
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Список откликов
        """
        try:
            user_id = self._validate_user_id(user_id)
            applications_data = self._load_json(self.applications_file)
            return applications_data.get(user_id, [])
        except Exception as e:
            logger.error(f"Ошибка получения откликов для пользователя {user_id}: {e}")
            return []
    
    def update_application_status(
        self,
        user_id: str,
        application_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        Обновление статуса отклика
        
        Args:
            user_id: Идентификатор пользователя
            application_id: ID отклика
            status: Новый статус (applied, viewed, interview, rejected, offer)
            notes: Дополнительные заметки
        
        Returns:
            True если успешно обновлено
        """
        try:
            user_id = self._validate_user_id(user_id)
            applications_data = self._load_json(self.applications_file)
            
            if user_id not in applications_data:
                return False
            
            for app in applications_data[user_id]:
                if app.get("id") == application_id:
                    app["status"] = status
                    app["updated_at"] = datetime.now().isoformat()
                    if notes:
                        app["notes"] = notes
                    if status == "viewed":
                        app["viewed_at"] = datetime.now().isoformat()
                    
                    self._save_json(self.applications_file, applications_data)
                    logger.info(f"💾 Статус отклика обновлен для пользователя {user_id}: {application_id} -> {status}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка обновления статуса отклика для пользователя {user_id}: {e}")
            return False
    
    # === Управление собеседованиями ===
    
    def save_interview(self, user_id: str, interview_data: Dict[str, Any]) -> str:
        """
        Сохранение приглашения на собеседование с привязкой к user_id
        
        Args:
            user_id: Идентификатор пользователя
            interview_data: Данные собеседования
        
        Returns:
            ID сохраненного собеседования
        """
        try:
            user_id = self._validate_user_id(user_id)
            interviews_data = self._load_json(self.interviews_file)
            
            if user_id not in interviews_data:
                interviews_data[user_id] = []
            
            interview_id = interview_data.get("id") or f"interview_{datetime.now().timestamp()}"
            interview_data["id"] = interview_id
            interview_data["user_id"] = user_id
            interview_data["status"] = interview_data.get("status", "scheduled")
            interview_data["created_at"] = datetime.now().isoformat()
            
            interviews_data[user_id].append(interview_data)
            self._save_json(self.interviews_file, interviews_data)
            logger.info(f"💾 Собеседование сохранено для пользователя {user_id}: {interview_id}")
            return interview_id
            
        except Exception as e:
            logger.error(f"Ошибка сохранения собеседования для пользователя {user_id}: {e}")
            return ""
    
    def get_user_interviews(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Получение всех собеседований пользователя
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Список собеседований
        """
        try:
            user_id = self._validate_user_id(user_id)
            interviews_data = self._load_json(self.interviews_file)
            return interviews_data.get(user_id, [])
        except Exception as e:
            logger.error(f"Ошибка получения собеседований для пользователя {user_id}: {e}")
            return []
    
    # === Управление прогрессом ===
    
    def save_user_progress(self, user_id: str, progress_data: Dict[str, Any]) -> bool:
        """
        Сохранение прогресса пользователя (статистика, метрики)
        
        Args:
            user_id: Идентификатор пользователя
            progress_data: Данные прогресса
        
        Returns:
            True если успешно сохранено
        """
        try:
            user_id = self._validate_user_id(user_id)
            progress_data_all = self._load_json(self.progress_file)
            
            if user_id not in progress_data_all:
                progress_data_all[user_id] = {}
            
            progress_data_all[user_id].update({
                **progress_data,
                "updated_at": datetime.now().isoformat()
            })
            
            self._save_json(self.progress_file, progress_data_all)
            logger.info(f"💾 Прогресс сохранен для пользователя {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения прогресса для пользователя {user_id}: {e}")
            return False
    
    def get_user_progress(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение прогресса пользователя
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Данные прогресса или None
        """
        try:
            user_id = self._validate_user_id(user_id)
            progress_data_all = self._load_json(self.progress_file)
            return progress_data_all.get(user_id)
        except Exception as e:
            logger.error(f"Ошибка получения прогресса для пользователя {user_id}: {e}")
            return None
    
    def get_user_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        Получение статистики пользователя по поиску работы
        
        Args:
            user_id: Идентификатор пользователя
        
        Returns:
            Словарь со статистикой
        """
        try:
            user_id = self._validate_user_id(user_id)
            
            applications = self.get_user_applications(user_id)
            interviews = self.get_user_interviews(user_id)
            
            stats = {
                "total_applications": len(applications),
                "applications_by_status": {},
                "total_interviews": len(interviews),
                "interviews_by_status": {},
                "total_vacancies_saved": len(self.get_user_vacancies(user_id))
            }
            
            # Статистика по статусам откликов
            for app in applications:
                status = app.get("status", "unknown")
                stats["applications_by_status"][status] = stats["applications_by_status"].get(status, 0) + 1
            
            # Статистика по статусам собеседований
            for interview in interviews:
                status = interview.get("status", "unknown")
                stats["interviews_by_status"][status] = stats["interviews_by_status"].get(status, 0) + 1
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики для пользователя {user_id}: {e}")
            return {}
    
    def delete_user_data(self, user_id: str):
        """
        Удаление всех данных пользователя (для GDPR compliance)
        
        Args:
            user_id: Идентификатор пользователя
        """
        try:
            user_id = self._validate_user_id(user_id)
            
            # Удаляем резюме
            resumes_data = self._load_json(self.resumes_file)
            if user_id in resumes_data:
                del resumes_data[user_id]
                self._save_json(self.resumes_file, resumes_data)
            
            # Удаляем вакансии
            vacancies_data = self._load_json(self.vacancies_file)
            if user_id in vacancies_data:
                del vacancies_data[user_id]
                self._save_json(self.vacancies_file, vacancies_data)
            
            # Удаляем отклики
            applications_data = self._load_json(self.applications_file)
            if user_id in applications_data:
                del applications_data[user_id]
                self._save_json(self.applications_file, applications_data)
            
            # Удаляем собеседования
            interviews_data = self._load_json(self.interviews_file)
            if user_id in interviews_data:
                del interviews_data[user_id]
                self._save_json(self.interviews_file, interviews_data)
            
            # Удаляем прогресс
            progress_data = self._load_json(self.progress_file)
            if user_id in progress_data:
                del progress_data[user_id]
                self._save_json(self.progress_file, progress_data)
            
            logger.info(f"🗑️ Все данные карьерного агента удалены для пользователя {user_id}")
            
        except Exception as e:
            logger.error(f"Ошибка удаления данных для пользователя {user_id}: {e}")


# Глобальный экземпляр хранилища
storage = CareerStorage()

