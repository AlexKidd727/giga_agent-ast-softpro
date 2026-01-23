FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости для Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir \
    websockets>=12.0 \
    playwright>=1.40.0 \
    aiohttp>=3.9.0

# Устанавливаем браузеры Playwright
RUN playwright install chromium && \
    playwright install-deps chromium

# Копируем код приложения
COPY main.py ./

# Создаем директорию для временных файлов
RUN mkdir -p /tmp

# Открываем порт
EXPOSE 7070

# Запускаем сервис
CMD ["python", "main.py"]

