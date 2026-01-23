"""
Конфигурация Deploy Agent
"""
from typing import TypedDict, Optional, Annotated, Literal
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage


class DeployAgentState(TypedDict):
    """Состояние агента деплоя"""
    messages: Annotated[list[AnyMessage], add_messages]
    user_request: str
    user_id: str
    
    # Параметры подключения к VPS
    vps_ip: Optional[str]
    vps_login: Optional[str]
    vps_password: Optional[str]
    vps_ssh_key: Optional[str]
    
    # Параметры проекта
    project_name: Optional[str]
    domain: Optional[str]
    app_port: Optional[str]
    deployment_type: Optional[Literal["docker", "static", "nodejs", "python"]]
    
    # Docker параметры
    docker_image: Optional[str]
    docker_compose_path: Optional[str]
    dockerfile_path: Optional[str]
    
    # Nginx параметры
    nginx_config_type: Optional[Literal["proxy", "static"]]
    static_root: Optional[str]
    include_www: Optional[bool]
    
    # SSL параметры
    ssl_email: Optional[str]
    ssl_enabled: Optional[bool]
    
    # Результаты
    result: Optional[dict]
    error: Optional[str]
    logs: Optional[list[str]]


# Маркер для идентификации конфигов, созданных этим агентом
DEPLOY_AGENT_MARKER = "# Managed by GigaAgent Deploy Agent"

# Директории по умолчанию
DEFAULT_DEPLOYMENT_PATH = "/opt/apps"
DEFAULT_NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
DEFAULT_NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
DEFAULT_ACME_WEBROOT = "/var/www/letsencrypt"

# Таймауты SSH (секунды)
SSH_CONNECT_TIMEOUT = 15
SSH_COMMAND_TIMEOUT = 300  # Для долгих операций типа certbot

# Порты по умолчанию
DEFAULT_APP_PORTS = {
    "docker": "3000",
    "nodejs": "3000",
    "python": "8000",
    "static": "80"
}

# Поддерживаемые дистрибутивы Linux
SUPPORTED_DISTROS = ["ubuntu", "debian", "centos", "fedora", "rhel"]

# Команды установки пакетов по дистрибутивам
PACKAGE_MANAGERS = {
    "ubuntu": "apt-get",
    "debian": "apt-get",
    "centos": "yum",
    "fedora": "dnf",
    "rhel": "yum"
}

# Пакеты для установки
REQUIRED_PACKAGES = {
    "nginx": {
        "apt-get": "nginx",
        "yum": "nginx",
        "dnf": "nginx"
    },
    "docker": {
        "apt-get": "docker.io docker-compose",
        "yum": "docker docker-compose",
        "dnf": "docker docker-compose"
    },
    "certbot": {
        "apt-get": "certbot",
        "yum": "certbot",
        "dnf": "certbot"
    },
    "zip": {
        "apt-get": "zip unzip",
        "yum": "zip unzip",
        "dnf": "zip unzip"
    }
}
