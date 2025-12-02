# Google Calendar Credentials

Эта папка предназначена для хранения файлов авторизации Google Calendar.

## Настройка

1. Создайте Service Account в Google Cloud Console
2. Скачайте JSON файл с ключами
3. Поместите файл в эту папку (например, `service-account.json` или `giga-agent-calendar-*.json`)
4. Установите переменную окружения в `.docker.env`:
   ```env
   # Для Docker (путь внутри контейнера)
   GOOGLE_CALENDAR_CREDENTIALS=/app/credentials/giga-agent-calendar-0ac99adb1c83.json
   # или если файл называется service-account.json:
   # GOOGLE_CALENDAR_CREDENTIALS=/app/credentials/service-account.json
   ```
   
   Для локального запуска (без Docker):
   ```env
   GOOGLE_CALENDAR_CREDENTIALS=./credentials/giga-agent-calendar-0ac99adb1c83.json
   ```

## Безопасность

⚠️ **Важно:** 
- Никогда не коммитьте файлы с ключами в Git
- Файлы *.json автоматически игнорируются
- Используйте переменные окружения для путей к файлам

## Структура файла

Пример структуры JSON файла Service Account:
```json
{
  "type": "service_account",
  "project_id": "your-project",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "your-service@your-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

Подробная инструкция по настройке: [GOOGLE_CALENDAR_SETUP.md](../GOOGLE_CALENDAR_SETUP.md)
