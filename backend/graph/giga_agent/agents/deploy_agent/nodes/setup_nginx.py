"""
Узел настройки NGINX
"""
import logging
from typing import Dict

from ..config import DeployAgentState
from ..utils.ssh_client import SSHManager
from ..utils.nginx_manager import NginxManager

logger = logging.getLogger(__name__)


async def setup_nginx_node(state: DeployAgentState) -> Dict:
    """
    Настройка NGINX:
    - Установка NGINX
    - Создание конфигурации сайта
    - Проверка и применение конфигурации
    """
    logs = state.get("logs", []) or []
    
    vps_ip = state.get("vps_ip")
    vps_login = state.get("vps_login")
    vps_password = state.get("vps_password")
    vps_ssh_key = state.get("vps_ssh_key")
    
    domain = state.get("domain")
    app_port = state.get("app_port", "3000")
    project_name = state.get("project_name")
    include_www = state.get("include_www", False)
    nginx_config_type = state.get("nginx_config_type", "proxy")
    static_root = state.get("static_root")
    ssl_enabled = state.get("ssl_enabled", False)
    
    if not vps_ip or not vps_login:
        return {
            "error": "Не указаны параметры подключения к VPS",
            "logs": logs
        }
    
    if not domain:
        return {
            "error": "Не указан домен для настройки NGINX",
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
            logs.append(f"Подключение к серверу {vps_ip}")
            
            # Установка NGINX
            if not nginx.is_installed():
                logs.append("Установка NGINX...")
                success, msg = nginx.install()
                if not success:
                    return {"error": f"Ошибка установки NGINX: {msg}", "logs": logs}
                logs.append("NGINX установлен и запущен")
            else:
                logs.append("NGINX уже установлен")
                
                # Проверяем статус
                status = nginx.get_status()
                logs.append(f"Статус NGINX: {status}")
                
                if status != "active":
                    ssh.start_service("nginx")
                    logs.append("NGINX запущен")
            
            # Проверяем конфликты домена
            domains = NginxManager.expand_www(domain, include_www)
            conflicts = nginx.detect_domain_conflicts(domains)
            
            if conflicts:
                logs.append(f"Обнаружены конфликты для домена {domain}:")
                for conflict in conflicts:
                    logs.append(f"  - {conflict}")
                logs.append("Конфигурация не будет создана, чтобы не сломать другие сайты")
                return {
                    "error": f"Домен {domain} уже используется другим конфигом",
                    "result": {"conflicts": conflicts},
                    "logs": logs
                }
            
            # Создаем конфигурацию сайта
            logs.append(f"Создание конфигурации NGINX для {domain}...")
            logs.append(f"  - Тип: {nginx_config_type}")
            logs.append(f"  - Порт приложения: {app_port}")
            logs.append(f"  - Включать www: {include_www}")
            logs.append(f"  - SSL: {ssl_enabled}")
            
            success, msg, details = nginx.create_site_config(
                domain=domain,
                upstream_port=app_port,
                include_www=include_www,
                enable_ssl=ssl_enabled,
                config_type=nginx_config_type,
                static_root=static_root,
                project_id=project_name,
                check_conflicts=False  # Уже проверили выше
            )
            
            logs.extend(details)
            
            if not success:
                return {"error": f"Ошибка создания конфигурации: {msg}", "logs": logs}
            
            # Получаем итоговую информацию
            config_path = nginx.get_site_config_path(domain)
            enabled_path = nginx.get_site_enabled_path(domain)
            
            logs.append(f"Конфигурация NGINX создана и применена")
            logs.append(f"  - Конфиг: {config_path}")
            logs.append(f"  - Активирован: {enabled_path}")
            
            # Проверяем доступность сайта
            if not ssl_enabled:
                logs.append(f"Сайт доступен по адресу: http://{domain}")
            else:
                logs.append(f"Сайт доступен по адресу: https://{domain}")
        
        return {
            "result": {
                "status": "success",
                "message": f"NGINX настроен для {domain}",
                "config_path": config_path,
                "enabled_path": enabled_path,
                "domains": domains,
                "ssl_enabled": ssl_enabled
            },
            "logs": logs,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Ошибка настройки NGINX: {e}")
        logs.append(f"Ошибка: {str(e)}")
        return {
            "error": str(e),
            "logs": logs
        }
