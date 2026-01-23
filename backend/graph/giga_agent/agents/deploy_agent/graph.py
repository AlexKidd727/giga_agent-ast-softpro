"""
Deploy Agent - граф для развертывания приложений на VPS
"""
import logging
from typing import Optional, Literal, Any
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

from .config import DeployAgentState
from .nodes.setup_server import setup_server_node
from .nodes.deploy_docker import deploy_docker_node
from .nodes.setup_nginx import setup_nginx_node
from .nodes.setup_ssl import setup_ssl_node
from .nodes.manage_services import manage_services_node

logger = logging.getLogger(__name__)


# Определяем действия
ActionType = Literal[
    "setup_server",
    "deploy_docker", 
    "setup_nginx",
    "setup_ssl",
    "manage_services",
    "full_deploy"
]


def route_action(state: DeployAgentState) -> str:
    """Маршрутизация по типу действия"""
    user_request = state.get("user_request", "").lower()
    
    # Определяем действие по ключевым словам в запросе
    if "ssl" in user_request or "https" in user_request or "сертификат" in user_request:
        return "setup_ssl"
    elif "nginx" in user_request:
        return "setup_nginx"
    elif "docker" in user_request or "контейнер" in user_request:
        return "deploy_docker"
    elif "статус" in user_request or "проверить" in user_request or "логи" in user_request:
        return "manage_services"
    elif "настроить сервер" in user_request or "первичная" in user_request:
        return "setup_server"
    else:
        # По умолчанию - полное развертывание
        return "full_deploy"


async def full_deploy_node(state: DeployAgentState) -> dict:
    """
    Полное развертывание: сервер -> docker -> nginx -> ssl
    """
    logs = state.get("logs", []) or []
    logs.append("=== Начало полного развертывания ===")
    
    # 1. Настройка сервера
    logs.append("")
    logs.append("--- Шаг 1: Настройка сервера ---")
    result = await setup_server_node({**state, "logs": logs})
    
    if result.get("error"):
        return result
    
    logs = result.get("logs", logs)
    
    # 2. Развертывание Docker (если указан образ или compose)
    if state.get("docker_image") or state.get("docker_compose_path"):
        logs.append("")
        logs.append("--- Шаг 2: Развертывание Docker ---")
        result = await deploy_docker_node({**state, "logs": logs})
        
        if result.get("error"):
            return result
        
        logs = result.get("logs", logs)
        
        # Получаем порт из результата если не указан
        if not state.get("app_port") and result.get("result", {}).get("app_port"):
            state["app_port"] = result["result"]["app_port"]
    
    # 3. Настройка NGINX (если указан домен)
    if state.get("domain"):
        logs.append("")
        logs.append("--- Шаг 3: Настройка NGINX ---")
        result = await setup_nginx_node({**state, "logs": logs, "ssl_enabled": False})
        
        if result.get("error"):
            return result
        
        logs = result.get("logs", logs)
        
        # 4. Настройка SSL (если указан email)
        if state.get("ssl_email"):
            logs.append("")
            logs.append("--- Шаг 4: Настройка SSL ---")
            result = await setup_ssl_node({**state, "logs": logs})
            
            if result.get("error"):
                # SSL ошибка не критична, продолжаем
                logs.append(f"Предупреждение SSL: {result.get('error')}")
            else:
                logs = result.get("logs", logs)
    
    logs.append("")
    logs.append("=== Развертывание завершено ===")
    
    return {
        "result": {
            "status": "success",
            "message": "Полное развертывание завершено"
        },
        "logs": logs,
        "error": None
    }


# Создаем граф
def create_deploy_graph():
    """Создание графа Deploy Agent"""
    
    workflow = StateGraph(DeployAgentState)
    
    # Добавляем узлы
    workflow.add_node("setup_server", setup_server_node)
    workflow.add_node("deploy_docker", deploy_docker_node)
    workflow.add_node("setup_nginx", setup_nginx_node)
    workflow.add_node("setup_ssl", setup_ssl_node)
    workflow.add_node("manage_services", manage_services_node)
    workflow.add_node("full_deploy", full_deploy_node)
    
    # Условный переход от начала
    workflow.add_conditional_edges(
        "__start__",
        route_action,
        {
            "setup_server": "setup_server",
            "deploy_docker": "deploy_docker",
            "setup_nginx": "setup_nginx",
            "setup_ssl": "setup_ssl",
            "manage_services": "manage_services",
            "full_deploy": "full_deploy"
        }
    )
    
    # Все узлы ведут к завершению
    workflow.add_edge("setup_server", END)
    workflow.add_edge("deploy_docker", END)
    workflow.add_edge("setup_nginx", END)
    workflow.add_edge("setup_ssl", END)
    workflow.add_edge("manage_services", END)
    workflow.add_edge("full_deploy", END)
    
    return workflow.compile()


