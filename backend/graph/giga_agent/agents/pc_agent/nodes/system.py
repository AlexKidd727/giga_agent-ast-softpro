"""
Узлы для системных операций PC Management Agent
"""

import os
import subprocess
import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.system_utils import (
    get_installed_programs, find_program_by_name, get_system_statistics,
    get_process_info, is_executable_safe
)
from ..config import IS_WINDOWS, COMMON_PROGRAMS, DANGEROUS_PROGRAMS

logger = logging.getLogger(__name__)

@tool
async def get_system_info(user_id: str = "default_user", state: Annotated[dict, InjectedState] = None):
    """
    Получение информации о системе
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        stats = get_system_statistics()
        
        if "error" in stats:
            return {
                "error": True,
                "message": f"❌ **Ошибка получения информации о системе:** {stats['error']}"
            }
        
        # Форматируем информацию
        message = f"""🖥️ **Информация о системе**

💻 **Платформа:**
• Система: {stats['platform']['system']} {stats['platform']['release']}
• Версия: {stats['platform']['version']}
• Архитектура: {stats['platform']['machine']}
• Процессор: {stats['platform']['processor']}

⚡ **Процессор:**
• Ядер: {stats['cpu']['count']}
• Загрузка: {stats['cpu']['percent']:.1f}%"""

        if stats['cpu']['frequency']:
            message += f"\n• Частота: {stats['cpu']['frequency']['current']:.0f} MHz"

        message += f"""

🧠 **Память:**
• Всего: {stats['memory']['total']}
• Доступно: {stats['memory']['available']}
• Использовано: {stats['memory']['used']} ({stats['memory']['percent']:.1f}%)

💾 **Диски:**"""

        for disk in stats['disks'][:3]:  # Показываем максимум 3 диска
            message += f"""
• **{disk['device']}** ({disk['fstype']})
  - Размер: {disk['total']}
  - Свободно: {disk['free']} ({100-disk['percent']:.1f}%)"""

        message += f"""

🌐 **Сеть:**
• Отправлено: {stats['network']['bytes_sent']}
• Получено: {stats['network']['bytes_recv']}

⏰ **Время работы системы:** {int((os.times().elapsed if hasattr(os, 'times') else 0) / 3600)} часов"""

        return {
            "success": True,
            "message": message,
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения информации о системе: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения информации о системе:** {str(e)}"
        }

@tool
async def run_program(
    program_name: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Запуск программы
    
    Args:
        program_name: Название программы для запуска
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        # Нормализуем имя программы для проверки
        program_lower = program_name.lower().strip()
        
        # Проверяем, не является ли программа опасной
        if program_lower in DANGEROUS_PROGRAMS:
            return {
                "error": True,
                "message": f"❌ **Запуск программы '{program_name}' заблокирован по соображениям безопасности**\n\n⚠️ Эта программа может быть опасна для системы."
            }
        
        # Поиск программы
        program_path = find_program_by_name(program_name)
        
        if not program_path:
            # Проверяем популярные программы
            if program_lower in COMMON_PROGRAMS:
                program_path = COMMON_PROGRAMS[program_lower]
            else:
                available_programs = list(COMMON_PROGRAMS.keys())[:10]
                return {
                    "error": True,
                    "message": f"❌ **Программа '{program_name}' не найдена**\n\n📋 **Доступные программы:**\n" + 
                              "\n".join([f"• {prog}" for prog in available_programs])
                }
        
        # Проверка безопасности: блокируем только программы из черного списка
        # Все остальные программы разрешены
        program_path_lower = program_path.lower() if program_path else ""
        
        # Проверяем, не является ли программа опасной по имени или пути
        is_dangerous = (
            program_lower in DANGEROUS_PROGRAMS or 
            program_path_lower in DANGEROUS_PROGRAMS or
            any(dangerous_prog in program_path_lower for dangerous_prog in DANGEROUS_PROGRAMS if dangerous_prog.endswith('.exe'))
        )
        
        if is_dangerous:
            return {
                "error": True,
                "message": f"❌ **Запуск программы '{program_name}' заблокирован по соображениям безопасности**\n\n⚠️ Эта программа может быть опасна для системы."
            }
        
        # Запуск программы
        try:
            if program_path.endswith(('.exe', '.bat', '.cmd')):
                # Запуск исполняемого файла
                process = subprocess.Popen(
                    program_path,
                    shell=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                return {
                    "success": True,
                    "message": f"✅ **Программа запущена:** {program_name}\n\n🆔 **PID процесса:** {process.pid}",
                    "program_name": program_name,
                    "program_path": program_path,
                    "pid": process.pid
                }
            else:
                # Запуск через ассоциации файлов
                subprocess.run(['start', '', program_path], shell=True, check=True)
                
                return {
                    "success": True,
                    "message": f"✅ **Программа запущена:** {program_name}\n\n📁 **Путь:** {program_path}",
                    "program_name": program_name,
                    "program_path": program_path
                }
                
        except subprocess.CalledProcessError as e:
            return {
                "error": True,
                "message": f"❌ **Ошибка запуска программы:** {str(e)}"
            }
        except Exception as e:
            return {
                "error": True,
                "message": f"❌ **Неожиданная ошибка при запуске:** {str(e)}"
            }
            
    except Exception as e:
        logger.error(f"Ошибка запуска программы {program_name}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка запуска программы:** {str(e)}"
        }

@tool
async def list_programs(user_id: str = "default_user", state: Annotated[dict, InjectedState] = None):
    """
    Получение списка установленных программ
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        programs = get_installed_programs()
        
        if not programs or (len(programs) == 1 and "ошибка" in programs[0].lower()):
            return {
                "error": True,
                "message": "❌ **Не удалось получить список программ**"
            }
        
        # Группируем программы
        popular_programs = [prog for prog in COMMON_PROGRAMS.keys()]
        other_programs = [prog for prog in programs if prog.lower() not in [p.lower() for p in popular_programs]]
        
        message = "📋 **Установленные программы**\n\n"
        message += "💡 **Используйте команду `run_program` с именем программы для запуска**\n\n"
        
        # Популярные программы
        if popular_programs:
            message += "⭐ **Популярные программы:**\n"
            for prog in popular_programs[:15]:
                message += f"• {prog}\n"
            if len(popular_programs) > 15:
                message += f"... и еще {len(popular_programs) - 15} популярных программ\n"
        
        # Другие программы
        if other_programs:
            message += f"\n📦 **Все установленные программы** (показано {min(50, len(other_programs))} из {len(other_programs)}):\n"
            for prog in other_programs[:50]:
                message += f"• {prog}\n"
            if len(other_programs) > 50:
                message += f"... и еще {len(other_programs) - 50} программ\n"
        
        message += f"\n💡 **Всего найдено:** {len(programs)} программ"
        message += f"\n\n⚠️ **Заблокированы:** regedit, msconfig, format, fdisk и другие опасные программы"
        
        return {
            "success": True,
            "message": message,
            "programs_count": len(programs),
            "popular_programs": popular_programs,
            "other_programs": other_programs
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения списка программ: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения списка программ:** {str(e)}"
        }

