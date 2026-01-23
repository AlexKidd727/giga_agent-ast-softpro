"""
Тесты для проверки работы read_file и resolve_file_path в Docker окружении.

Проверяет:
1. resolve_file_path с разными вариантами путей
2. read_file с файлами, содержащими пробелы и скобки
3. Работу с user_id и изоляцией файлов
4. Нормализацию имен файлов

Запуск в Docker:
    docker-compose exec langgraph-api python -m pytest tests/test_read_file.py -v
    
Или напрямую:
    docker-compose exec langgraph-api python tests/test_read_file.py
"""

import os
import sys
import tempfile
import shutil
import importlib
from pathlib import Path
from typing import Optional

# Добавляем путь к модулям
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, "../../repl/app"))
sys.path.insert(0, os.path.join(base_dir, "../.."))

import pytest
import asyncio

# Импортируем тестируемые функции
try:
    from user_files_utils import resolve_file_path, normalize_filename, get_user_file_path, get_user_files_dir
except ImportError:
    # Пробуем альтернативный путь
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
    from user_files_utils import resolve_file_path, normalize_filename, get_user_file_path, get_user_files_dir

try:
    from giga_agent.agents.pc_agent.nodes.files import read_file
except ImportError:
    # Пробуем альтернативный путь
    sys.path.insert(0, os.path.join(base_dir, "giga_agent"))
    from agents.pc_agent.nodes.files import read_file


class TestNormalizeFilename:
    """Тесты для функции normalize_filename"""
    
    def test_normalize_spaces_before_parentheses(self):
        """Проверяет нормализацию пробелов перед скобками"""
        assert normalize_filename("archive (5).zip") == "archive(5).zip"
        assert normalize_filename("audio (1).txt") == "audio(1).txt"
        assert normalize_filename("file (test).pdf") == "file(test).pdf"
    
    def test_normalize_spaces_after_parentheses(self):
        """Проверяет нормализацию пробелов после скобок"""
        assert normalize_filename("archive( 5 ).zip") == "archive(5).zip"
        assert normalize_filename("file( test ).txt") == "file(test).txt"
    
    def test_no_changes_needed(self):
        """Проверяет, что нормальные имена не изменяются"""
        assert normalize_filename("normal_file.txt") == "normal_file.txt"
        assert normalize_filename("archive(5).zip") == "archive(5).zip"
        assert normalize_filename("file_without_spaces.txt") == "file_without_spaces.txt"


