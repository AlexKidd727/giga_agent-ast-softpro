"""
Узлы для работы с окнами Windows в PC Management Agent
"""

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from ..utils.windows_utils import (
    get_window_list, find_window_by_title, close_window_by_hwnd,
    minimize_window_by_hwnd, maximize_window_by_hwnd, restore_window_by_hwnd,
    get_window_info_by_hwnd, is_program_running
)
from ..config import IS_WINDOWS

logger = logging.getLogger(__name__)

@tool
async def open_windows(user_id: str = "default_user", state: Annotated[dict, InjectedState] = None):
    """
    Получение списка открытых окон
    
    Args:
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        windows = get_window_list()
        
        # Проверяем на ошибки
        if windows and "error" in windows[0]:
            return {
                "error": True,
                "message": f"❌ **{windows[0]['error']}**"
            }
        
        if not windows:
            return {
                "success": True,
                "message": "🪟 **Открытые окна не найдены**",
                "windows_count": 0
            }
        
        # Фильтруем и сортируем окна
        visible_windows = [w for w in windows if w.get('title') and len(w['title'].strip()) > 0]
        visible_windows.sort(key=lambda x: x.get('title', '').lower())
        
        message = f"🪟 **Открытые окна ({len(visible_windows)}):**\n\n"
        
        for i, window in enumerate(visible_windows[:20], 1):  # Ограничиваем вывод
            title = window['title']
            if len(title) > 60:
                title = title[:57] + "..."
            
            process_name = window.get('process_name', 'Unknown')
            hwnd = window.get('hwnd', 0)
            
            # Статус окна
            status_icons = []
            if window.get('is_minimized'):
                status_icons.append("📉")
            elif window.get('is_maximized'):
                status_icons.append("📈")
            else:
                status_icons.append("🪟")
            
            status = " ".join(status_icons)
            
            message += f"{status} **{title}**\n"
            message += f"  📱 {process_name} | 🆔 {hwnd}\n"
            
            # Размер окна
            rect = window.get('rect', {})
            if rect:
                width = rect.get('width', 0)
                height = rect.get('height', 0)
                message += f"  📐 {width}×{height}\n"
            
            message += "\n"
        
        if len(visible_windows) > 20:
            message += f"... и еще {len(visible_windows) - 20} окон"
        
        message += "\n💡 **Используйте HWND для управления конкретным окном**"
        
        return {
            "success": True,
            "message": message,
            "windows_count": len(visible_windows),
            "windows": visible_windows[:10]  # Возвращаем данные для программной обработки
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения списка окон: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения списка окон:** {str(e)}"
        }

@tool
async def close_window(
    window_identifier: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Закрытие окна по HWND или заголовку
    
    Args:
        window_identifier: HWND окна или часть заголовка
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        # Пробуем интерпретировать как HWND
        try:
            hwnd = int(window_identifier)
            result = close_window_by_hwnd(hwnd)
            
            if result.get('success'):
                return {
                    "success": True,
                    "message": f"✅ **{result['message']}**",
                    "hwnd": hwnd
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **{result['error']}**"
                }
                
        except ValueError:
            # Это заголовок окна
            windows = find_window_by_title(window_identifier)
            
            if not windows or "error" in windows[0]:
                return {
                    "error": True,
                    "message": f"❌ **Окна с заголовком '{window_identifier}' не найдены**"
                }
            
            closed_windows = []
            for window in windows[:5]:  # Ограничиваем количество закрываемых окон
                hwnd = window.get('hwnd')
                if hwnd:
                    result = close_window_by_hwnd(hwnd)
                    if result.get('success'):
                        closed_windows.append(window['title'])
            
            if closed_windows:
                message = f"✅ **Закрыто окон:** {len(closed_windows)}\n\n"
                for title in closed_windows:
                    message += f"• {title}\n"
                
                return {
                    "success": True,
                    "message": message,
                    "closed_count": len(closed_windows)
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **Не удалось закрыть окна с заголовком '{window_identifier}'**"
                }
            
    except Exception as e:
        logger.error(f"Ошибка закрытия окна {window_identifier}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка закрытия окна:** {str(e)}"
        }

@tool
async def get_window_info(
    hwnd: int,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Получение подробной информации об окне
    
    Args:
        hwnd: HWND окна
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        window_info = get_window_info_by_hwnd(hwnd)
        
        if "error" in window_info:
            return {
                "error": True,
                "message": f"❌ **{window_info['error']}**"
            }
        
        # Форматируем информацию
        title = window_info.get('title', 'Без заголовка')
        rect = window_info.get('rect', {})
        process = window_info.get('process', {})
        
        message = f"""🪟 **Информация об окне**

