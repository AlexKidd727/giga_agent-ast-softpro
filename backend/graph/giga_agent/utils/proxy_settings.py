"""
Единые настройки прокси для исходящих HTTP(S) запросов проекта.

Зачем:
- OpenAI / OpenRouter (через openai + httpx)
- Tavily / GetURL (внутри langchain_tavily / tavily)
- любые requests/httpx вызовы в инструментах

Используем существующие env-переменные проекта:
- AI_PROXY_HOST
- AI_PROXY_PORT (по умолчанию 8080)
- AI_PROXY_USERNAME (опционально)
- AI_PROXY_PASSWORD (опционально)

Примечание по безопасности:
- НИКОГДА не логируем пароль/полный URL с кредами.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


@dataclass(frozen=True)
class ProxyConfig:
    """Нормализованная конфигурация прокси."""

    scheme: str
    hostport: str
    username: Optional[str]
    password: Optional[str]

    def as_url(self, include_auth: bool = True) -> str:
        """Строит URL прокси. Если include_auth=False, креды не добавляются."""
        if include_auth and self.username and self.password:
            safe_username = quote(self.username, safe="")
            safe_password = quote(self.password, safe="")
            return f"{self.scheme}://{safe_username}:{safe_password}@{self.hostport}"
        return f"{self.scheme}://{self.hostport}"


def _normalize_hostport(host: str, default_port: str) -> str:
    host = (host or "").strip()
    if not host:
        return ""
    # Если порт уже указан (host:port) — оставляем как есть.
    if ":" in host:
        return host
    return f"{host}:{default_port}"


def load_proxy_config_from_env() -> Optional[ProxyConfig]:
    """
    Загружает прокси-конфиг из env.

    Возвращает None, если прокси не настроен.
    """
    host = os.getenv("AI_PROXY_HOST")
    if not host:
        return None

    port = os.getenv("AI_PROXY_PORT", "8080")
    username = os.getenv("AI_PROXY_USERNAME") or None
    password = os.getenv("AI_PROXY_PASSWORD") or None

    # Сейчас в проекте везде подразумевается HTTP-proxy.
    scheme = os.getenv("AI_PROXY_SCHEME", "http").strip() or "http"

    hostport = _normalize_hostport(host, port)
    if not hostport:
        return None

    return ProxyConfig(
        scheme=scheme,
        hostport=hostport,
        username=username,
        password=password,
    )


def apply_proxy_env_vars(override: bool = False) -> Optional[str]:
    """
    Применяет прокси к стандартным env-переменным, которые понимают requests/httpx и многие SDK.

    По умолчанию НЕ перезаписывает уже заданные HTTP_PROXY/HTTPS_PROXY.
    Возвращает "host:port" (без кредов) для безопасного логирования, либо None.
    """
    cfg = load_proxy_config_from_env()
    if not cfg:
        return None

    proxy_url = cfg.as_url(include_auth=True)

    # Примечание:
    # Многие библиотеки читают именно эти переменные. Поэтому ставим обе.
    if override or not os.getenv("HTTP_PROXY"):
        os.environ["HTTP_PROXY"] = proxy_url
    if override or not os.getenv("HTTPS_PROXY"):
        os.environ["HTTPS_PROXY"] = proxy_url

    # ALL_PROXY используется некоторыми клиентами/утилитами; ставим только если пусто.
    if override or not os.getenv("ALL_PROXY"):
        os.environ["ALL_PROXY"] = proxy_url

    return cfg.hostport


def get_proxy_url_for_http_clients() -> Optional[str]:
    """
    Возвращает URL прокси (с кредами при наличии) для явной передачи в httpx/requests.
    """
    cfg = load_proxy_config_from_env()
    if not cfg:
        return None
    return cfg.as_url(include_auth=True)