class TestResolveFilePath:
    """Тесты для функции resolve_file_path"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        # Сохраняем оригинальное значение FILES_DIR
        self.original_files_dir = os.environ.get("FILES_DIR", "files")
        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="test_files_")
        os.environ["FILES_DIR"] = self.test_dir
        # Обновляем FILES_DIR в модуле
        import user_files_utils
        user_files_utils.FILES_DIR = self.test_dir
        # Перезагружаем модуль, чтобы применить изменения
        importlib.reload(user_files_utils)
    
    def teardown_method(self):
        """Очистка после каждого теста"""
        # Восстанавливаем оригинальное значение
        os.environ["FILES_DIR"] = self.original_files_dir
        # Удаляем временную директорию
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_resolve_file_in_user_directory(self):
        """Проверяет поиск файла в папке пользователя"""
        user_id = "test_user_123"
        filename = "test_file.txt"
        
        # Создаем структуру папок и файл
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / filename
        test_file.write_text("test content")
        
        # Проверяем поиск файла
        resolved = resolve_file_path(filename, user_id)
        assert resolved is not None
        assert resolved.exists()
        assert resolved == test_file
    
    def test_resolve_file_with_spaces_in_name(self):
        """Проверяет поиск файла с пробелами в имени"""
        user_id = "test_user_123"
        filename = "audio (1).txt"
        normalized_filename = "audio(1).txt"
        
        # Создаем файл с нормализованным именем (как при загрузке)
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / normalized_filename
        test_file.write_text("test content")
        
        # Проверяем поиск по оригинальному имени (с пробелами)
        resolved = resolve_file_path(filename, user_id)
        assert resolved is not None
        assert resolved.exists()
        assert resolved == test_file
    
    def test_resolve_file_with_user_id_in_path(self):
        """Проверяет поиск файла с user_id в пути"""
        user_id = "740cd143-0353-4360-a3d6-a8cb86e00ef6"
        file_path = f"{user_id}/audio (1).txt"
        normalized_filename = "audio(1).txt"
        
        # Создаем файл с нормализованным именем
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / normalized_filename
        test_file.write_text("test content")
        
        # Проверяем поиск по пути с user_id
        resolved = resolve_file_path(file_path, user_id)
        assert resolved is not None
        assert resolved.exists()
        assert resolved == test_file
    
    def test_resolve_file_not_found(self):
        """Проверяет возврат None для несуществующего файла"""
        user_id = "test_user_123"
        filename = "nonexistent_file.txt"
        
        resolved = resolve_file_path(filename, user_id)
        assert resolved is None
    
    def test_resolve_file_without_user_id(self):
        """Проверяет поиск файла без указания user_id"""
        filename = "common_file.txt"
        
        # Создаем файл в общей папке
        test_file = Path(self.test_dir) / filename
        test_file.write_text("test content")
        
        # Проверяем поиск без user_id
        resolved = resolve_file_path(filename, None)
        assert resolved is not None
        assert resolved.exists()
        assert resolved == test_file


class TestReadFile:
    """Тесты для инструмента read_file"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        # Сохраняем оригинальное значение FILES_DIR
        self.original_files_dir = os.environ.get("FILES_DIR", "files")
        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix="test_files_")
        os.environ["FILES_DIR"] = self.test_dir
        # Обновляем FILES_DIR в модуле
        import user_files_utils
        user_files_utils.FILES_DIR = self.test_dir
        # Перезагружаем модуль, чтобы применить изменения
        importlib.reload(user_files_utils)
    
    def teardown_method(self):
        """Очистка после каждого теста"""
        # Восстанавливаем оригинальное значение
        os.environ["FILES_DIR"] = self.original_files_dir
        # Удаляем временную директорию
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    @pytest.mark.asyncio
    async def test_read_file_simple(self):
        """Проверяет чтение простого файла"""
        user_id = "test_user_123"
        filename = "simple_file.txt"
        content = "Test file content"
        
        # Создаем файл
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / filename
        test_file.write_text(content)
        
        # Читаем файл (read_file - это инструмент, вызываем через ainvoke)
        state = {"user_id": user_id}
        result = await read_file.ainvoke({"file_path": filename, "user_id": user_id, "state": state})
        
        assert result["success"] is True
        assert content in result["message"]
        assert result["file_path"] == str(test_file)
    
    @pytest.mark.asyncio
    async def test_read_file_with_spaces(self):
        """Проверяет чтение файла с пробелами в имени"""
        user_id = "740cd143-0353-4360-a3d6-a8cb86e00ef6"
        filename_with_spaces = "audio (1).txt"
        normalized_filename = "audio(1).txt"
        content = "Audio file content"
        
        # Создаем файл с нормализованным именем (как при загрузке)
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / normalized_filename
        test_file.write_text(content)
        
        # Читаем файл по пути с пробелами
        file_path = f"{user_id}/{filename_with_spaces}"
        state = {"user_id": user_id}
        result = await read_file.ainvoke({"file_path": file_path, "user_id": user_id, "state": state})
        
        assert result["success"] is True
        assert content in result["message"]
        assert result["file_path"] == str(test_file)
    
    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        """Проверяет обработку несуществующего файла"""
        user_id = "test_user_123"
        filename = "nonexistent_file.txt"
        
        state = {"user_id": user_id}
        result = await read_file.ainvoke({"file_path": filename, "user_id": user_id, "state": state})
        
        assert result["error"] is True
        assert "не существует" in result["message"].lower() or "not found" in result["message"].lower()
    
    @pytest.mark.asyncio
    async def test_read_file_with_user_id_from_state(self):
        """Проверяет использование user_id из state"""
        user_id = "test_user_123"
        filename = "state_file.txt"
        content = "Content from state"
        
        # Создаем файл
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / filename
        test_file.write_text(content)
        
        # Читаем файл, передавая user_id только через state
        state = {"user_id": user_id}
        result = await read_file.ainvoke({"file_path": filename, "user_id": "default_user", "state": state})
        
        assert result["success"] is True
        assert content in result["message"]
        assert result["file_path"] == str(test_file)
    
    @pytest.mark.asyncio
    async def test_read_file_csv(self):
        """Проверяет чтение CSV файла"""
        user_id = "test_user_123"
        filename = "data.csv"
        content = "name,age\nJohn,30\nJane,25"
        
        # Создаем CSV файл
        user_dir = Path(self.test_dir) / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        test_file = user_dir / filename
        test_file.write_text(content)
        
        # Читаем файл (read_file - это инструмент, вызываем через ainvoke)
        state = {"user_id": user_id}
        result = await read_file.ainvoke({"file_path": filename, "user_id": user_id, "state": state})
        
        assert result["success"] is True
        assert "name" in result["message"]
        assert "age" in result["message"]


def run_tests():
    """Запуск всех тестов"""
    print("=" * 80)
    print("Запуск тестов для read_file и resolve_file_path")
    print("=" * 80)
    
    # Запускаем pytest
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    
    if exit_code == 0:
        print("\n" + "=" * 80)
        print("Все тесты пройдены успешно!")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print(f"Тесты завершились с ошибками (код выхода: {exit_code})")
        print("=" * 80)
    
    return exit_code


if __name__ == "__main__":
    exit(run_tests())