# Компилируем граф
graph = create_deploy_graph()


@tool
async def deploy_agent_tool(
    action: str,
    vps_ip: str,
    vps_login: str,
    vps_password: Optional[str] = None,
    vps_ssh_key: Optional[str] = None,
    project_name: Optional[str] = None,
    domain: Optional[str] = None,
    app_port: Optional[str] = "3000",
    docker_image: Optional[str] = None,
    docker_compose_path: Optional[str] = None,
    ssl_email: Optional[str] = None,
    include_www: Optional[bool] = False,
    nginx_config_type: Optional[str] = "proxy",
    static_root: Optional[str] = None
) -> dict:
    """
    Deploy Agent - инструмент для развертывания приложений на VPS.
    
    Поддерживаемые действия (action):
    - setup_server: Первичная настройка сервера (обновление пакетов, базовые утилиты, firewall)
    - deploy_docker: Развертывание Docker приложения (установка Docker, запуск контейнеров)
    - setup_nginx: Настройка NGINX (создание конфигурации сайта, проксирование)
    - setup_ssl: Настройка SSL сертификата (certbot, Let's Encrypt, автообновление)
    - manage_services: Управление сервисами (статус, логи, перезапуск)
    - full_deploy: Полное развертывание (сервер + docker + nginx + ssl)
    
    Args:
        action: Действие для выполнения
        vps_ip: IP адрес VPS сервера
        vps_login: Логин для SSH подключения
        vps_password: Пароль для SSH (или используйте vps_ssh_key)
        vps_ssh_key: Приватный SSH ключ (альтернатива паролю)
        project_name: Имя проекта (используется для именования контейнеров и конфигов)
        domain: Домен для настройки NGINX и SSL
        app_port: Порт приложения для проксирования (по умолчанию 3000)
        docker_image: Docker образ для запуска
        docker_compose_path: Путь к docker-compose.yml на сервере
        ssl_email: Email для регистрации SSL сертификата Let's Encrypt
        include_www: Включать ли www вариант домена в конфигурацию
        nginx_config_type: Тип конфигурации NGINX (proxy или static)
        static_root: Корневая директория для статических файлов
        
    Returns:
        dict с результатом выполнения:
        - result: Результат операции
        - logs: Список выполненных действий
        - error: Ошибка (если есть)
    """
    
    # Валидация
    if not vps_password and not vps_ssh_key:
        return {
            "error": "Необходимо указать vps_password или vps_ssh_key",
            "logs": []
        }
    
    # Формируем состояние
    state: DeployAgentState = {
        "messages": [],
        "user_request": action,
        "user_id": "deploy_agent",
        "vps_ip": vps_ip,
        "vps_login": vps_login,
        "vps_password": vps_password,
        "vps_ssh_key": vps_ssh_key,
        "project_name": project_name,
        "domain": domain,
        "app_port": app_port,
        "deployment_type": "docker",
        "docker_image": docker_image,
        "docker_compose_path": docker_compose_path,
        "dockerfile_path": None,
        "nginx_config_type": nginx_config_type,
        "static_root": static_root,
        "include_www": include_www,
        "ssl_email": ssl_email,
        "ssl_enabled": False,
        "result": None,
        "error": None,
        "logs": []
    }
    
    try:
        # Выполняем граф
        result = await graph.ainvoke(state)
        
        return {
            "result": result.get("result"),
            "logs": result.get("logs", []),
            "error": result.get("error")
        }
        
    except Exception as e:
        logger.error(f"Ошибка Deploy Agent: {e}")
        return {
            "error": str(e),
            "logs": state.get("logs", [])
        }


# Экспортируем для использования как инструмент
__all__ = ["graph", "deploy_agent_tool"]
