"""
SSH клиент для работы с VPS
"""
import paramiko
import logging
import socket
from typing import Optional, Tuple
from contextlib import contextmanager

from ..config import (
    SSH_CONNECT_TIMEOUT, 
    SSH_COMMAND_TIMEOUT,
    PACKAGE_MANAGERS,
    REQUIRED_PACKAGES
)

logger = logging.getLogger(__name__)


class SSHManager:
    """Менеджер SSH подключений к VPS"""
    
    def __init__(
        self,
        hostname: str,
        username: str,
        password: Optional[str] = None,
        ssh_key: Optional[str] = None,
        port: int = 22
    ):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.ssh_key = ssh_key
        self.port = port
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self._distro: Optional[str] = None
        self._package_manager: Optional[str] = None
    
    def connect(self) -> bool:
        """Подключение к серверу"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                "hostname": self.hostname,
                "username": self.username,
                "port": self.port,
                "timeout": SSH_CONNECT_TIMEOUT
            }
            
            if self.ssh_key:
                # Подключение по SSH ключу
                from io import StringIO
                key = paramiko.RSAKey.from_private_key(StringIO(self.ssh_key))
                connect_kwargs["pkey"] = key
            elif self.password:
                connect_kwargs["password"] = self.password
            else:
                raise ValueError("Необходимо указать пароль или SSH ключ")
            
            self.client.connect(**connect_kwargs)
            logger.info(f"Успешное подключение к {self.hostname}")
            return True
            
        except paramiko.AuthenticationException as e:
            logger.error(f"Ошибка аутентификации: {e}")
            raise
        except paramiko.SSHException as e:
            logger.error(f"SSH ошибка: {e}")
            raise
        except socket.timeout:
            logger.error(f"Таймаут подключения к {self.hostname}")
            raise
        except Exception as e:
            logger.error(f"Ошибка подключения: {e}")
            raise
    
    def disconnect(self):
        """Отключение от сервера"""
        if self.sftp:
            try:
                self.sftp.close()
            except:
                pass
            self.sftp = None
        
        if self.client:
            try:
                self.client.close()
            except:
                pass
            self.client = None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
    
    def exec_command(
        self,
        command: str,
        timeout: int = SSH_COMMAND_TIMEOUT,
        get_pty: bool = False
    ) -> Tuple[int, str, str]:
        """
        Выполнение команды на сервере
        
        Returns:
            Tuple[exit_code, stdout, stderr]
        """
        if not self.client:
            raise RuntimeError("SSH клиент не подключен")
        
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command, 
                timeout=timeout,
                get_pty=get_pty
            )
            
            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode("utf-8", errors="replace")
            stderr_text = stderr.read().decode("utf-8", errors="replace")
            
            logger.debug(f"Command: {command[:100]}... Exit: {exit_code}")
            
            return exit_code, stdout_text, stderr_text
            
        except socket.timeout:
            logger.error(f"Таймаут выполнения команды: {command[:100]}...")
            raise
    
    def exec_sudo(
        self,
        command: str,
        timeout: int = SSH_COMMAND_TIMEOUT
    ) -> Tuple[int, str, str]:
        """Выполнение команды с sudo"""
        # Проверяем, начинается ли команда с sudo
        if not command.strip().startswith("sudo"):
            command = f"sudo {command}"
        return self.exec_command(command, timeout)
    
    def get_sftp(self) -> paramiko.SFTPClient:
        """Получение SFTP клиента"""
        if not self.client:
            raise RuntimeError("SSH клиент не подключен")
        
        if not self.sftp:
            self.sftp = self.client.open_sftp()
        
        return self.sftp
    
    def upload_file(self, local_path: str, remote_path: str):
        """Загрузка файла на сервер"""
        sftp = self.get_sftp()
        sftp.put(local_path, remote_path)
        logger.info(f"Файл загружен: {local_path} -> {remote_path}")
    
    def download_file(self, remote_path: str, local_path: str):
        """Скачивание файла с сервера"""
        sftp = self.get_sftp()
        sftp.get(remote_path, local_path)
        logger.info(f"Файл скачан: {remote_path} -> {local_path}")
    
    def write_file(self, remote_path: str, content: str, sudo: bool = False):
        """Запись содержимого в файл на сервере"""
        import time
        temp_path = f"/tmp/deploy_agent_{int(time.time())}.tmp"
        
        # Записываем во временный файл
        exit_code, _, stderr = self.exec_command(f"cat > {temp_path}")
        if exit_code != 0:
            # Альтернативный способ через echo
            # Экранируем специальные символы
            escaped_content = content.replace("'", "'\\''")
            exit_code, _, stderr = self.exec_command(f"echo '{escaped_content}' > {temp_path}")
        
        # Используем stdin для записи
        stdin, stdout, stderr_ch = self.client.exec_command(f"cat > {temp_path}")
        stdin.write(content)
        stdin.close()
        stdout.channel.recv_exit_status()
        
        # Перемещаем на место
        if sudo:
            self.exec_sudo(f"mv {temp_path} {remote_path}")
            self.exec_sudo(f"chmod 644 {remote_path}")
        else:
            self.exec_command(f"mv {temp_path} {remote_path}")
        
        logger.info(f"Файл записан: {remote_path}")
    
    def read_file(self, remote_path: str, sudo: bool = False) -> Optional[str]:
        """Чтение содержимого файла с сервера"""
        cmd = f"sudo cat {remote_path}" if sudo else f"cat {remote_path}"
        exit_code, stdout, stderr = self.exec_command(cmd)
        
        if exit_code != 0:
            logger.warning(f"Не удалось прочитать файл {remote_path}: {stderr}")
            return None
        
        return stdout
    
    def file_exists(self, remote_path: str) -> bool:
        """Проверка существования файла"""
        exit_code, stdout, _ = self.exec_command(
            f"test -f {remote_path} && echo 'exists' || echo 'not_exists'"
        )
        return stdout.strip() == "exists"
    
    def dir_exists(self, remote_path: str) -> bool:
        """Проверка существования директории"""
        exit_code, stdout, _ = self.exec_command(
            f"test -d {remote_path} && echo 'exists' || echo 'not_exists'"
        )
        return stdout.strip() == "exists"
    
    def mkdir(self, remote_path: str, sudo: bool = False):
        """Создание директории"""
        cmd = f"mkdir -p {remote_path}"
        if sudo:
            self.exec_sudo(cmd)
        else:
            self.exec_command(cmd)
    
    def detect_distro(self) -> str:
        """Определение дистрибутива Linux"""
        if self._distro:
            return self._distro
        
        # Пробуем /etc/os-release
        exit_code, stdout, _ = self.exec_command("cat /etc/os-release 2>/dev/null")
        if exit_code == 0:
            for line in stdout.split("\n"):
                if line.startswith("ID="):
                    self._distro = line.split("=")[1].strip().strip('"').lower()
                    break
        
        # Fallback на lsb_release
        if not self._distro:
            exit_code, stdout, _ = self.exec_command("lsb_release -is 2>/dev/null")
            if exit_code == 0:
                self._distro = stdout.strip().lower()
        
        # Default to ubuntu
        if not self._distro:
            self._distro = "ubuntu"
        
        logger.info(f"Определен дистрибутив: {self._distro}")
        return self._distro
    
    def get_package_manager(self) -> str:
        """Получение менеджера пакетов для текущего дистрибутива"""
        if self._package_manager:
            return self._package_manager
        
        distro = self.detect_distro()
        self._package_manager = PACKAGE_MANAGERS.get(distro, "apt-get")
        return self._package_manager
    
    def install_package(self, package_name: str) -> Tuple[bool, str]:
        """Установка пакета"""
        pm = self.get_package_manager()
        
        # Получаем имя пакета для данного менеджера
        if package_name in REQUIRED_PACKAGES:
            pkg = REQUIRED_PACKAGES[package_name].get(pm, package_name)
        else:
            pkg = package_name
        
        # Обновляем индекс пакетов
        if pm == "apt-get":
            self.exec_sudo("apt-get update -qq")
            install_cmd = f"apt-get install -y {pkg}"
        elif pm == "yum":
            install_cmd = f"yum install -y {pkg}"
        elif pm == "dnf":
            install_cmd = f"dnf install -y {pkg}"
        else:
            install_cmd = f"apt-get install -y {pkg}"
        
        exit_code, stdout, stderr = self.exec_sudo(install_cmd)
        
        if exit_code == 0:
            logger.info(f"Пакет установлен: {package_name}")
            return True, f"Пакет {package_name} установлен"
        else:
            logger.error(f"Ошибка установки пакета {package_name}: {stderr}")
            return False, stderr
    
    def is_package_installed(self, binary_name: str) -> bool:
        """Проверка, установлен ли пакет (по наличию бинарника)"""
        exit_code, stdout, _ = self.exec_command(f"which {binary_name}")
        return exit_code == 0 and stdout.strip() != ""
    
    def get_service_status(self, service_name: str) -> str:
        """Получение статуса systemd сервиса"""
        exit_code, stdout, _ = self.exec_command(f"systemctl is-active {service_name}")
        return stdout.strip()
    
    def start_service(self, service_name: str) -> bool:
        """Запуск сервиса"""
        exit_code, _, stderr = self.exec_sudo(f"systemctl start {service_name}")
        return exit_code == 0
    
    def stop_service(self, service_name: str) -> bool:
        """Остановка сервиса"""
        exit_code, _, stderr = self.exec_sudo(f"systemctl stop {service_name}")
        return exit_code == 0
    
    def restart_service(self, service_name: str) -> bool:
        """Перезапуск сервиса"""
        exit_code, _, stderr = self.exec_sudo(f"systemctl restart {service_name}")
        return exit_code == 0
    
    def reload_service(self, service_name: str) -> bool:
        """Перезагрузка конфигурации сервиса"""
        exit_code, _, stderr = self.exec_sudo(f"systemctl reload {service_name}")
        return exit_code == 0
    
    def enable_service(self, service_name: str) -> bool:
        """Включение автозапуска сервиса"""
        exit_code, _, stderr = self.exec_sudo(f"systemctl enable {service_name}")
        return exit_code == 0
