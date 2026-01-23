FROM mikelarg/aegra:0.0.7

USER root

# КРИТИЧЕСКИ ВАЖНО: Создаем constraints.txt с нужной версией protobuf СРАЗУ после начала сборки
# Базовый образ использует команду: uv pip install -c /api/constraints.txt -e /deps/*
# Нам нужно переопределить protobuf ДО того, как базовый образ попытается установить зависимости
RUN mkdir -p /api && \
    if [ -f /api/constraints.txt ]; then \
        grep -v "^protobuf" /api/constraints.txt > /tmp/constraints_no_proto.txt 2>/dev/null || true && \
        echo "protobuf>=4.25.1,<5.0.0" >> /tmp/constraints_no_proto.txt && \
        mv /tmp/constraints_no_proto.txt /api/constraints.txt; \
    else \
        echo "protobuf>=4.25.1,<5.0.0" > /api/constraints.txt; \
    fi

RUN apt-get update && apt-get install -y ffmpeg libavcodec-extra

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git

RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
RUN apt-get install -y nodejs
RUN npm install -g npm@latest

WORKDIR /

COPY ./pyproject.toml /pyproject.toml
COPY ./README.md /README.md
COPY ./constraints.txt /local-constraints.txt

# Создаем constraints.txt в /deps/graph до того, как базовый образ попытается его использовать
# Базовый образ использует команду: uv pip install -c /api/constraints.txt -e /deps/*
# Но мы создаем constraints.txt в /deps/graph, чтобы он был доступен при установке
RUN mkdir -p /deps/graph && cp /local-constraints.txt /deps/graph/constraints.txt

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is available to all users
RUN mv /root/.local/bin/uv /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

RUN uv venv --system-site-packages

# Устанавливаем protobuf нужной версии ДО установки зависимостей из pyproject.toml
# Это необходимо для совместимости с t-tech-investments, который требует protobuf<5.0.0
# Базовый образ использует constraints.txt с protobuf>=6.32.1, но мы устанавливаем protobuf<5.0.0 заранее
RUN uv pip install --system "protobuf>=4.25.1,<5.0.0"

# Заменяем системный constraints.txt нашим, чтобы переопределить protobuf при установке зависимостей
# Это необходимо, так как базовый образ может использовать constraints.txt при установке
RUN mkdir -p /api && \
    if [ -f /api/constraints.txt ]; then \
        cp /api/constraints.txt /api/constraints.txt.backup && \
        sed 's/protobuf>=6\.32\.1,<7\.0\.0/protobuf>=4.25.1,<5.0.0/g' /api/constraints.txt.backup > /api/constraints.txt 2>/dev/null || \
        cp /local-constraints.txt /api/constraints.txt; \
    else \
        cp /local-constraints.txt /api/constraints.txt; \
    fi

# Создаем lockfile если его нет, затем синхронизируем зависимости
# uv sync автоматически создаст lockfile при первом запуске
# Благодаря конфигурации [tool.uv.index] и [tool.uv.sources] в pyproject.toml,
# uv sync будет использовать CPU-only версию torch из индекса PyTorch
# Это предотвратит загрузку CUDA зависимостей (nvidia-cuda-nvrtc-cu12, nvidia-cudnn-cu12 и т.д.)
RUN --mount=type=cache,target=/root/.cache/uv uv sync --prerelease=allow

# Переустанавливаем CPU-only версию torch после uv sync на случай, если что-то пошло не так
# Это гарантирует, что используется CPU-only версия без CUDA зависимостей
RUN uv pip uninstall --system torch torchvision torchaudio || true && \
    uv pip install --system --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0,<3.0.0" || \
    uv pip install --system "torch>=2.0.0,<3.0.0" --extra-index-url https://download.pytorch.org/whl/cpu || \
    echo "CPU-only torch install failed; will use dependency version"

# Устанавливаем SDK T-Инвестиций отдельно.
# ВАЖНО:
# - Пакет `t-tech-investments` может быть недоступен в публичном индексе,
#   поэтому делаем fallback на официальный репозиторий invest-python (предоставляет `tinkoff.invest`).
# - Не используем эмоджи в выводе (требование проекта).
RUN uv pip install --system "t-tech-investments" \
    || (echo "t-tech-investments install failed; trying invest-python (tinkoff-investments) from GitHub" && \
        mkdir -p /tmp/tinkoff_meta && \
        printf '%s\n' \
          '[build-system]' \
          'requires = ["setuptools>=68", "wheel"]' \
          'build-backend = "setuptools.build_meta"' \
          > /tmp/tinkoff_meta/pyproject.toml && \
        printf '%s\n' \
          'from setuptools import setup' \
          'setup(name="tinkoff", version="0.1.1")' \
          > /tmp/tinkoff_meta/setup.py && \
        uv pip install --system /tmp/tinkoff_meta && \
        uv pip install --system "tinkoff-investments @ git+https://github.com/Tinkoff/invest-python.git") \
    || echo "Tinkoff SDK install failed"

# Устанавливаем библиотеки для чтения документов (PDF, DOCX, DOC, RTF, TXT, XLS, XLSX)
RUN uv pip install --system "python-docx>=1.2.0" "PyPDF2>=3.0.0" "striprtf>=0.0.26" "openpyxl>=3.1.0" "xlrd>=2.0.1"

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY ./giga_agent ./giga_agent
COPY ./langgraph.json ./aegra.json

# Создаем директорию для credentials (файлы будут монтироваться через volume)
RUN mkdir -p /app/credentials