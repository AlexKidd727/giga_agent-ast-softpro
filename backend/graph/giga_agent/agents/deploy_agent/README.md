# Deploy Agent

Агент для развертывания приложений на VPS серверах. Поддерживает Docker, NGINX, SSL/HTTPS через Let's Encrypt.

## Возможности

### 1. Первичная настройка сервера (`setup_server`)
- Обновление списка пакетов
- Установка базовых утилит (curl, wget, git, zip, htop)
- Настройка firewall (UFW/firewalld)
- Определение дистрибутива Linux

### 2. Развертывание Docker (`deploy_docker`)
- Автоматическая установка Docker и Docker Compose
- Поддержка docker run и docker-compose
- Управление контейнерами (start, stop, restart)
- Просмотр логов контейнеров

### 3. Настройка NGINX (`setup_nginx`)
- Установка и настройка NGINX
- Создание site-конфигов в `/etc/nginx/sites-available/`
- Поддержка proxy и static конфигураций
- WebSocket проксирование
- Автоматическое определение конфликтов доменов
- Бэкапы перед изменениями

### 4. Настройка SSL (`setup_ssl`)
- Установка certbot
- Получение сертификатов Let's Encrypt через webroot
- Обновление NGINX конфигурации для HTTPS
- HTTP -> HTTPS редирект
- Автоматическое обновление сертификатов (cron)

### 5. Управление сервисами (`manage_services`)
- Мониторинг статуса сервисов
- Информация о сервере (память, диск, uptime)
- Список контейнеров Docker
- Список активных сайтов NGINX

### 6. Полное развертывание (`full_deploy`)
Выполняет все шаги последовательно:
1. setup_server
2. deploy_docker
3. setup_nginx
4. setup_ssl

## Использование

### Как инструмент LangChain

```python
from backend.graph.giga_agent.agents.deploy_agent import deploy_agent_tool

# Полное развертывание
result = await deploy_agent_tool.ainvoke({
    "action": "full_deploy",
    "vps_ip": "123.45.67.89",
    "vps_login": "root",
    "vps_password": "your_password",
    "project_name": "myapp",
    "domain": "example.com",
    "docker_image": "myapp:latest",
    "app_port": "3000",
    "ssl_email": "admin@example.com",
    "include_www": True
})

print(result["logs"])  # Список выполненных действий
print(result["result"])  # Результат
print(result["error"])  # Ошибка (если есть)
```

### Только настройка SSL

```python
result = await deploy_agent_tool.ainvoke({
    "action": "setup_ssl",
    "vps_ip": "123.45.67.89",
    "vps_login": "root",
    "vps_password": "your_password",
    "domain": "example.com",
    "ssl_email": "admin@example.com"
})
```

### Проверка статуса

```python
result = await deploy_agent_tool.ainvoke({
    "action": "manage_services",
    "vps_ip": "123.45.67.89",
    "vps_login": "root",
    "vps_password": "your_password",
    "project_name": "myapp"  # Опционально, для фильтрации контейнеров
})
```

## Параметры

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| action | str | Да | Действие: setup_server, deploy_docker, setup_nginx, setup_ssl, manage_services, full_deploy |
| vps_ip | str | Да | IP адрес VPS сервера |
| vps_login | str | Да | Логин для SSH |
| vps_password | str | Да* | Пароль для SSH |
| vps_ssh_key | str | Да* | Приватный SSH ключ (альтернатива паролю) |
| project_name | str | Нет | Имя проекта |
| domain | str | Нет** | Домен для NGINX и SSL |
| app_port | str | Нет | Порт приложения (по умолчанию 3000) |
| docker_image | str | Нет | Docker образ для запуска |
| docker_compose_path | str | Нет | Путь к docker-compose.yml |
| ssl_email | str | Нет*** | Email для Let's Encrypt |
| include_www | bool | Нет | Включать www вариант домена |
| nginx_config_type | str | Нет | Тип конфигурации: proxy или static |
| static_root | str | Нет | Корневая директория для статики |

\* Требуется либо vps_password, либо vps_ssh_key  
\** Обязательно для setup_nginx и setup_ssl  
\*** Обязательно для setup_ssl

## Архитектура

```
deploy_agent/
├── __init__.py           # Экспорт graph и deploy_agent_tool
├── config.py             # Конфигурация и типы состояния
├── graph.py              # Основной граф LangGraph
├── README.md             # Документация
├── nodes/
│   ├── __init__.py
│   ├── setup_server.py   # Узел настройки сервера
│   ├── deploy_docker.py  # Узел развертывания Docker
│   ├── setup_nginx.py    # Узел настройки NGINX
│   ├── setup_ssl.py      # Узел настройки SSL
│   └── manage_services.py # Узел управления сервисами
├── prompts/
│   └── __init__.py       # Системные промпты
└── utils/
    ├── __init__.py
    ├── ssh_client.py     # SSH менеджер
    ├── nginx_manager.py  # NGINX менеджер
    ├── docker_manager.py # Docker менеджер
    └── ssl_manager.py    # SSL/Certbot менеджер
```

## Принципы безопасности

1. **Изоляция конфигураций**: Каждый сайт имеет отдельный конфиг в sites-available. Не трогаем nginx.conf и конфиги других сайтов.

2. **Маркеры**: Все созданные конфигурации помечаются маркером `# Managed by GigaAgent Deploy Agent` для идентификации.

3. **Бэкапы**: Перед любым изменением конфигурации создается резервная копия с timestamp.

4. **Проверка**: После изменения NGINX конфигурации всегда выполняется `nginx -t` перед `reload`.

5. **Откат**: При ошибке синтаксиса NGINX автоматически откатывается к предыдущей конфигурации.

6. **Конфликты доменов**: Перед созданием конфига проверяется, не используется ли домен в других конфигах.

## Пример NGINX конфигурации

### HTTP (без SSL)

```nginx
# Managed by GigaAgent Deploy Agent (project_id=myapp)

# HTTP (включая ACME challenge для Let's Encrypt)
server {
    listen 80;
    server_name example.com www.example.com;

    # ACME challenge для Let's Encrypt (webroot)
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        try_files $uri =404;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
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
    }
}
```

### HTTPS (с SSL)

```nginx
# Managed by GigaAgent Deploy Agent (project_id=myapp)

# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name example.com www.example.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS
server {
    listen 443 ssl http2;
    server_name example.com www.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    
    # Безопасность
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://127.0.0.1:3000;
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
    }
}
```

## Поддерживаемые дистрибутивы

- Ubuntu (apt-get)
- Debian (apt-get)
- CentOS (yum)
- RHEL (yum)
- Fedora (dnf)

## Зависимости

- paramiko (SSH клиент)
- langgraph
- langchain_core

## Интеграция с основным агентом

Для добавления в основной агент GigaAgent:

1. Импортировать инструмент:
```python
from backend.graph.giga_agent.agents.deploy_agent import deploy_agent_tool
```

2. Добавить в список инструментов:
```python
tools = [
    # ... другие инструменты
    deploy_agent_tool
]
```

3. Обновить системный промпт с описанием возможностей Deploy Agent.
