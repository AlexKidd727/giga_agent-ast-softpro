"""
Узел управления сервисами
"""
import logging
from typing import Dict

from ..config import DeployAgentState
from ..utils.ssh_client import SSHManager
from ..utils.nginx_manager import NginxManager
from ..utils.docker_manager import DockerManager

logger = logging.getLogger(__name__)


async def manage_services_node(state: DeployAgentState) -> Dict:
    """
    Управление сервисами на сервере:
    - Проверка статуса
    - Перезапуск сервисов
    - Просмотр логов
    - Очистка ресурсов
    """
    logs = state.get("logs", []) or []
    
    vps_ip = state.get("vps_ip")
    vps_login = state.get("vps_login")
    vps_password = state.get("vps_password")
    vps_ssh_key = state.get("vps_ssh_key")
    
    project_name = state.get("project_name")
    
    if not vps_ip or not vps_login:
        return {
            "error": "Не указаны параметры подключения к VPS",
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
            nginx = NginxManager(ssh)
            docker = DockerManager(ssh)
            
            logs.append(f"Подключение к серверу {vps_ip}")
            
            result = {
                "server_info": {},
                "nginx": {},
                "docker": {},
                "services": []
            }
            
            # Информация о сервере
            logs.append("=== Информация о сервере ===")
            
            # Uptime
            exit_code, stdout, _ = ssh.exec_command("uptime -p")
            uptime = stdout.strip() if exit_code == 0 else "N/A"
            result["server_info"]["uptime"] = uptime
            logs.append(f"Uptime: {uptime}")
            
            # Память
            exit_code, stdout, _ = ssh.exec_command("free -h | grep Mem")
            if exit_code == 0:
                mem_parts = stdout.split()
                if len(mem_parts) >= 3:
                    result["server_info"]["memory"] = {
                        "total": mem_parts[1],
                        "used": mem_parts[2],
                        "free": mem_parts[3] if len(mem_parts) > 3 else "N/A"
                    }
                    logs.append(f"Память: {mem_parts[2]} / {mem_parts[1]}")
            
            # Диск
            exit_code, stdout, _ = ssh.exec_command("df -h / | tail -1")
            if exit_code == 0:
                disk_parts = stdout.split()
                if len(disk_parts) >= 5:
                    result["server_info"]["disk"] = {
                        "total": disk_parts[1],
                        "used": disk_parts[2],
                        "free": disk_parts[3],
                        "percent": disk_parts[4]
                    }
                    logs.append(f"Диск: {disk_parts[2]} / {disk_parts[1]} ({disk_parts[4]} использовано)")
            
            # Статус NGINX
            logs.append("")
            logs.append("=== NGINX ===")
            
            if nginx.is_installed():
                status = nginx.get_status()
                result["nginx"]["installed"] = True
                result["nginx"]["status"] = status
                logs.append(f"Статус: {status}")
                
                # Список активных сайтов
                active_sites = nginx.get_active_sites()
                result["nginx"]["active_sites"] = active_sites
                logs.append(f"Активных сайтов: {len(active_sites)}")
                for site in active_sites[:5]:  # Показываем первые 5
                    logs.append(f"  - {site}")
                if len(active_sites) > 5:
                    logs.append(f"  ... и еще {len(active_sites) - 5}")
                
                # Проверка конфигурации
                valid, msg = nginx.test_config()
                result["nginx"]["config_valid"] = valid
                if not valid:
                    logs.append(f"Ошибка конфигурации: {msg}")
            else:
                result["nginx"]["installed"] = False
                logs.append("NGINX не установлен")
            
            # Статус Docker
            logs.append("")
            logs.append("=== Docker ===")
            
            if docker.is_docker_installed():
                result["docker"]["installed"] = True
                
                # Список контейнеров
                containers = docker.list_containers(all_containers=True)
                result["docker"]["containers"] = containers
                
                running = [c for c in containers if "Up" in c["status"]]
                stopped = [c for c in containers if "Up" not in c["status"]]
                
                logs.append(f"Контейнеров: {len(containers)} (запущено: {len(running)}, остановлено: {len(stopped)})")
                
                # Фильтруем по проекту если указан
                if project_name:
                    project_containers = [c for c in containers if project_name.lower() in c["name"].lower()]
                    if project_containers:
                        logs.append(f"Контейнеры проекта {project_name}:")
                        for c in project_containers:
                            logs.append(f"  - {c['name']}: {c['status']}")
                else:
                    # Показываем все контейнеры
                    for c in containers[:10]:
                        logs.append(f"  - {c['name']}: {c['status']}")
                    if len(containers) > 10:
                        logs.append(f"  ... и еще {len(containers) - 10}")
            else:
                result["docker"]["installed"] = False
                logs.append("Docker не установлен")
            
            # Статус основных сервисов
            logs.append("")
            logs.append("=== Системные сервисы ===")
            
            services_to_check = ["nginx", "docker", "ssh", "cron"]
            for service in services_to_check:
                status = ssh.get_service_status(service)
                result["services"].append({
                    "name": service,
                    "status": status
                })
                logs.append(f"{service}: {status}")
        
        return {
            "result": result,
            "logs": logs,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Ошибка управления сервисами: {e}")
        logs.append(f"Ошибка: {str(e)}")
        return {
            "error": str(e),
            "logs": logs
        }
