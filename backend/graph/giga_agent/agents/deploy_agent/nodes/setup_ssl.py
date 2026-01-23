"""
Узел настройки SSL сертификата
"""
import logging
from typing import Dict

from ..config import DeployAgentState
from ..utils.ssh_client import SSHManager
from ..utils.nginx_manager import NginxManager
from ..utils.ssl_manager import SSLManager

logger = logging.getLogger(__name__)


async def setup_ssl_node(state: DeployAgentState) -> Dict:
    """
    Настройка SSL сертификата:
    - Установка certbot
    - Получение сертификата Let's Encrypt
    - Обновление конфигурации NGINX для HTTPS
    - Настройка автоматического обновления
    """
    logs = state.get("logs", []) or []
    
    vps_ip = state.get("vps_ip")
    vps_login = state.get("vps_login")
    vps_password = state.get("vps_password")
    vps_ssh_key = state.get("vps_ssh_key")
    
    domain = state.get("domain")
    ssl_email = state.get("ssl_email")
    app_port = state.get("app_port", "3000")
    project_name = state.get("project_name")
    include_www = state.get("include_www", False)
    nginx_config_type = state.get("nginx_config_type", "proxy")
    static_root = state.get("static_root")
    
    if not vps_ip or not vps_login:
        return {
            "error": "Не указаны параметры подключения к VPS",
            "logs": logs
        }
    
    if not domain:
        return {
            "error": "Не указан домен для SSL сертификата",
            "logs": logs
        }
    
    if not ssl_email:
        return {
            "error": "Не указан email для Let's Encrypt (ssl_email)",
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
            ssl = SSLManager(ssh, nginx)
            
            logs.append(f"Подключение к серверу {vps_ip}")
            
            # Проверяем, установлен ли NGINX
            if not nginx.is_installed():
                logs.append("NGINX не установлен. Сначала выполните настройку NGINX.")
                return {
                    "error": "NGINX не установлен",
                    "logs": logs
                }
            
            # Проверяем, есть ли конфиг для домена
            if not nginx.site_config_exists(domain):
                logs.append(f"Конфигурация NGINX для {domain} не найдена")
                logs.append("Создаем HTTP конфигурацию для получения сертификата...")
                
                success, msg, details = nginx.create_site_config(
                    domain=domain,
                    upstream_port=app_port,
                    include_www=include_www,
                    enable_ssl=False,
                    config_type=nginx_config_type,
                    static_root=static_root,
                    project_id=project_name
                )
                logs.extend(details)
                
                if not success:
                    return {"error": f"Ошибка создания NGINX конфига: {msg}", "logs": logs}
            
            # Проверяем, есть ли уже сертификат
            domains = NginxManager.expand_www(domain, include_www)
            primary_domain = domains[0]
            
            if ssl.certificate_exists(primary_domain):
                logs.append(f"Сертификат для {primary_domain} уже существует")
                
                # Получаем информацию о сертификате
                cert_info = ssl.get_certificate_info(primary_domain)
                if cert_info:
                    logs.append(f"  - Действителен до: {cert_info.get('not_after', 'N/A')}")
                
                # Включаем HTTPS в NGINX если еще не включен
                logs.append("Проверяем конфигурацию NGINX...")
            else:
                # Получаем новый сертификат
                logs.append(f"Получение SSL сертификата для {domain}...")
                logs.append(f"  - Email: {ssl_email}")
                logs.append(f"  - Домены: {', '.join(domains)}")
                
                success, msg, details = ssl.obtain_certificate(
                    domain=domain,
                    email=ssl_email,
                    include_www=include_www
                )
                logs.extend(details)
                
                if not success:
                    return {"error": f"Ошибка получения сертификата: {msg}", "logs": logs}
            
            # Включаем HTTPS в NGINX
            logs.append("Обновление конфигурации NGINX для HTTPS...")
            
            success, msg, details = ssl.enable_https_for_site(
                domain=domain,
                upstream_port=app_port,
                include_www=include_www,
                config_type=nginx_config_type,
                static_root=static_root,
                project_id=project_name
            )
            logs.extend(details)
            
            if not success:
                return {"error": f"Ошибка включения HTTPS: {msg}", "logs": logs}
            
            # Настраиваем автообновление
            logs.append("Настройка автоматического обновления сертификата...")
            
            success, msg, details = ssl.setup_auto_renewal(domain)
            logs.extend(details)
            
            if not success:
                logs.append(f"Предупреждение: {msg}")
            
            # Итоговая информация
            logs.append("")
            logs.append("=== SSL настройка завершена ===")
            logs.append(f"Сайт доступен по адресу: https://{domain}")
            if include_www:
                logs.append(f"А также: https://www.{domain}")
            
            cert_info = ssl.get_certificate_info(primary_domain)
        
        return {
            "result": {
                "status": "success",
                "message": f"SSL сертификат настроен для {domain}",
                "domains": domains,
                "certificate_info": cert_info,
                "https_url": f"https://{domain}"
            },
            "ssl_enabled": True,
            "logs": logs,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Ошибка настройки SSL: {e}")
        logs.append(f"Ошибка: {str(e)}")
        return {
            "error": str(e),
            "logs": logs
        }
