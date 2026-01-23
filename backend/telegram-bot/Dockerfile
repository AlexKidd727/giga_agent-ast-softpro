FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir \
    aiogram>=3.0.0 \
    langgraph-sdk>=0.0.20 \
    langchain-core>=0.3.0

# Копируем код приложения
COPY main.py ./
COPY pyproject.toml ./

# Открываем порт (не используется, но для консистентности)
EXPOSE 8080

# Запускаем бота
CMD ["python", "main.py"]
