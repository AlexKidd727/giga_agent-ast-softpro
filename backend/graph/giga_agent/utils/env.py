import os
from pathlib import Path
from dotenv import load_dotenv


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
        _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
        return

    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        candidate = p / filename
        if candidate.is_file():
            load_dotenv(candidate, override=override)
            _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
            return

    # Mark as attempted even if no file found to avoid repeated costly scans
    _ENV_ALREADY_LOADED = True  # type: ignore[assignment]
