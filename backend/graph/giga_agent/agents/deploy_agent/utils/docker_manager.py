"""
Менеджер Docker для развертывания контейнеров
"""
import logging
import time
from typing import Optional, List, Tuple, Dict

from .ssh_client import SSHManager
from ..config import DEFAULT_DEPLOYMENT_PATH

logger = logging.getLogger(__name__)


class DockerManager:
    """Менеджер для работы с Docker"""
    
    def __init__(self, ssh: SSHManager):
        self.ssh = ssh
    
    def is_docker_installed(self) -> bool:
        """Проверка, установлен ли Docker"""
        return self.ssh.is_package_installed("docker")
    
    def is_docker_compose_installed(self) -> bool:
        """Проверка, установлен ли Docker Compose"""
        # Проверяем оба варианта: docker-compose и docker compose
        exit_code1, _, _ = self.ssh.exec_command("docker-compose --version 2>/dev/null")
        exit_code2, _, _ = self.ssh.exec_command("docker compose version 2>/dev/null")
        return exit_code1 == 0 or exit_code2 == 0
    
    def install_docker(self) -> Tuple[bool, str]:
        """Установка Docker"""
        if self.is_docker_installed():
            return True, "Docker уже установлен"
        
        distro = self.ssh.detect_distro()
        
        if distro in ["ubuntu", "debian"]:
            # Установка через официальный скрипт Docker
            commands = [
                "apt-get update",
                "apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release",
                "curl -fsSL https://get.docker.com -o /tmp/get-docker.sh",
                "sh /tmp/get-docker.sh",
                "rm /tmp/get-docker.sh",
                "systemctl enable docker",
                "systemctl start docker"
            ]
        elif distro in ["centos", "rhel", "fedora"]:
            commands = [
                "yum install -y yum-utils",
                "yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo",
                "yum install -y docker-ce docker-ce-cli containerd.io",
                "systemctl enable docker",
                "systemctl start docker"
            ]
        else:
            # Fallback на apt
            success, msg = self.ssh.install_package("docker")
            if success:
                self.ssh.enable_service("docker")
                self.ssh.start_service("docker")
            return success, msg
        
        for cmd in commands:
            exit_code, _, stderr = self.ssh.exec_sudo(cmd)
            if exit_code != 0:
                logger.error(f"Ошибка выполнения: {cmd}: {stderr}")
                # Продолжаем, некоторые ошибки не критичны
        
        if self.is_docker_installed():
            return True, "Docker установлен и запущен"
        return False, "Не удалось установить Docker"
    
    def install_docker_compose(self) -> Tuple[bool, str]:
        """Установка Docker Compose"""
        if self.is_docker_compose_installed():
            return True, "Docker Compose уже установлен"
        
        # Пробуем установить через пакетный менеджер
        success, msg = self.ssh.install_package("docker")  # Обычно включает compose
        
        if not self.is_docker_compose_installed():
            # Устанавливаем плагин docker compose
            self.ssh.exec_sudo("apt-get install -y docker-compose-plugin 2>/dev/null || true")
            self.ssh.exec_sudo("yum install -y docker-compose-plugin 2>/dev/null || true")
        
        if self.is_docker_compose_installed():
            return True, "Docker Compose установлен"
        return False, "Не удалось установить Docker Compose"
    
    def get_docker_compose_command(self) -> str:
        """Получение команды docker compose (v1 или v2)"""
        exit_code, _, _ = self.ssh.exec_command("docker compose version 2>/dev/null")
        if exit_code == 0:
            return "docker compose"
        return "docker-compose"
    
    def docker_login(
        self,
        username: str,
        password: str,
        registry: str = "docker.io"
    ) -> Tuple[bool, str]:
        """Авторизация в Docker registry"""
        # Используем stdin для пароля (безопаснее)
        exit_code, stdout, stderr = self.ssh.exec_command(
            f"echo '{password}' | docker login -u {username} --password-stdin {registry}"
        )
        
        if exit_code == 0:
            return True, f"Авторизация в {registry} успешна"
        return False, stderr or stdout
    
    def pull_image(self, image: str) -> Tuple[bool, str]:
        """Загрузка Docker образа"""
        exit_code, stdout, stderr = self.ssh.exec_sudo(f"docker pull {image}")
        
        if exit_code == 0:
            return True, f"Образ {image} загружен"
        return False, stderr or stdout
    
    def list_containers(self, all_containers: bool = False) -> List[Dict]:
        """Получение списка контейнеров"""
        flag = "-a" if all_containers else ""
        exit_code, stdout, _ = self.ssh.exec_command(
            f"docker ps {flag} --format '{{{{.ID}}}}|{{{{.Names}}}}|{{{{.Status}}}}|{{{{.Image}}}}|{{{{.Ports}}}}'"
        )
        
        if exit_code != 0 or not stdout.strip():
            return []
        
        containers = []
        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                containers.append({
                    "id": parts[0],
                    "name": parts[1],
                    "status": parts[2],
                    "image": parts[3],
                    "ports": parts[4] if len(parts) > 4 else ""
                })
        
        return containers
    
    def get_container_by_name(self, name: str) -> Optional[Dict]:
        """Получение контейнера по имени"""
        containers = self.list_containers(all_containers=True)
        for container in containers:
            if container["name"] == name:
                return container
        return None
    
    def container_exists(self, name: str) -> bool:
        """Проверка существования контейнера"""
        return self.get_container_by_name(name) is not None
    
    def start_container(self, name_or_id: str) -> Tuple[bool, str]:
        """Запуск контейнера"""
        exit_code, stdout, stderr = self.ssh.exec_sudo(f"docker start {name_or_id}")
        if exit_code == 0:
            return True, f"Контейнер {name_or_id} запущен"
        return False, stderr or stdout
    
    def stop_container(self, name_or_id: str) -> Tuple[bool, str]:
        """Остановка контейнера"""
        exit_code, stdout, stderr = self.ssh.exec_sudo(f"docker stop {name_or_id}")
        if exit_code == 0:
            return True, f"Контейнер {name_or_id} остановлен"
        return False, stderr or stdout
    
    def restart_container(self, name_or_id: str) -> Tuple[bool, str]:
        """Перезапуск контейнера"""
        exit_code, stdout, stderr = self.ssh.exec_sudo(f"docker restart {name_or_id}")
        if exit_code == 0:
            return True, f"Контейнер {name_or_id} перезапущен"
        return False, stderr or stdout
    
    def remove_container(self, name_or_id: str, force: bool = False) -> Tuple[bool, str]:
        """Удаление контейнера"""
        flag = "-f" if force else ""
        exit_code, stdout, stderr = self.ssh.exec_sudo(f"docker rm {flag} {name_or_id}")
        if exit_code == 0:
            return True, f"Контейнер {name_or_id} удален"
        return False, stderr or stdout
    
    def get_container_logs(
        self,
        name_or_id: str,
        tail: int = 100
    ) -> Tuple[bool, str]:
        """Получение логов контейнера"""
        exit_code, stdout, stderr = self.ssh.exec_command(
            f"docker logs --tail {tail} {name_or_id}"
        )
        if exit_code == 0:
            return True, stdout
        return False, stderr or "Не удалось получить логи"
    
    def run_container(
        self,
        image: str,
        name: str,
        ports: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        restart_policy: str = "unless-stopped",
        detach: bool = True,
        network: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Запуск нового контейнера
        
        Args:
            image: Docker образ
            name: Имя контейнера
            ports: Маппинг портов {"host_port": "container_port"}
            volumes: Маппинг томов {"host_path": "container_path"}
            env_vars: Переменные окружения
            restart_policy: Политика перезапуска
            detach: Запуск в фоне
            network: Docker сеть
        """
        cmd_parts = ["docker run"]
        
        if detach:
            cmd_parts.append("-d")
        
        cmd_parts.append(f"--name {name}")
        cmd_parts.append(f"--restart {restart_policy}")
        
        if network:
            cmd_parts.append(f"--network {network}")
        
        if ports:
            for host_port, container_port in ports.items():
                cmd_parts.append(f"-p {host_port}:{container_port}")
        
        if volumes:
            for host_path, container_path in volumes.items():
                cmd_parts.append(f"-v {host_path}:{container_path}")
        
        if env_vars:
            for key, value in env_vars.items():
                cmd_parts.append(f"-e {key}={value}")
        
        cmd_parts.append(image)
        
        cmd = " ".join(cmd_parts)
        exit_code, stdout, stderr = self.ssh.exec_sudo(cmd)
        
        if exit_code == 0:
            return True, f"Контейнер {name} запущен"
        return False, stderr or stdout
    
    def compose_up(
        self,
        compose_file: str,
        project_name: Optional[str] = None,
        detach: bool = True,
        build: bool = False
    ) -> Tuple[bool, str]:
        """Запуск docker-compose"""
        compose_cmd = self.get_docker_compose_command()
        
        cmd_parts = [compose_cmd, f"-f {compose_file}"]
        
        if project_name:
            cmd_parts.append(f"-p {project_name}")
        
        cmd_parts.append("up")
        
        if detach:
            cmd_parts.append("-d")
        
        if build:
            cmd_parts.append("--build")
        
        cmd = " ".join(cmd_parts)
        exit_code, stdout, stderr = self.ssh.exec_sudo(cmd)
        
        if exit_code == 0:
            return True, "Docker Compose запущен"
        return False, stderr or stdout
    
    def compose_down(
        self,
        compose_file: str,
        project_name: Optional[str] = None,
        remove_volumes: bool = False
    ) -> Tuple[bool, str]:
        """Остановка docker-compose"""
        compose_cmd = self.get_docker_compose_command()
        
        cmd_parts = [compose_cmd, f"-f {compose_file}"]
        
        if project_name:
            cmd_parts.append(f"-p {project_name}")
        
        cmd_parts.append("down")
        
        if remove_volumes:
            cmd_parts.append("-v")
        
        cmd = " ".join(cmd_parts)
        exit_code, stdout, stderr = self.ssh.exec_sudo(cmd)
        
        if exit_code == 0:
            return True, "Docker Compose остановлен"
        return False, stderr or stdout
    
    def compose_logs(
        self,
        compose_file: str,
        project_name: Optional[str] = None,
        service: Optional[str] = None,
        tail: int = 100
    ) -> Tuple[bool, str]:
        """Получение логов docker-compose"""
        compose_cmd = self.get_docker_compose_command()
        
        cmd_parts = [compose_cmd, f"-f {compose_file}"]
        
        if project_name:
            cmd_parts.append(f"-p {project_name}")
        
        cmd_parts.append(f"logs --tail {tail}")
        
        if service:
            cmd_parts.append(service)
        
        cmd = " ".join(cmd_parts)
        exit_code, stdout, stderr = self.ssh.exec_command(cmd)
        
        if exit_code == 0:
            return True, stdout
        return False, stderr or "Не удалось получить логи"
    
    def build_image(
        self,
        dockerfile_path: str,
        image_name: str,
        context_path: Optional[str] = None,
        no_cache: bool = False
    ) -> Tuple[bool, str]:
        """Сборка Docker образа"""
        context = context_path or "."
        
        cmd_parts = ["docker build"]
        
        if no_cache:
            cmd_parts.append("--no-cache")
        
        cmd_parts.append(f"-t {image_name}")
        cmd_parts.append(f"-f {dockerfile_path}")
        cmd_parts.append(context)
        
        cmd = " ".join(cmd_parts)
        exit_code, stdout, stderr = self.ssh.exec_sudo(cmd)
        
        if exit_code == 0:
            return True, f"Образ {image_name} собран"
        return False, stderr or stdout
    
    def deploy_project(
        self,
        project_name: str,
        project_path: str,
        compose_file: str = "docker-compose.yml",
        build: bool = True
    ) -> Tuple[bool, str, List[str]]:
        """
        Развертывание проекта через docker-compose
        
        Args:
            project_name: Имя проекта
            project_path: Путь к проекту на сервере
            compose_file: Имя файла docker-compose
            build: Собирать ли образы
            
        Returns:
            Tuple[success, message, details]
        """
        details = []
        
        # Проверяем наличие Docker
        if not self.is_docker_installed():
            success, msg = self.install_docker()
            if not success:
                return False, msg, details
            details.append("Docker установлен")
        
        # Проверяем наличие Docker Compose
        if not self.is_docker_compose_installed():
            success, msg = self.install_docker_compose()
            if not success:
                return False, msg, details
            details.append("Docker Compose установлен")
        
        # Проверяем существование директории проекта
        if not self.ssh.dir_exists(project_path):
            return False, f"Директория проекта не найдена: {project_path}", details
        
        compose_path = f"{project_path}/{compose_file}"
        
        # Проверяем наличие docker-compose файла
        if not self.ssh.file_exists(compose_path):
            return False, f"Файл {compose_file} не найден в {project_path}", details
        
        details.append(f"Найден {compose_file}")
        
        # Останавливаем старые контейнеры (если есть)
        self.compose_down(compose_path, project_name)
        details.append("Остановлены старые контейнеры (если были)")
        
        # Запускаем новые
        success, msg = self.compose_up(
            compose_path,
            project_name=project_name,
            detach=True,
            build=build
        )
        
        if not success:
            return False, f"Ошибка запуска: {msg}", details
        
        details.append("Контейнеры запущены")
        
        # Ждем немного и проверяем статус
        time.sleep(3)
        
        containers = self.list_containers()
        running = [c for c in containers if project_name in c["name"].lower()]
        
        if running:
            details.append(f"Запущено контейнеров: {len(running)}")
            for c in running:
                details.append(f"  - {c['name']}: {c['status']}")
        
        return True, f"Проект {project_name} развернут", details
    
    def get_container_port(self, name_or_id: str) -> Optional[str]:
        """Получение порта контейнера"""
        exit_code, stdout, _ = self.ssh.exec_command(
            f"docker port {name_or_id} 2>/dev/null | head -1"
        )
        
        if exit_code == 0 and stdout.strip():
            # Формат: 80/tcp -> 0.0.0.0:3000
            parts = stdout.strip().split(":")
            if len(parts) > 1:
                return parts[-1].strip()
        
        return None
    
    def cleanup_unused(self) -> Tuple[bool, str]:
        """Очистка неиспользуемых ресурсов Docker"""
        # Удаляем остановленные контейнеры
        self.ssh.exec_sudo("docker container prune -f")
        
        # Удаляем неиспользуемые образы
        self.ssh.exec_sudo("docker image prune -f")
        
        # Удаляем неиспользуемые тома
        self.ssh.exec_sudo("docker volume prune -f")
        
        # Удаляем неиспользуемые сети
        self.ssh.exec_sudo("docker network prune -f")
        
        return True, "Неиспользуемые ресурсы Docker очищены"
