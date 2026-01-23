"""
Инструмент для проверки кода (code review)
Проверяет файл линтером, логические ошибки, компиляцию и выдает предложения для доработки
"""

import os
import logging
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Annotated, Optional, Dict, List
from enum import Enum

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import Field

logger = logging.getLogger(__name__)

# Путь к папке с файлами проекта
FILES_DIR = os.getenv("FILES_DIR", "/files")

# Импортируем утилиты для работы с файлами пользователей
try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../repl/app"))
    from user_files_utils import resolve_file_path, get_user_files_dir, get_user_file_path
except ImportError:
    # Fallback если модуль недоступен
    def resolve_file_path(file_path, user_id=None):
        potential_path = os.path.join(FILES_DIR, file_path.lstrip("/"))
        if os.path.exists(potential_path):
            return Path(potential_path)
        if os.path.exists(file_path):
            return Path(file_path)
        return None
    def get_user_files_dir(user_id):
        return Path(FILES_DIR)
    def get_user_file_path(user_id, filename):
        return Path(FILES_DIR) / filename


class LanguageType(str, Enum):
    """Типы языков программирования"""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    CPP = "cpp"
    C = "c"
    GO = "go"
    RUST = "rust"
    PHP = "php"
    RUBY = "ruby"
    UNKNOWN = "unknown"


def detect_language(file_path: Path) -> LanguageType:
    """Определяет язык программирования по расширению файла"""
    ext = file_path.suffix.lower()
    
    language_map = {
        '.py': LanguageType.PYTHON,
        '.js': LanguageType.JAVASCRIPT,
        '.jsx': LanguageType.JAVASCRIPT,
        '.ts': LanguageType.TYPESCRIPT,
        '.tsx': LanguageType.TYPESCRIPT,
        '.java': LanguageType.JAVA,
        '.cpp': LanguageType.CPP,
        '.cc': LanguageType.CPP,
        '.cxx': LanguageType.CPP,
        '.c': LanguageType.C,
        '.go': LanguageType.GO,
        '.rs': LanguageType.RUST,
        '.php': LanguageType.PHP,
        '.rb': LanguageType.RUBY,
    }
    
    return language_map.get(ext, LanguageType.UNKNOWN)


