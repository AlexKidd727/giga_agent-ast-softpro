FROM python:3.11-slim

WORKDIR /app

# Устанавливаем psycopg2 для работы с PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем только необходимые зависимости для миграций
RUN pip install --no-cache-dir \
    sqlalchemy>=2.0.0 \
    psycopg2-binary>=2.9.0

# Копируем скрипт миграции
COPY migrations/migrate.py /app/migrate.py

# Делаем скрипт исполняемым
RUN chmod +x /app/migrate.py

# Команда по умолчанию - выполнение миграций
CMD ["python", "/app/migrate.py"]

