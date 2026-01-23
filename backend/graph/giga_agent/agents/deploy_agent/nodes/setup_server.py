"""
Узел первичной настройки сервера
"""
import logging
from typing import Dict, List

from ..config import DeployAgentState
from ..utils.ssh_client import SSHManager

logger = logging.getLogger(__name__)


async def setup_server_node(state: DeployAgentState) -> Dict:
    """
    Первичная настройка сервера:
    - Обновление пакетов
    - Установка базовых утилит
    - Настройка firewall
    """
    logs = state.get("logs", []) or []
    
    vps_ip = state.get("vps_ip")
    vps_login = state.get("vps_login")
    vps_password = state.get("vps_password")
    vps_ssh_key = state.get("vps_ssh_key")
    
    if not vps_ip or not vps_login:
        return {
            "error": "Не указаны параметры подключения к VPS (ip, login)",
            "logs": logs
        }
    
    if not vps_password and not vps_ssh_key:
        return {
            "error": "Не указан пароль или SSH ключ для подключения",
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
            logs.append(f"Подключение к серверу {vps_ip} успешно")
            
            # Определяем дистрибутив
            distro = ssh.detect_distro()
            logs.append(f"Дистрибутив: {distro}")
            
            # Обновляем пакеты
            logs.append("Обновление списка пакетов...")
            pm = ssh.get_package_manager()
            
            if pm == "apt-get":
                exit_code, _, stderr = ssh.exec_sudo("apt-get update -qq")
            elif pm == "yum":
                exit_code, _, stderr = ssh.exec_sudo("yum check-update || true")
            elif pm == "dnf":
                exit_code, _, stderr = ssh.exec_sudo("dnf check-update || true")
            
            logs.append("Список пакетов обновлен")
            
            # Устанавливаем базовые утилиты
            base_packages = ["curl", "wget", "git", "zip", "unzip", "htop"]
            logs.append("Установка базовых утилит...")
            
            for pkg in base_packages:
                if not ssh.is_package_installed(pkg):
                    success, msg = ssh.install_package(pkg)
                    if success:
                        logs.append(f"  - {pkg} установлен")
                    else:
                        logs.append(f"  - {pkg}: ошибка установки")
                else:
                    logs.append(f"  - {pkg} уже установлен")
            
            # Проверяем firewall
            exit_code, stdout, _ = ssh.exec_command("which ufw 2>/dev/null || which firewall-cmd 2>/dev/null || echo ''")
            firewall_tool = stdout.strip()
            
            if "ufw" in firewall_tool:
                logs.append("Настройка UFW firewall...")
                # Разрешаем SSH, HTTP, HTTPS
                ssh.exec_sudo("ufw allow ssh")
                ssh.exec_sudo("ufw allow http")
                ssh.exec_sudo("ufw allow https")
                logs.append("Разрешены порты: SSH, HTTP, HTTPS")
            elif "firewall-cmd" in firewall_tool:
                logs.append("Настройка firewalld...")
                ssh.exec_sudo("firewall-cmd --permanent --add-service=ssh")
                ssh.exec_sudo("firewall-cmd --permanent --add-service=http")
                ssh.exec_sudo("firewall-cmd --permanent --add-service=https")
                ssh.exec_sudo("firewall-cmd --reload")
                logs.append("Разрешены порты: SSH, HTTP, HTTPS")
            else:
                logs.append("Firewall не обнаружен (ufw/firewalld)")
            
            # Проверяем свободное место
            exit_code, stdout, _ = ssh.exec_command("df -h / | tail -1 | awk '{print $4}'")
            free_space = stdout.strip()
            logs.append(f"Свободное место на диске: {free_space}")
            
            # Проверяем память
            exit_code, stdout, _ = ssh.exec_command("free -h | grep Mem | awk '{print $2}'")
            total_mem = stdout.strip()
            logs.append(f"Всего памяти: {total_mem}")
        
        return {
            "result": {
                "status": "success",
                "message": "Сервер настроен",
                "distro": distro,
                "free_space": free_space,
                "total_memory": total_mem
            },
            "logs": logs,
            "error": None
        }
        
    except Exception as e:
        logger.error(f"Ошибка настройки сервера: {e}")
        logs.append(f"Ошибка: {str(e)}")
        return {
            "error": str(e),
            "logs": logs
        }