async def _run_linter(file_path: Path, language: LanguageType) -> Dict[str, any]:
    """Запускает линтер для файла"""
    results = {
        "linter_errors": [],
        "linter_warnings": [],
        "linter_output": "",
        "success": False
    }
    
    try:
        if language == LanguageType.PYTHON:
            # Пробуем разные линтеры для Python
            linters = [
                ("ruff", ["ruff", "check", str(file_path)]),
                ("flake8", ["flake8", str(file_path)]),
                ("pylint", ["pylint", "--output-format=json", str(file_path)]),
            ]
            
            for linter_name, cmd in linters:
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(file_path.parent)
                    )
                    
                    if result.returncode == 0:
                        results["linter_output"] = f"{linter_name}: проверка пройдена"
                        results["success"] = True
                        break
                    else:
                        output = result.stdout + result.stderr
                        results["linter_output"] = f"{linter_name}:\n{output}"
                        
                        # Парсим вывод pylint (JSON)
                        if linter_name == "pylint" and output.strip():
                            try:
                                pylint_data = json.loads(output)
                                for item in pylint_data:
                                    if item.get("type") == "error":
                                        results["linter_errors"].append({
                                            "line": item.get("line", 0),
                                            "message": item.get("message", ""),
                                            "symbol": item.get("symbol", "")
                                        })
                                    elif item.get("type") == "warning":
                                        results["linter_warnings"].append({
                                            "line": item.get("line", 0),
                                            "message": item.get("message", ""),
                                            "symbol": item.get("symbol", "")
                                        })
                            except json.JSONDecodeError:
                                # Если не JSON, парсим как текст
                                for line in output.split('\n'):
                                    if 'error' in line.lower() or 'E' in line:
                                        results["linter_errors"].append({"message": line})
                                    elif 'warning' in line.lower() or 'W' in line:
                                        results["linter_warnings"].append({"message": line})
                        else:
                            # Парсим вывод flake8/ruff
                            for line in output.split('\n'):
                                if line.strip():
                                    if 'error' in line.lower() or 'E' in line or 'F' in line:
                                        results["linter_errors"].append({"message": line})
                                    elif 'warning' in line.lower() or 'W' in line:
                                        results["linter_warnings"].append({"message": line})
                        
                        results["success"] = len(results["linter_errors"]) == 0
                except FileNotFoundError:
                    continue
                except subprocess.TimeoutExpired:
                    logger.warning(f"Линтер {linter_name} превысил время ожидания")
                    continue
        
        elif language == LanguageType.JAVASCRIPT:
            # ESLint для JavaScript
            try:
                result = subprocess.run(
                    ["eslint", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(file_path.parent)
                )
                
                if result.returncode == 0:
                    results["linter_output"] = "eslint: проверка пройдена"
                    results["success"] = True
                else:
                    output = result.stdout + result.stderr
                    results["linter_output"] = f"eslint:\n{output}"
                    
                    for line in output.split('\n'):
                        if line.strip() and ('error' in line.lower() or '✖' in line):
                            results["linter_errors"].append({"message": line})
                        elif 'warning' in line.lower():
                            results["linter_warnings"].append({"message": line})
            except FileNotFoundError:
                results["linter_output"] = "eslint не установлен. Установите: npm install -g eslint"
        
        elif language == LanguageType.TYPESCRIPT:
            # TSC для TypeScript
            try:
                result = subprocess.run(
                    ["tsc", "--noEmit", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(file_path.parent)
                )
                
                if result.returncode == 0:
                    results["linter_output"] = "tsc: проверка пройдена"
                    results["success"] = True
                else:
                    output = result.stdout + result.stderr
                    results["linter_output"] = f"tsc:\n{output}"
                    
                    for line in output.split('\n'):
                        if line.strip() and ('error' in line.lower() or 'TS' in line):
                            results["linter_errors"].append({"message": line})
            except FileNotFoundError:
                results["linter_output"] = "tsc не установлен. Установите: npm install -g typescript"
        
        # Для других языков можно добавить соответствующие линтеры
        
    except Exception as e:
        logger.error(f"Ошибка при запуске линтера: {e}")
        results["linter_output"] = f"Ошибка при запуске линтера: {str(e)}"
    
    return results


async def _check_compilation(file_path: Path, language: LanguageType) -> Dict[str, any]:
    """Проверяет компиляцию файла (для компилируемых языков)"""
    results = {
        "compilation_errors": [],
        "compilation_warnings": [],
        "compilation_output": "",
        "success": False
    }
    
    try:
        if language == LanguageType.PYTHON:
            # Python - проверка синтаксиса
            try:
                result = subprocess.run(
                    ["python", "-m", "py_compile", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    results["compilation_output"] = "Синтаксис Python корректен"
                    results["success"] = True
                else:
                    output = result.stderr
                    results["compilation_output"] = f"Ошибки синтаксиса:\n{output}"
                    results["compilation_errors"] = [{"message": line} for line in output.split('\n') if line.strip()]
            except Exception as e:
                results["compilation_output"] = f"Ошибка проверки синтаксиса: {str(e)}"
        
        elif language == LanguageType.JAVA:
            # Java - компиляция
            try:
                result = subprocess.run(
                    ["javac", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(file_path.parent)
                )
                
                if result.returncode == 0:
                    results["compilation_output"] = "Компиляция Java успешна"
                    results["success"] = True
                else:
                    output = result.stderr + result.stdout
                    results["compilation_output"] = f"Ошибки компиляции:\n{output}"
                    results["compilation_errors"] = [{"message": line} for line in output.split('\n') if line.strip()]
            except FileNotFoundError:
                results["compilation_output"] = "javac не установлен"
        
        elif language == LanguageType.CPP or language == LanguageType.C:
            # C/C++ - компиляция (только проверка синтаксиса)
            compiler = "g++" if language == LanguageType.CPP else "gcc"
            try:
                # Создаем временный объектный файл
                with tempfile.NamedTemporaryFile(suffix='.o', delete=False) as tmp_file:
                    tmp_obj = tmp_file.name
                
                try:
                    result = subprocess.run(
                        [compiler, "-c", str(file_path), "-o", tmp_obj],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if result.returncode == 0:
                        results["compilation_output"] = f"Компиляция {compiler} успешна"
                        results["success"] = True
                    else:
                        output = result.stderr
                        results["compilation_output"] = f"Ошибки компиляции:\n{output}"
                        results["compilation_errors"] = [{"message": line} for line in output.split('\n') if line.strip()]
                finally:
                    if os.path.exists(tmp_obj):
                        os.unlink(tmp_obj)
            except FileNotFoundError:
                results["compilation_output"] = f"{compiler} не установлен"
        
        elif language == LanguageType.GO:
            # Go - проверка компиляции
            try:
                result = subprocess.run(
                    ["go", "build", "-o", os.devnull, str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(file_path.parent)
                )
                
                if result.returncode == 0:
                    results["compilation_output"] = "Компиляция Go успешна"
                    results["success"] = True
                else:
                    output = result.stderr + result.stdout
                    results["compilation_output"] = f"Ошибки компиляции:\n{output}"
                    results["compilation_errors"] = [{"message": line} for line in output.split('\n') if line.strip()]
            except FileNotFoundError:
                results["compilation_output"] = "go не установлен"
        
        elif language == LanguageType.RUST:
            # Rust - проверка компиляции
            try:
                result = subprocess.run(
                    ["rustc", "--crate-type", "lib", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    results["compilation_output"] = "Проверка Rust успешна"
                    results["success"] = True
                else:
                    output = result.stderr + result.stdout
                    results["compilation_output"] = f"Ошибки компиляции:\n{output}"
                    results["compilation_errors"] = [{"message": line} for line in output.split('\n') if line.strip()]
            except FileNotFoundError:
                results["compilation_output"] = "rustc не установлен"
        
    except Exception as e:
        logger.error(f"Ошибка при проверке компиляции: {e}")
        results["compilation_output"] = f"Ошибка при проверке компиляции: {str(e)}"
    
    return results


async def _analyze_logical_errors(file_path: Path, language: LanguageType, file_content: str) -> Dict[str, any]:
    """Анализирует код на логические ошибки (базовый анализ)"""
    results = {
        "logical_issues": [],
        "suggestions": []
    }
    
    try:
        # Базовые проверки для Python
        if language == LanguageType.PYTHON:
            lines = file_content.split('\n')
            
            # Проверка на неиспользуемые импорты
            imports = []
            for i, line in enumerate(lines, 1):
                if line.strip().startswith('import ') or line.strip().startswith('from '):
                    imports.append((i, line.strip()))
            
            # Проверка на потенциальные проблемы
            for i, line in enumerate(lines, 1):
                # Проверка на сравнение с None через ==
                if ' == None' in line or ' != None' in line:
                    results["logical_issues"].append({
                        "line": i,
                        "type": "style",
                        "message": "Используйте 'is None' или 'is not None' вместо '== None' или '!= None'"
                    })
                
                # Проверка на пустые except блоки
                if line.strip() == 'except:' or line.strip().startswith('except:') and 'pass' in lines[i:i+2]:
                    results["logical_issues"].append({
                        "line": i,
                        "type": "error",
                        "message": "Избегайте пустых except блоков, указывайте конкретные исключения"
                    })
                
                # Проверка на использование eval/exec
                if 'eval(' in line or 'exec(' in line:
                    results["logical_issues"].append({
                        "line": i,
                        "type": "security",
                        "message": "Использование eval/exec может быть небезопасным"
                    })
        
        # Базовые проверки для JavaScript
        elif language == LanguageType.JAVASCRIPT:
            lines = file_content.split('\n')
            
            for i, line in enumerate(lines, 1):
                # Проверка на == вместо ===
                if ' == ' in line and ' === ' not in line and '==' not in line:
                    results["logical_issues"].append({
                        "line": i,
                        "type": "style",
                        "message": "Рекомендуется использовать строгое сравнение === вместо =="
                    })
                
                # Проверка на var вместо let/const
                if ' var ' in line:
                    results["logical_issues"].append({
                        "line": i,
                        "type": "style",
                        "message": "Рекомендуется использовать let или const вместо var"
                    })
        
    except Exception as e:
        logger.error(f"Ошибка при анализе логических ошибок: {e}")
    
    return results


@tool(parse_docstring=True)
async def code_review(
    file_path: Annotated[
        str,
        Field(description="Путь к файлу для проверки. Может быть локальным путем или относительным путем от папки пользователя"),
    ],
    apply_fixes: Annotated[
        bool,
        Field(
            description="Применить автоматические исправления после проверки (если поддерживается)",
            default=False
        ),
    ] = False,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Проводит комплексную проверку кода: линтер, логические ошибки, компиляция.
    Выдает предложения для доработки и может применить правки после подтверждения.
    
    Проверяет:
    - Линтер (flake8, ruff, pylint для Python; eslint для JS; tsc для TS и т.д.)
    - Логические ошибки (базовый статический анализ)
    - Компиляцию/синтаксис (для компилируемых языков)
    
    Args:
        file_path: Путь к файлу для проверки
        apply_fixes: Применить автоматические исправления (если поддерживается линтером)
    
    Returns:
        JSON строка с результатами проверки:
        {
            "success": true/false,
            "language": "python/javascript/etc",
            "linter": {результаты линтера},
            "compilation": {результаты компиляции},
            "logical_analysis": {результаты логического анализа},
            "suggestions": [список предложений],
            "applied_fixes": [список примененных исправлений] (если apply_fixes=true)
        }
    
    Examples:
        - code_review("my_script.py")
        - code_review("/files/user123/app.js", apply_fixes=True)
    """
    try:
        # Получаем user_id из state
        user_id = None
        if state:
            user_id = state.get("user_id")
            if user_id in ["default_user", "anonymous", "guest", ""]:
                user_id = None
        
        # Разрешаем путь к файлу
        resolved_path = resolve_file_path(file_path, user_id)
        
        if not resolved_path or not resolved_path.exists():
            # Пробуем найти файл в других местах с нормализацией имен
            clean_path = file_path.lstrip("/")
            potential_paths = [
                file_path,
                os.path.join(FILES_DIR, clean_path),
                os.path.abspath(file_path),
            ]
            
            # Пробуем нормализованные варианты
            try:
                from user_files_utils import normalize_filename
                normalized_path = normalize_filename(clean_path)
                if normalized_path != clean_path:
                    potential_paths.append(os.path.join(FILES_DIR, normalized_path))
                    if user_id:
                        filename = os.path.basename(normalized_path)
                        potential_paths.append(os.path.join(FILES_DIR, user_id, filename))
            except:
                pass
            
            # Если есть user_id, пробуем найти в его папке
            if user_id:
                filename = os.path.basename(clean_path)
                potential_paths.insert(0, os.path.join(FILES_DIR, user_id, filename))
                # Пробуем с нормализованным именем
                try:
                    from user_files_utils import normalize_filename
                    normalized_name = normalize_filename(filename)
                    if normalized_name != filename:
                        potential_paths.insert(0, os.path.join(FILES_DIR, user_id, normalized_name))
                except:
                    pass
            
            resolved_path = None
            for path in potential_paths:
                if os.path.exists(path):
                    resolved_path = Path(path)
                    break
            
            if not resolved_path:
                return json.dumps({
                    "success": False,
                    "error": f"Файл не найден: {file_path}",
                    "language": "unknown"
                }, ensure_ascii=False)
        
        # Определяем язык программирования
        language = detect_language(resolved_path)
        
        # Читаем содержимое файла
        try:
            with open(resolved_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
        except UnicodeDecodeError:
            # Пробуем другие кодировки
            with open(resolved_path, 'r', encoding='cp1251') as f:
                file_content = f.read()
        
        # Запускаем проверки
        linter_results = await _run_linter(resolved_path, language)
        compilation_results = await _check_compilation(resolved_path, language)
        logical_results = await _analyze_logical_errors(resolved_path, language, file_content)
        
        # Формируем предложения
        suggestions = []
        
        if linter_results.get("linter_errors"):
            suggestions.append({
                "type": "linter_error",
                "priority": "high",
                "message": f"Найдено {len(linter_results['linter_errors'])} ошибок линтера",
                "details": linter_results["linter_errors"][:5]  # Первые 5 ошибок
            })
        
        if linter_results.get("linter_warnings"):
            suggestions.append({
                "type": "linter_warning",
                "priority": "medium",
                "message": f"Найдено {len(linter_results['linter_warnings'])} предупреждений линтера",
                "details": linter_results["linter_warnings"][:5]
            })
        
        if compilation_results.get("compilation_errors"):
            suggestions.append({
                "type": "compilation_error",
                "priority": "high",
                "message": f"Найдено {len(compilation_results['compilation_errors'])} ошибок компиляции",
                "details": compilation_results["compilation_errors"][:5]
            })
        
        if logical_results.get("logical_issues"):
            suggestions.append({
                "type": "logical_issue",
                "priority": "medium",
                "message": f"Найдено {len(logical_results['logical_issues'])} потенциальных проблем",
                "details": logical_results["logical_issues"][:5]
            })
        
        # Применяем исправления, если запрошено
        applied_fixes = []
        if apply_fixes:
            if language == LanguageType.PYTHON:
                # Пробуем автоматические исправления через ruff
                try:
                    result = subprocess.run(
                        ["ruff", "check", "--fix", str(resolved_path)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(resolved_path.parent)
                    )
                    
                    if result.returncode == 0 or "Fixed" in result.stdout:
                        applied_fixes.append("Применены автоматические исправления через ruff")
                except FileNotFoundError:
                    pass
                except Exception as e:
                    logger.warning(f"Не удалось применить автоматические исправления: {e}")
            
            elif language == LanguageType.JAVASCRIPT:
                # Пробуем автоматические исправления через eslint
                try:
                    result = subprocess.run(
                        ["eslint", "--fix", str(resolved_path)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(resolved_path.parent)
                    )
                    
                    if result.returncode == 0 or "fixed" in result.stdout.lower():
                        applied_fixes.append("Применены автоматические исправления через eslint")
                except FileNotFoundError:
                    pass
                except Exception as e:
                    logger.warning(f"Не удалось применить автоматические исправления: {e}")
        
        # Формируем итоговый результат
        result = {
            "success": (
                linter_results.get("success", False) and
                compilation_results.get("success", True) and
                len(logical_results.get("logical_issues", [])) == 0
            ),
            "language": language.value,
            "file_path": str(resolved_path),
            "linter": linter_results,
            "compilation": compilation_results,
            "logical_analysis": logical_results,
            "suggestions": suggestions,
            "summary": {
                "total_errors": len(linter_results.get("linter_errors", [])) + len(compilation_results.get("compilation_errors", [])),
                "total_warnings": len(linter_results.get("linter_warnings", [])),
                "total_issues": len(logical_results.get("logical_issues", []))
            }
        }
        
        if applied_fixes:
            result["applied_fixes"] = applied_fixes
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        error_msg = f"Ошибка при проверке кода {file_path}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "language": "unknown"
        }, ensure_ascii=False)
