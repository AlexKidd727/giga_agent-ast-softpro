import os
from pathlib import Path
from dotenv import load_dotenv

from giga_agent.utils.proxy_settings import apply_proxy_env_vars


def load_project_env(filename: str = ".env", override: bool = False) -> None:
    # Ensure env loading happens only once per process unless explicitly overridden
    global _ENV_ALREADY_LOADED  # type: ignore[var-annotated]
    try:
        already_loaded = _ENV_ALREADY_LOADED  # type: ignore[name-defined]
    except NameError:
        already_loaded = False

    if already_loaded and not override:
        return

    explicit = os.getenv("ENV_PATH")
    if explicit and Path(explicit).is_file():
        load_dotenv(explicit, override=override)
        # ВАЖНО (proxy policy):
        # Прокси должен использоваться ТОЛЬКО точечно (GetUrl и OpenAI/OpenRouter),
        # а не глобально через HTTP_PROXY/HTTPS_PROXY.
        # Поэтому по умолчанию НЕ выставляем HTTP(S)_PROXY/ALL_PROXY автоматически.
        # Если нужно старое поведение (глобальный прокси) — включите флаг:
        #   AI_PROXY_APPLY_GLOBAL=1
        if os.getenv("AI_PROXY_APPLY_GLOBAL", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
            apply_proxy_env_vars(override=False)
        _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
        return

    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        candidate = p / filename
        if candidate.is_file():
            load_dotenv(candidate, override=override)
            # ВАЖНО (proxy policy): см. блок выше.
            if os.getenv("AI_PROXY_APPLY_GLOBAL", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
                apply_proxy_env_vars(override=False)
            _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
            return

    # Mark as attempted even if no file found to avoid repeated costly scans
    # Примечание: даже если файл env не найден, могли быть заданы переменные окружения напрямую.
    # Поэтому всё равно можно применить настройки прокси, но только если это явно включено.
    if os.getenv("AI_PROXY_APPLY_GLOBAL", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        apply_proxy_env_vars(override=False)
    _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
