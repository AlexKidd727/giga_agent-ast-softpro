"""
Менеджер SSL сертификатов через Let's Encrypt / Certbot
"""
import logging
import time
from typing import Optional, List, Tuple

from .ssh_client import SSHManager
from .nginx_manager import NginxManager
from ..config import (
    DEFAULT_ACME_WEBROOT,
    SSH_COMMAND_TIMEOUT
)

logger = logging.getLogger(__name__)


class SSLManager:
    """Менеджер SSL сертификатов"""
    
    def __init__(self, ssh: SSHManager, nginx: NginxManager):
        self.ssh = ssh
        self.nginx = nginx
    
    def is_certbot_installed(self) -> bool:
        """Проверка, установлен ли certbot"""
        return self.ssh.is_package_installed("certbot")
    
    def install_certbot(self) -> Tuple[bool, str]:
        """Установка certbot"""
        if self.is_certbot_installed():
            return True, "Certbot уже установлен"
        
        success, msg = self.ssh.install_package("certbot")
        if success:
            return True, "Certbot установлен"
        return False, msg
    
    def certificate_exists(self, domain: str) -> bool:
        """Проверка существования сертификата для домена"""
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        return self.ssh.file_exists(cert_path)
    
    def get_certificate_info(self, domain: str) -> Optional[dict]:
        """Получение информации о сертификате"""
        cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        
        if not self.ssh.file_exists(cert_path):
            return None
        
        # Получаем информацию о сертификате через openssl
        exit_code, stdout, _ = self.ssh.exec_command(
            f"openssl x509 -in {cert_path} -noout -dates -subject 2>/dev/null"
        )
        
        if exit_code != 0:
            return None
        
        info = {"path": cert_path}
        for line in stdout.strip().split("\n"):
            if "notBefore=" in line:
                info["not_before"] = line.split("=", 1)[1].strip()
            elif "notAfter=" in line:
                info["not_after"] = line.split("=", 1)[1].strip()
            elif "subject=" in line:
                info["subject"] = line.split("=", 1)[1].strip()
        
        return info
    
    def obtain_certificate(
        self,
        domain: str,
        email: str,
        include_www: bool = False,
        force_renew: bool = False
    ) -> Tuple[bool, str, List[str]]:
        """
        Получение SSL сертификата через certbot webroot
        
        Args:
            domain: Основной домен
            email: Email для уведомлений Let's Encrypt
            include_www: Включать ли www вариант
            force_renew: Принудительное обновление
            
        Returns:
            Tuple[success, message, details]
        """
        details = []
        
        # Установка certbot если нужно
        if not self.is_certbot_installed():
            success, msg = self.install_certbot()
            if not success:
                return False, f"Не удалось установить certbot: {msg}", details
            details.append("Certbot установлен")
        else:
            details.append("Certbot найден")
        
        # Проверяем, есть ли уже сертификат
        domains = NginxManager.expand_www(domain, include_www)
        primary_domain = domains[0]
        
        if self.certificate_exists(primary_domain) and not force_renew:
            details.append(f"Сертификат для {primary_domain} уже существует")
            return True, "Сертификат уже существует", details
        
        # Подготовка webroot
        self.ssh.exec_sudo(f"mkdir -p {DEFAULT_ACME_WEBROOT}/.well-known/acme-challenge")
        self.ssh.exec_sudo(f"chmod -R 755 {DEFAULT_ACME_WEBROOT}")
        details.append(f"Подготовлен webroot: {DEFAULT_ACME_WEBROOT}")
        
        # Проверяем, что NGINX настроен для ACME challenge
        # Создаем временный HTTP-only конфиг если нужно
        if not self.nginx.site_config_exists(domain):
            success, msg, config_details = self.nginx.create_site_config(
                domain=domain,
                include_www=include_www,
                enable_ssl=False,  # Пока без SSL
                config_type="proxy"
            )
            if not success:
                return False, f"Не удалось создать NGINX конфиг: {msg}", details + config_details
            details.extend(config_details)
        
        # Формируем команду certbot
        domains_args = " ".join([f"-d {d}" for d in domains])
        certbot_cmd = (
            f"certbot certonly --webroot "
            f"-w {DEFAULT_ACME_WEBROOT} "
            f"{domains_args} "
            f"--email {email} "
            f"--agree-tos "
            f"--non-interactive "
            f"--keep-until-expiring"
        )
        
        if force_renew:
            certbot_cmd += " --force-renewal"
        
        details.append(f"Запрос сертификата для {domain}...")
        
        # Выполняем certbot (может занять время)
        exit_code, stdout, stderr = self.ssh.exec_sudo(certbot_cmd)
        
        if exit_code != 0:
            error_msg = stderr or stdout
            details.append(f"Ошибка certbot: {error_msg}")
            return False, f"Не удалось получить сертификат: {error_msg}", details
        
        details.append("Сертификат успешно получен")
        
        # Проверяем, что сертификат создан
        if not self.certificate_exists(primary_domain):
            return False, "Сертификат не найден после выполнения certbot", details
        
        return True, f"SSL сертификат для {domain} получен", details
    
    def enable_https_for_site(
        self,
        domain: str,
        upstream_port: str = "3000",
        include_www: bool = False,
        config_type: str = "proxy",
        static_root: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Tuple[bool, str, List[str]]:
        """
        Включение HTTPS для сайта (обновление NGINX конфига)
        
        Предполагается, что сертификат уже получен.
        """
        details = []
        domains = NginxManager.expand_www(domain, include_www)
        primary_domain = domains[0]
        
        # Проверяем наличие сертификата
        if not self.certificate_exists(primary_domain):
            return False, f"Сертификат не найден для {primary_domain}", details
        
        # Обновляем NGINX конфиг с SSL
        success, msg, config_details = self.nginx.create_site_config(
            domain=domain,
            upstream_port=upstream_port,
            include_www=include_www,
            enable_ssl=True,
            config_type=config_type,
            static_root=static_root,
            project_id=project_id,
            check_conflicts=False  # Мы обновляем свой же конфиг
        )
        
        details.extend(config_details)
        
        if not success:
            return False, f"Не удалось обновить NGINX конфиг: {msg}", details
        
        details.append("HTTPS включен")
        return True, f"HTTPS включен для {domain}", details
    
    def setup_auto_renewal(self, domain: str) -> Tuple[bool, str, List[str]]:
        """
        Настройка автоматического обновления сертификата
        
        Создает cron задачу для регулярного обновления.
        """
        details = []
        safe_domain = domain.replace(".", "_")
        
        # Скрипт обновления
        renew_script = f"""#!/bin/bash
# Автоматическое обновление SSL сертификата для {domain}
# Создано GigaAgent Deploy Agent

/usr/bin/certbot renew --quiet
sudo systemctl reload nginx

echo "$(date): certbot renew выполнен для {domain}" >> /var/log/certbot_renew.log
"""
        
        script_path = f"/usr/local/bin/renew_ssl_{safe_domain}.sh"
        
        # Записываем скрипт
        self.ssh.write_file(script_path, renew_script, sudo=True)
        self.ssh.exec_sudo(f"chmod +x {script_path}")
        details.append(f"Создан скрипт обновления: {script_path}")
        
        # Добавляем в cron (каждые 60 дней в 3:00)
        cron_line = f"0 3 */60 * * {script_path}"
        
        # Проверяем, нет ли уже такой задачи
        exit_code, stdout, _ = self.ssh.exec_sudo("crontab -l 2>/dev/null || true")
        current_cron = stdout.strip()
        
        if script_path in current_cron:
            details.append("Cron задача уже существует")
            return True, "Автообновление уже настроено", details
        
        # Добавляем новую задачу
        new_cron = f"{current_cron}\n{cron_line}" if current_cron else cron_line
        
        # Записываем новый crontab
        temp_cron = f"/tmp/crontab_{int(time.time())}.tmp"
        self.ssh.write_file(temp_cron, new_cron + "\n", sudo=False)
        exit_code, _, stderr = self.ssh.exec_sudo(f"crontab {temp_cron}")
        self.ssh.exec_command(f"rm -f {temp_cron}")
        
        if exit_code != 0:
            return False, f"Не удалось добавить cron задачу: {stderr}", details
        
        details.append(f"Добавлена cron задача: {cron_line}")
        return True, "Автообновление настроено", details
    
    def full_ssl_setup(
        self,
        domain: str,
        email: str,
        upstream_port: str = "3000",
        include_www: bool = False,
        config_type: str = "proxy",
        static_root: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> Tuple[bool, str, List[str]]:
        """
        Полная настройка SSL: получение сертификата + настройка NGINX + автообновление
        
        Это основной метод для настройки SSL "под ключ".
        """
        all_details = []
        
        # 1. Получаем сертификат
        success, msg, details = self.obtain_certificate(
            domain=domain,
            email=email,
            include_www=include_www
        )
        all_details.extend(details)
        
        if not success:
            return False, msg, all_details
        
        # 2. Включаем HTTPS в NGINX
        success, msg, details = self.enable_https_for_site(
            domain=domain,
            upstream_port=upstream_port,
            include_www=include_www,
            config_type=config_type,
            static_root=static_root,
            project_id=project_id
        )
        all_details.extend(details)
        
        if not success:
            return False, msg, all_details
        
        # 3. Настраиваем автообновление
        success, msg, details = self.setup_auto_renewal(domain)
        all_details.extend(details)
        
        if not success:
            # Не критично, SSL уже работает
            all_details.append(f"Предупреждение: {msg}")
        
        return True, f"SSL полностью настроен для {domain}", all_details
    
    def renew_certificate(self, domain: Optional[str] = None) -> Tuple[bool, str]:
        """Принудительное обновление сертификата"""
        if domain:
            cmd = f"certbot renew --cert-name {domain} --force-renewal"
        else:
            cmd = "certbot renew --force-renewal"
        
        exit_code, stdout, stderr = self.ssh.exec_sudo(cmd)
        
        if exit_code == 0:
            self.nginx.reload()
            return True, "Сертификат обновлен"
        return False, stderr or stdout
    
    def revoke_certificate(self, domain: str) -> Tuple[bool, str]:
        """Отзыв сертификата"""
        cert_path = f"/etc/letsencrypt/live/{domain}/cert.pem"
        
        if not self.ssh.file_exists(cert_path):
            return False, f"Сертификат не найден: {cert_path}"
        
        exit_code, stdout, stderr = self.ssh.exec_sudo(
            f"certbot revoke --cert-path {cert_path} --non-interactive"
        )
        
        if exit_code == 0:
            return True, f"Сертификат для {domain} отозван"
        return False, stderr or stdout
