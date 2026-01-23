"""
Менеджер NGINX для настройки веб-сервера
"""
import logging
import re
import time
from typing import Optional, List, Tuple

from .ssh_client import SSHManager
from ..config import (
    DEPLOY_AGENT_MARKER,
    DEFAULT_NGINX_SITES_AVAILABLE,
    DEFAULT_NGINX_SITES_ENABLED,
    DEFAULT_ACME_WEBROOT
)

logger = logging.getLogger(__name__)


class NginxManager:
    """Менеджер для работы с NGINX"""
    
    def __init__(self, ssh: SSHManager):
        self.ssh = ssh
    
    def is_installed(self) -> bool:
        """Проверка, установлен ли NGINX"""
        return self.ssh.is_package_installed("nginx")
    
    def install(self) -> Tuple[bool, str]:
        """Установка NGINX"""
        if self.is_installed():
            return True, "NGINX уже установлен"
        
        success, msg = self.ssh.install_package("nginx")
        if success:
            # Включаем автозапуск
            self.ssh.enable_service("nginx")
            self.ssh.start_service("nginx")
            return True, "NGINX установлен и запущен"
        return False, msg
    
    def get_status(self) -> str:
        """Получение статуса NGINX"""
        return self.ssh.get_service_status("nginx")
    
    def test_config(self) -> Tuple[bool, str]:
        """Проверка синтаксиса конфигурации"""
        exit_code, stdout, stderr = self.ssh.exec_sudo("nginx -t")
        if exit_code == 0:
            return True, "Конфигурация корректна"
        return False, stderr or stdout
    
    def reload(self) -> Tuple[bool, str]:
        """Перезагрузка NGINX"""
        # Сначала проверяем конфигурацию
        valid, msg = self.test_config()
        if not valid:
            return False, f"Ошибка конфигурации: {msg}"
        
        if self.ssh.reload_service("nginx"):
            return True, "NGINX перезагружен"
        return False, "Не удалось перезагрузить NGINX"
    
    def restart(self) -> Tuple[bool, str]:
        """Перезапуск NGINX"""
        if self.ssh.restart_service("nginx"):
            return True, "NGINX перезапущен"
        return False, "Не удалось перезапустить NGINX"
    
    @staticmethod
    def safe_filename(domain: str) -> str:
        """Преобразование домена в безопасное имя файла"""
        # Убираем www. в начале
        if domain.startswith("www."):
            domain = domain[4:]
        # Заменяем точки на подчеркивания
        return re.sub(r'[^a-zA-Z0-9_-]', '_', domain)
    
    @staticmethod
    def expand_www(domain: str, include_www: bool = False) -> List[str]:
        """Расширение домена с www вариантом"""
        domain = domain.strip().lower()
        
        if domain.startswith("www."):
            base = domain[4:]
            return [base, domain] if base else [domain]
        
        if include_www:
            return [domain, f"www.{domain}"]
        return [domain]
    
    def get_site_config_path(self, domain: str) -> str:
        """Получение пути к конфигу сайта"""
        filename = f"{self.safe_filename(domain)}.conf"
        return f"{DEFAULT_NGINX_SITES_AVAILABLE}/{filename}"
    
    def get_site_enabled_path(self, domain: str) -> str:
        """Получение пути к симлинку в sites-enabled"""
        filename = f"{self.safe_filename(domain)}.conf"
        return f"{DEFAULT_NGINX_SITES_ENABLED}/{filename}"
    
    def site_config_exists(self, domain: str) -> bool:
        """Проверка существования конфига сайта"""
        return self.ssh.file_exists(self.get_site_config_path(domain))
    
    def detect_domain_conflicts(
        self, 
        domains: List[str], 
        exclude_marker: str = DEPLOY_AGENT_MARKER
    ) -> List[str]:
        """
        Поиск конфликтов server_name среди sites-enabled.
        Возвращает список конфигов, где домен найден, но конфиг не помечен нашим маркером.
        """
        conflicts = []
        
        exit_code, stdout, _ = self.ssh.exec_command(
            f"ls {DEFAULT_NGINX_SITES_ENABLED}/*.conf 2>/dev/null || true"
        )
        
        if exit_code != 0 or not stdout.strip():
            return conflicts
        
        config_files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]
        
        for config_file in config_files:
            content = self.ssh.read_file(config_file, sudo=True)
            if not content:
                continue
            
            # Проверяем, есть ли наш маркер
            if exclude_marker in content:
                continue
            
            # Ищем server_name директивы
            for domain in domains:
                # Ищем точное совпадение server_name
                pattern = rf'\bserver_name\s+[^;]*\b{re.escape(domain)}\b'
                if re.search(pattern, content, re.IGNORECASE):
                    conflicts.append(config_file)
                    break
        
        return conflicts
    
    def build_site_config(
        self,
        domain: str,
        upstream_port: str = "3000",
        include_www: bool = False,
        enable_ssl: bool = False,
        config_type: str = "proxy",  # proxy | static
        static_root: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> str:
        """
        Генерация конфигурации NGINX для сайта
        
        Args:
            domain: Основной домен
            upstream_port: Порт приложения для проксирования
            include_www: Включать ли www вариант домена
            enable_ssl: Включить HTTPS (требует наличия сертификата)
            config_type: Тип конфигурации (proxy или static)
            static_root: Корневая директория для статики
            project_id: ID проекта для маркера
        """
        domains = self.expand_www(domain, include_www)
        server_names = " ".join(domains)
        primary_domain = domains[0]
        safe_name = self.safe_filename(primary_domain)
        
        # Маркер для идентификации конфига
        marker = f"{DEPLOY_AGENT_MARKER}"
        if project_id:
            marker += f" (project_id={project_id})"
        
        # Блок location для HTTP
        def location_block_http():
            if config_type == "static":
                root_dir = static_root or f"/var/www/{safe_name}"
                return f"""
    root {root_dir};
    index index.html index.htm;

    location / {{
        try_files $uri $uri/ =404;
    }}
"""
            # proxy (default)
            return f"""
    location / {{
        proxy_pass http://127.0.0.1:{upstream_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket поддержка
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
"""
        
        # Блок location для HTTPS
        def location_block_https():
            if config_type == "static":
                root_dir = static_root or f"/var/www/{safe_name}"
                return f"""
    root {root_dir};
    index index.html index.htm;

    location / {{
        try_files $uri $uri/ =404;
    }}
"""
            return f"""
    location / {{
        proxy_pass http://127.0.0.1:{upstream_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
"""
        
        # Базовый HTTP конфиг
        base_http = f"""{marker}

# HTTP (включая ACME challenge для Let's Encrypt)
server {{
    listen 80;
    server_name {server_names};

    # ACME challenge для Let's Encrypt (webroot)
    location ^~ /.well-known/acme-challenge/ {{
        root {DEFAULT_ACME_WEBROOT};
        try_files $uri =404;
    }}
{location_block_http()}
}}
"""
        
        if not enable_ssl:
            return base_http
        
        # HTTPS конфиг
        https_block = f"""
# HTTPS
server {{
    listen 443 ssl http2;
    server_name {server_names};

    ssl_certificate /etc/letsencrypt/live/{primary_domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{primary_domain}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    
    # Безопасность
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
{location_block_https()}
}}
"""
        
        # HTTP -> HTTPS redirect
        redirect_block = f"""
# HTTP -> HTTPS redirect
server {{
    listen 80;
    server_name {server_names};

    location ^~ /.well-known/acme-challenge/ {{
        root {DEFAULT_ACME_WEBROOT};
        try_files $uri =404;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}
"""
        
        return f"""{marker}

{redirect_block}
{https_block}
"""
    
    def create_site_config(
        self,
        domain: str,
        upstream_port: str = "3000",
        include_www: bool = False,
        enable_ssl: bool = False,
        config_type: str = "proxy",
        static_root: Optional[str] = None,
        project_id: Optional[str] = None,
        check_conflicts: bool = True
    ) -> Tuple[bool, str, List[str]]:
        """
        Создание конфигурации сайта
        
        Returns:
            Tuple[success, message, details]
        """
        details = []
        domains = self.expand_www(domain, include_www)
        
        # Проверка конфликтов
        if check_conflicts:
            conflicts = self.detect_domain_conflicts(domains)
            if conflicts:
                return False, f"Домен {domain} уже используется другим конфигом", conflicts
        
        # Подготовка ACME webroot
        self.ssh.exec_sudo(f"mkdir -p {DEFAULT_ACME_WEBROOT}/.well-known/acme-challenge")
        self.ssh.exec_sudo(f"chmod -R 755 {DEFAULT_ACME_WEBROOT}")
        details.append(f"Подготовлен ACME webroot: {DEFAULT_ACME_WEBROOT}")
        
        # Проверяем наличие сертификата для SSL
        if enable_ssl:
            cert_path = f"/etc/letsencrypt/live/{domains[0]}/fullchain.pem"
            if not self.ssh.file_exists(cert_path):
                logger.warning(f"SSL сертификат не найден: {cert_path}")
                enable_ssl = False
                details.append("SSL сертификат не найден, создается HTTP конфиг")
        
        # Генерируем конфиг
        config_content = self.build_site_config(
            domain=domain,
            upstream_port=upstream_port,
            include_www=include_www,
            enable_ssl=enable_ssl,
            config_type=config_type,
            static_root=static_root,
            project_id=project_id
        )
        
        config_path = self.get_site_config_path(domain)
        enabled_path = self.get_site_enabled_path(domain)
        
        # Бэкап существующего конфига
        if self.ssh.file_exists(config_path):
            backup_path = f"{config_path}.bak.{int(time.time())}"
            self.ssh.exec_sudo(f"cp {config_path} {backup_path}")
            details.append(f"Создана резервная копия: {backup_path}")
        
        # Записываем конфиг
        self.ssh.write_file(config_path, config_content, sudo=True)
        details.append(f"Записан конфиг: {config_path}")
        
        # Создаем симлинк в sites-enabled
        self.ssh.exec_sudo(f"ln -sf {config_path} {enabled_path}")
        details.append(f"Активирован: {enabled_path}")
        
        # Проверяем конфигурацию
        valid, msg = self.test_config()
        if not valid:
            # Откатываем: удаляем симлинк
            self.ssh.exec_sudo(f"rm -f {enabled_path}")
            return False, f"Ошибка синтаксиса NGINX: {msg}", details
        
        # Перезагружаем NGINX
        success, msg = self.reload()
        if not success:
            return False, f"Не удалось перезагрузить NGINX: {msg}", details
        
        details.append("NGINX перезагружен")
        return True, "Конфигурация создана и применена", details
    
    def remove_site_config(self, domain: str) -> Tuple[bool, str]:
        """Удаление конфигурации сайта"""
        config_path = self.get_site_config_path(domain)
        enabled_path = self.get_site_enabled_path(domain)
        
        # Удаляем симлинк
        if self.ssh.file_exists(enabled_path):
            self.ssh.exec_sudo(f"rm -f {enabled_path}")
        
        # Удаляем конфиг (с бэкапом)
        if self.ssh.file_exists(config_path):
            backup_path = f"{config_path}.bak.removed.{int(time.time())}"
            self.ssh.exec_sudo(f"mv {config_path} {backup_path}")
        
        # Перезагружаем NGINX
        self.reload()
        
        return True, f"Конфигурация для {domain} удалена"
    
    def get_active_sites(self) -> List[str]:
        """Получение списка активных сайтов"""
        exit_code, stdout, _ = self.ssh.exec_command(
            f"ls {DEFAULT_NGINX_SITES_ENABLED}/ 2>/dev/null || true"
        )
        if exit_code != 0 or not stdout.strip():
            return []
        return [f.strip() for f in stdout.strip().split("\n") if f.strip()]
    
    def get_site_config_content(self, domain: str) -> Optional[str]:
        """Получение содержимого конфига сайта"""
        config_path = self.get_site_config_path(domain)
        return self.ssh.read_file(config_path, sudo=True)