@tool
async def get_process_list(
    process_name: str = None,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение списка запущенных процессов
    
    Args:
        process_name: Название процесса для фильтрации (необязательно)
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        processes = get_process_info(name=process_name)
        
        if not processes or (len(processes) == 1 and "error" in processes[0]):
            error_msg = processes[0].get("error", "Неизвестная ошибка") if processes else "Процессы не найдены"
            return {
                "error": True,
                "message": f"❌ **Ошибка получения процессов:** {error_msg}"
            }
        
        # Форматируем список процессов
        if process_name:
            message = f"🔍 **Процессы содержащие '{process_name}':**\n\n"
        else:
            message = f"📊 **Запущенные процессы** (показано {len(processes)}):\n\n"
        
        for proc in processes[:25]:  # Ограничиваем вывод
            if "error" in proc:
                continue
                
            cpu_percent = proc.get('cpu_percent', 0)
            memory_percent = proc.get('memory_percent', 0)
            memory_rss = proc.get('memory_rss', 'N/A')
            
            message += f"**{proc['name']}** (PID: {proc['pid']})\n"
            message += f"  • CPU: {cpu_percent:.1f}% | RAM: {memory_percent:.1f}% ({memory_rss})\n"
            message += f"  • Статус: {proc.get('status', 'Unknown')}\n\n"
        
        if len(processes) > 25:
            message += f"... и еще {len(processes) - 25} процессов"
        
        return {
            "success": True,
            "message": message,
            "processes_count": len(processes),
            "filtered": process_name is not None
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения списка процессов: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения списка процессов:** {str(e)}"
        }

@tool
async def kill_process(
    process_identifier: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Завершение процесса по PID или имени
    
    Args:
        process_identifier: PID процесса или название процесса
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        import psutil
        
        killed_processes = []
        
        # Пробуем интерпретировать как PID
        try:
            pid = int(process_identifier)
            try:
                process = psutil.Process(pid)
                process_name = process.name()
                
                # Проверяем, что это не критический системный процесс
                critical_processes = ['explorer.exe', 'winlogon.exe', 'csrss.exe', 'smss.exe', 'system']
                if process_name.lower() in critical_processes:
                    return {
                        "error": True,
                        "message": f"❌ **Завершение критического процесса '{process_name}' запрещено**"
                    }
                
                process.terminate()
                killed_processes.append({"pid": pid, "name": process_name})
                
            except psutil.NoSuchProcess:
                return {
                    "error": True,
                    "message": f"❌ **Процесс с PID {pid} не найден**"
                }
            except psutil.AccessDenied:
                return {
                    "error": True,
                    "message": f"❌ **Нет прав для завершения процесса с PID {pid}**"
                }
                
        except ValueError:
            # Это имя процесса
            process_name = process_identifier.lower()
            
            # Проверяем критические процессы
            critical_processes = ['explorer.exe', 'winlogon.exe', 'csrss.exe', 'smss.exe', 'system']
            if any(critical in process_name for critical in critical_processes):
                return {
                    "error": True,
                    "message": f"❌ **Завершение критических системных процессов запрещено**"
                }
            
            found_processes = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if process_name in proc.info['name'].lower():
                        found_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not found_processes:
                return {
                    "error": True,
                    "message": f"❌ **Процессы с именем '{process_identifier}' не найдены**"
                }
            
            # Завершаем найденные процессы
            for proc in found_processes:
                try:
                    proc.terminate()
                    killed_processes.append({"pid": proc.pid, "name": proc.info['name']})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        
        if killed_processes:
            message = f"✅ **Завершено процессов:** {len(killed_processes)}\n\n"
            for proc in killed_processes:
                message += f"• {proc['name']} (PID: {proc['pid']})\n"
            
            return {
                "success": True,
                "message": message,
                "killed_processes": killed_processes
            }
        else:
            return {
                "error": True,
                "message": "❌ **Не удалось завершить ни одного процесса**"
            }
            
    except Exception as e:
        logger.error(f"Ошибка завершения процесса {process_identifier}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка завершения процесса:** {str(e)}"
        }
