# Быстрый старт: Развертывание на VPS

## Предварительные требования

1. Установлен PuTTY (должен быть в `C:\Program Files\PuTTY\`)
2. SSH ключ добавлен на сервер (см. ниже)

## Шаги развертывания

### Шаг 1: Создание SSH ключа (если еще не создан)

Запустите:
```cmd
create_ssh_key.bat
```

Скрипт создаст SSH ключ и покажет публичный ключ. **ВАЖНО**: Скопируйте публичный ключ и добавьте его на сервер через веб-интерфейс Cloud.ru:

1. Войдите в панель управления Cloud.ru
2. Перейдите в настройки вашей ВМ (<your-server-ip>)
3. Найдите раздел "SSH ключи" или "Авторизация"
4. Добавьте публичный ключ (начинается с `ssh-rsa AAAAB3NzaC1yc2E...`)

### Шаг 2: Развертывание проекта

После добавления ключа на сервер, запустите:
```cmd
deploy_full.bat
```

Скрипт автоматически:
1. ✅ Подключится к серверу
2. ✅ Создаст директорию `/opt/giga-agents`
3. ✅ Проверит и установит Docker (если нужно)
4. ✅ Скопирует все файлы проекта
5. ✅ Настроит и запустит проект через Docker Compose

### Шаг 3: Проверка

После завершения развертывания приложение будет доступно по адресу:
**http://<your-server-ip>:8502**

## Ручное развертывание (альтернатива)

Если автоматическое развертывание не работает, можно выполнить вручную:

1. Подключитесь к серверу:
   ```cmd
   "C:\Program Files\PuTTY\plink.exe" -ssh -i "%USERPROFILE%\.ssh\giga_agent_key" user1@<your-server-ip>
   ```

2. На сервере выполните:
   ```bash
   sudo mkdir -p /opt/giga-agents
   sudo chown user1:user1 /opt/giga-agents
   cd /opt/giga-agents
   ```

3. Скопируйте файлы с локальной машины (в отдельном окне PowerShell):
   ```cmd
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" -r backend user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" -r front user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" -r credentials user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" -r db user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" docker-compose.yml user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" .docker.env user1@<your-server-ip>:/opt/giga-agents/
   "C:\Program Files\PuTTY\pscp.exe" -i "%USERPROFILE%\.ssh\giga_agent_key" Makefile user1@<your-server-ip>:/opt/giga-agents/
   ```

4. На сервере выполните скрипт развертывания:
   ```bash
   cd /opt/giga-agents
   chmod +x deploy_auto.sh
   bash deploy_auto.sh
   ```

## Устранение проблем

### Ошибка "No supported authentication methods available"

Сервер требует SSH ключ. Убедитесь, что:
1. SSH ключ создан (`create_ssh_key.bat`)
2. Публичный ключ добавлен на сервер через веб-интерфейс Cloud.ru

### Ошибка при копировании файлов

Проверьте:
- Доступность сервера (ping <your-server-ip>)
- Правильность пути к PuTTY
- Наличие всех необходимых файлов в локальной директории

### Docker не запускается

На сервере выполните:
```bash
sudo systemctl status docker
sudo usermod -aG docker $USER
newgrp docker
```

### Порт 8502 недоступен

Убедитесь, что порт открыт в настройках безопасности Cloud.ru:
- Протокол: TCP
- Порт: 8502
- Источник: 0.0.0.0/0

## Файлы проекта

- `create_ssh_key.bat` - создание SSH ключа
- `deploy_full.bat` - автоматическое развертывание
- `deploy_auto.sh` - скрипт настройки на сервере
- `DEPLOY_INSTRUCTIONS.md` - подробная инструкция

