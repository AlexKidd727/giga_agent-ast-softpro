"""
Узел развертывания Docker проекта
"""
import logging
from typing import Dict

from ..config import DeployAgentState, DEFAULT_DEPLOYMENT_PATH
from ..utils.ssh_client import SSHManager
from ..utils.docker_manager import DockerManager

logger = logging.getLogger(__name__)


async def deploy_docker_node(state: DeployAgentState) -> Dict:
    """
    Развертывание Docker проекта:
    - Установка Docker и Docker Compose
    - Загрузка/сборка образа
    - Запуск контейнеров
    """
    logs = state.get("logs", []) or []
    
    vps_ip = state.get("vps_ip")
    vps_login = state.get("vps_login")
    vps_password = state.get("vps_password")
    vps_ssh_key = state.get("vps_ssh_key")
    
    project_name = state.get("project_name")
    docker_image = state.get("docker_image")
    docker_compose_path = state.get("docker_compose_path")
    app_port = state.get("app_port", "3000")
    
    if not vps_ip or not vps_login:
        return {
            "error": "Не указаны параметры подключения к VPS",
            "logs": logs
        }
    
    if not project_name:
        return {
            "error": "Не указано имя проекта",
            "logs": logs
        }
    
    try:
        ssh = SSHManager(
            hostname=vps_ip,
            username=vps_login,
            password=vps_password,
            ssh_key=vps_ssh_key
        )
        
        with ssh:
            docker = DockerManager(ssh)
            logs.append(f"Подключение к серверу {vps_ip}")
            
            # Установка Docker
            if not docker.is_docker_installed():
                logs.append("Установка Docker...")
                success, msg = docker.install_docker()
                if not success:
                    return {"error": f"Ошибка установки Docker: {msg}", "logs": logs}
                logs.append("Docker установлен")
            else:
                logs.append("Docker уже установлен")
            
            # Установка Docker Compose
            if not docker.is_docker_compose_installed():
                logs.append("Установка Docker Compose...")
                success, msg = docker.install_docker_compose()
                if not success:
                    logs.append(f"Предупреждение: {msg}")
                else:
                    logs.append("Docker Compose установлен")
            else:
                logs.append("Docker Compose уже установлен")
            
            # Определяем путь к проекту
            project_path = f"{DEFAULT_DEPLOYMENT_PATH}/{project_name}"
            
            # Создаем директорию проекта если нужно
            if not ssh.dir_exists(project_path):
                ssh.mkdir(project_path, sudo=True)
                ssh.exec_sudo(f"chown {vps_login}:{vps_login} {project_path}")
                logs.append(f"Создана директория: {project_path}")
            
            # Вариант 1: Запуск готового образа
            if docker_image and not docker_compose_path:
                logs.append(f"Загрузка образа {docker_image}...")
                success, msg = docker.pull_image(docker_image)
                if not success:
                    logs.append(f"Предупреждение: {msg}")
                
                # Останавливаем старый контейнер если есть
                if docker.container_exists(project_name):
                    logs.append(f"Остановка старого контейнера {project_name}...")
                    docker.stop_container(project_name)
                    docker.remove_container(project_name, force=True)
                
                # Запускаем новый контейнер
                logs.append(f"Запуск контейнера {project_name}...")
                success, msg = docker.run_container(
                    image=docker_image,
                    name=project_name,
                    ports={app_port: app_port},
                    restart_policy="unless-stopped"
                )
                
                if not success:
                    return {"error": f"Ошибка запуска контейнера: {msg}", "logs": logs}
                
                logs.append(f"Контейнер {project_name} запущен на порту {app_port}")
            
            # Вариант 2: Запуск через docker-compose
            elif docker_compose_path or ssh.file_exists(f"{project_path}/docker-compose.yml"):
                compose_file = docker_compose_path or f"{project_path}/docker-compose.yml"
                
                logs.append(f"Развертывание через docker-compose: {compose_file}")
                
                success, msg, details = docker.deploy_project(
                    project_name=project_name,
                    project_path=project_path if not docker_compose_path else "/".join(docker_compose_path.split("/")[:-1]),
                    compose_file=compose_file.split("/")[-1] if "/" in compose_file else compose_file,
                    build=True
                )
                
                logs.extend(details)
                
                if not success:
                    return {"error": f"Ошибка развертывания: {msg}", "logs": logs}
            
            else:
                return {
                    "error": "Не указан docker_image или docker_compose_path",
                    "logs": logs
                }
            
            # Получаем информацию о запущенных контейнерах
            containers = docker.list_containers()
            project_containers = [c for c in containers if project_name.lower() in c["name"].lower()]
            
            container_info = []
            for c in project_containers:
                port = docker.get_container_port(c["id"])
                container_info.append({
                    "name": c["name"],
                    "status": c["status"],
                    "port": port
                })
            
            logs.append(f"Развертывание завершено. Контейнеров: {len(project_containers)}")
        
        return {
            "result": {
                "status": "success",
                "message": f"Docker проект {project_name} развернут",
                "containers": container_info,
                "app_port": app_port
            },
            "logs": logs,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Ошибка развертывания Docker: {e}")
        logs.append(f"Ошибка: {str(e)}")
        return {
            "error": str(e),
            "logs": logs
        }