📛 **Заголовок:** {title}
🆔 **HWND:** {hwnd}
🔢 **PID:** {window_info.get('pid', 'N/A')}

📱 **Процесс:**
• Имя: {process.get('name', 'Unknown')}
• CPU: {process.get('cpu_percent', 0):.1f}%
• RAM: {process.get('memory_percent', 0):.1f}%
• Статус: {process.get('status', 'Unknown')}

📐 **Размеры и позиция:**
• X: {rect.get('left', 0)}, Y: {rect.get('top', 0)}
• Ширина: {rect.get('width', 0)}
• Высота: {rect.get('height', 0)}

🎛️ **Состояние:**
• Видимо: {'✅' if window_info.get('is_visible') else '❌'}
• Свернуто: {'✅' if window_info.get('is_minimized') else '❌'}
• Развернуто: {'✅' if window_info.get('is_maximized') else '❌'}
• Активно: {'✅' if window_info.get('is_enabled') else '❌'}"""
        
        return {
            "success": True,
            "message": message,
            "window_info": window_info
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения информации об окне {hwnd}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка получения информации об окне:** {str(e)}"
        }

@tool
async def minimize_window(
    window_identifier: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Сворачивание окна по HWND или заголовку
    
    Args:
        window_identifier: HWND окна или часть заголовка
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        # Пробуем интерпретировать как HWND
        try:
            hwnd = int(window_identifier)
            result = minimize_window_by_hwnd(hwnd)
            
            if result.get('success'):
                return {
                    "success": True,
                    "message": f"✅ **{result['message']}**",
                    "hwnd": hwnd
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **{result['error']}**"
                }
                
        except ValueError:
            # Это заголовок окна
            windows = find_window_by_title(window_identifier)
            
            if not windows or "error" in windows[0]:
                return {
                    "error": True,
                    "message": f"❌ **Окна с заголовком '{window_identifier}' не найдены**"
                }
            
            minimized_windows = []
            for window in windows[:3]:  # Ограничиваем количество
                hwnd = window.get('hwnd')
                if hwnd:
                    result = minimize_window_by_hwnd(hwnd)
                    if result.get('success'):
                        minimized_windows.append(window['title'])
            
            if minimized_windows:
                message = f"✅ **Свернуто окон:** {len(minimized_windows)}\n\n"
                for title in minimized_windows:
                    message += f"• {title}\n"
                
                return {
                    "success": True,
                    "message": message,
                    "minimized_count": len(minimized_windows)
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **Не удалось свернуть окна с заголовком '{window_identifier}'**"
                }
            
    except Exception as e:
        logger.error(f"Ошибка сворачивания окна {window_identifier}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка сворачивания окна:** {str(e)}"
        }

@tool
async def maximize_window(
    window_identifier: str,
    user_id: str = "default_user",
    state: Annotated[dict, InjectedState] = None
):
    """
    Разворачивание окна по HWND или заголовку
    
    Args:
        window_identifier: HWND окна или часть заголовка
        user_id: Идентификатор пользователя (необязательно)
    """
    try:
        if not IS_WINDOWS:
            return {
                "error": True,
                "message": "❌ **Функция доступна только для Windows**"
            }
        
        # Пробуем интерпретировать как HWND
        try:
            hwnd = int(window_identifier)
            result = maximize_window_by_hwnd(hwnd)
            
            if result.get('success'):
                return {
                    "success": True,
                    "message": f"✅ **{result['message']}**",
                    "hwnd": hwnd
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **{result['error']}**"
                }
                
        except ValueError:
            # Это заголовок окна
            windows = find_window_by_title(window_identifier)
            
            if not windows or "error" in windows[0]:
                return {
                    "error": True,
                    "message": f"❌ **Окна с заголовком '{window_identifier}' не найдены**"
                }
            
            maximized_windows = []
            for window in windows[:3]:  # Ограничиваем количество
                hwnd = window.get('hwnd')
                if hwnd:
                    result = maximize_window_by_hwnd(hwnd)
                    if result.get('success'):
                        maximized_windows.append(window['title'])
            
            if maximized_windows:
                message = f"✅ **Развернуто окон:** {len(maximized_windows)}\n\n"
                for title in maximized_windows:
                    message += f"• {title}\n"
                
                return {
                    "success": True,
                    "message": message,
                    "maximized_count": len(maximized_windows)
                }
            else:
                return {
                    "error": True,
                    "message": f"❌ **Не удалось развернуть окна с заголовком '{window_identifier}'**"
                }
            
    except Exception as e:
        logger.error(f"Ошибка разворачивания окна {window_identifier}: {e}")
        return {
            "error": True,
            "message": f"❌ **Ошибка разворачивания окна:** {str(e)}"
        }
