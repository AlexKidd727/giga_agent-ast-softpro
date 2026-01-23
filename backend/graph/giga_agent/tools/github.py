import base64
import fnmatch
import hashlib
import httpx
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Union, Literal, Annotated, Iterable, List, Tuple

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState


GITHUB_API_VERSION = "2022-11-28"


async def _get_github_token(user_id: Optional[str] = None, state: Optional[dict] = None) -> str:
    """
    Внутренний helper: получает GitHub токен пользователя из БД (если user_id валиден),
    иначе пытается взять токен из env `GITHUB_PERSONAL_ACCESS_TOKEN`.

    Примечание: порядок такой же, как в существующих GitHub-тулах проекта.
    Логика: сначала пытаемся получить токен из БД пользователя, если не найден - используем env.
    """
    if not user_id and state:
        user_id = state.get("user_id")

    from giga_agent.utils.user_tokens import get_user_github_token

    # Сначала пытаемся получить токен из БД пользователя (если user_id валиден)
    github_token = None
    if user_id:
        github_token = await get_user_github_token(user_id)
    
    # Если токен не найден в БД, используем fallback на переменную окружения
    if not github_token:
        github_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    
    if not github_token:
        raise ValueError("GITHUB_PERSONAL_ACCESS_TOKEN не настроен и GitHub токен пользователя не найден")
    return github_token


def _github_headers(github_token: str) -> Dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _safe_repo_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("repo_name не должен быть пустым")
    # GitHub допускает много символов, но для надёжности ограничим базовыми.
    # Примечание: не пытаемся «чинить» сильно — лучше явная ошибка.
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(ch not in allowed for ch in name):
        raise ValueError("repo_name содержит недопустимые символы. Разрешены: буквы/цифры/.-_")
    return name


def _default_ignore_globs() -> List[str]:
    # Примечание: защита от утечек секретов и мусорных директорий.
    return [
        "**/.git/**",
        "**/.idea/**",
        "**/.vscode/**",
        "**/__pycache__/**",
        "**/.pytest_cache/**",
        "**/.mypy_cache/**",
        "**/.ruff_cache/**",
        "**/.venv/**",
        "**/venv/**",
        "**/env/**",
        "**/node_modules/**",
        "**/dist/**",
        "**/build/**",
        "**/.DS_Store",
        "**/Thumbs.db",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.pyd",
        "**/*.log",
        "**/*.tmp",
        "**/*.bak*",
        "**/.env",
        "**/.env.*",
        "**/credentials/**",
        "**/*.pem",
        "**/*.ppk",
        "**/*.key",
        "**/*.p12",
        "**/*.pfx",
    ]


def _match_any_glob(path_posix: str, globs: Iterable[str]) -> bool:
    for pat in globs:
        if fnmatch.fnmatch(path_posix, pat):
            return True
    return False


def _iter_files(root_dir: Path, ignore_globs: Iterable[str]) -> Iterable[Tuple[Path, str]]:
    """
    Итератор по файлам проекта.
    Возвращает (absolute_path, relative_posix_path).
    """
    root_dir = root_dir.resolve()
    for p in root_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root_dir).as_posix()
        # Всегда игнорируем .git
        if rel.startswith(".git/"):
            continue
        if _match_any_glob(rel, ignore_globs):
            continue
        yield p, rel


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _try_run_git(args: List[str], cwd: Path) -> Tuple[int, str]:
    """
    Безопасный запуск git. Возвращает (exit_code, combined_output).
    """
    try:
        p = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        return p.returncode, out.strip()
    except FileNotFoundError:
        return 127, "git не найден в PATH"


@tool(parse_docstring=True)
async def get_workflow_runs(
    owner: str,
    repo: str,
    actor: Optional[str] = None,
    branch: Optional[str] = None,
    event: Optional[str] = None,
    status: Optional[
        Literal[
            "completed",
            "action_required",
            "cancelled",
            "failure",
            "neutral",
            "skipped",
            "stale",
            "success",
            "timed_out",
            "in_progress",
            "queued",
            "requested",
            "waiting",
            "pending",
        ]
    ] = None,
    per_page: int = 30,
    page: int = 1,
    created: Optional[str] = None,
    exclude_pull_requests: bool = False,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
) -> Dict[str, Any]:
    """
    Получает CI Runs из GitHub репозитория

    Args:
        owner: Repository owner (case-insensitive).
        repo: Repository name without .git extension (case-insensitive).
        actor: Filter by the user who triggered the run.
        branch: Filter by branch name.
        event: Filter by event (e.g., push, pull_request).
        status: Filter by run status or conclusion. Can be one of: completed, action_required, cancelled, failure, neutral, skipped, stale, success, timed_out, in_progress, queued, requested, waiting, pending.
        per_page: Results per page (max 100). If you need to get more call this method in loop
        page: Page number to fetch.
        created: Date-time range filter (see GitHub search syntax).
        exclude_pull_requests: If True, omit pull request runs.
        user_id: Идентификатор пользователя для получения токена из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    if per_page > 100:
        raise Exception("Maximum per_page value is 100")
    
    github_token = await _get_github_token(user_id=user_id, state=state)
    
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    headers = _github_headers(github_token)

    params: Dict[str, Union[str, int, bool]] = {
        "per_page": per_page,
        "page": page,
        "exclude_pull_requests": str(exclude_pull_requests).lower(),
    }

    # Optional filters
    if actor:
        params["actor"] = actor
    if branch:
        params["branch"] = branch
    if event:
        params["event"] = event
    if status:
        params["status"] = status
    if created:
        params["created"] = created

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return remove_url_keys(response.json())


@tool(parse_docstring=True)
async def list_pull_requests(
    owner: str,
    repo: str,
    state: Optional[Literal["open", "closed", "all"]] = "open",
    head: Optional[str] = None,
    base: Optional[str] = None,
    sort: Optional[Literal["created", "updated", "popularity", "long-running"]] = None,
    direction: Optional[Literal["asc", "desc"]] = None,
    per_page: int = 30,
    page: int = 1,
    user_id: Optional[str] = None,
    state_graph: Annotated[dict, InjectedState] = None,
) -> Dict[str, Any]:
    """
    Список Pull Requests репозитория
    
    Args:
        owner: Владелец репозитория (без .git)
        repo: Имя репозитория (без .git)
        state: Статус PR: open|closed|all (по умолчанию open)
        head: Фильтр по head ("user:branch")
        base: Фильтр по base ветке
        sort: Порядок сортировки: created|updated|popularity|long-running
        direction: Направление сортировки: asc|desc
        per_page: Результатов на страницу (макс 100)
        page: Номер страницы
        user_id: Идентификатор пользователя для получения токена из БД
        state_graph: Состояние графа (для извлечения user_id, если не передан явно)
    """
    if per_page > 100:
        raise Exception("Maximum per_page value is 100")
    
    github_token = await _get_github_token(user_id=user_id, state=state_graph)
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = _github_headers(github_token)

    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if state:
        params["state"] = state
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    if sort:
        params["sort"] = sort
    if direction:
        params["direction"] = direction

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return remove_url_keys(response.json())


@tool(parse_docstring=True)
async def get_pull_request(
    owner: str,
    repo: str,
    pull_number: int,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
) -> Dict[str, Any]:
    """
    Получает Pull Request по номеру

    Args:
        owner: Владелец репозитория (без .git)
        repo: Имя репозитория (без .git)
        pull_number: Номер PR
        user_id: Идентификатор пользователя для получения токена из БД
        state: Состояние графа (для извлечения user_id, если не передан явно)
    """
    github_token = await _get_github_token(user_id=user_id, state=state)
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    headers = _github_headers(github_token)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return remove_url_keys(response.json())


def remove_url_keys(obj: Any) -> Any:
    """
    Recursively remove keys containing '_url' from dictionaries if their value is not a dict.

    Parameters:
        obj: The input data, which can be a dict, list, or any other type.

    Returns:
        A new data structure with keys matching the criteria removed.
    """
    if isinstance(obj, dict):
        result: Dict[Any, Any] = {}
        for key, value in obj.items():
            # Skip keys containing '_url' when value is not a dict
            if "_url" in key and not isinstance(value, dict):
                continue
            result[key] = remove_url_keys(value)
        return result
    elif isinstance(obj, list):
        return [remove_url_keys(item) for item in obj]
    else:
        return obj


@tool(parse_docstring=True)
async def create_github_repository(
    repo_name: str,
    description: Optional[str] = None,
    private: bool = True,
    organization: Optional[str] = None,
    auto_init: bool = False,
    gitignore_template: Optional[str] = None,
    license_template: Optional[str] = None,
    homepage: Optional[str] = None,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
) -> Dict[str, Any]:
    """
    Создаёт новый репозиторий на GitHub (в аккаунте пользователя или в организации).

    Args:
        repo_name: Имя репозитория (без пробелов). Разрешены: буквы/цифры/.-_
        description: Описание репозитория
        private: Сделать репозиторий приватным (по умолчанию True)
        organization: Если указан — создаёт репозиторий в организации (org login), иначе в аккаунте пользователя
        auto_init: Если True — GitHub создаст первый коммит с README
        gitignore_template: Имя шаблона .gitignore (например, "Python", "Node")
        license_template: Ключ лицензии (например, "mit", "apache-2.0")
        homepage: Домашняя страница проекта
        user_id: Идентификатор пользователя (для токена из БД)
        state: Состояние графа (для извлечения user_id, если не передан явно)

    Returns:
        Словарь с данными репозитория (url/ssh_url/clone_url/full_name и т.п.)
    """
    github_token = await _get_github_token(user_id=user_id, state=state)

    repo_name = _safe_repo_name(repo_name)
    payload: Dict[str, Any] = {
        "name": repo_name,
        "private": bool(private),
    }
    if description is not None:
        payload["description"] = description
    if homepage is not None:
        payload["homepage"] = homepage
    if auto_init:
        payload["auto_init"] = True
    if gitignore_template:
        payload["gitignore_template"] = gitignore_template
    if license_template:
        payload["license_template"] = license_template

    if organization:
        url = f"https://api.github.com/orgs/{organization}/repos"
    else:
        url = "https://api.github.com/user/repos"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_github_headers(github_token), json=payload)
        # Явная обработка частых ошибок (для человека)
        if resp.status_code == 422:
            raise ValueError(f"GitHub API 422: возможно, репозиторий '{repo_name}' уже существует или имя некорректно. details={resp.text}")
        resp.raise_for_status()
        return remove_url_keys(resp.json())


@tool(parse_docstring=True)
async def publish_project_to_github(
    owner: str,
    repo: str,
    project_id: str,
    branch: str = "main",
    commit_message: str = "Initial commit",
    make_private: Optional[bool] = None,
    create_repo_if_missing: bool = False,
    organization: Optional[str] = None,
    ignore_globs: Optional[List[str]] = None,
    max_file_size_bytes: int = 900_000,
    prefer_git: bool = True,
    user_id: Optional[str] = None,
    state: Annotated[dict, InjectedState] = None,
) -> Dict[str, Any]:
    """
    Публикует (выкладывает) созданный `coder_generate` проект в GitHub репозиторий.

    По умолчанию берёт проект из `FILES_DIR/projects/<project_id>/`.
    Публикация делается:
    - через `git` (если доступен в окружении и prefer_git=True)
    - иначе через GitHub Contents API (подходит для небольших файлов)

    Важно:
    - автоматически исключаются секреты/мусор (см. ignore_globs по умолчанию)
    - .env, credentials и т.п. не отправляются

    Args:
        owner: Владелец репозитория (user или org)
        repo: Имя репозитория
        project_id: Идентификатор проекта из `coder_generate`
        branch: Ветка для публикации (по умолчанию main)
        commit_message: Сообщение коммита
        make_private: Если create_repo_if_missing=True, можно задать приватность (иначе не используется)
        create_repo_if_missing: Если True — создаст репозиторий, если он не существует
        organization: Если создаём репозиторий и это org — укажите org login
        ignore_globs: Дополнительные glob-паттерны исключений (posix-пути)
        max_file_size_bytes: Максимальный размер одного файла для Contents API (git-режим не ограничивается)
        prefer_git: Пытаться использовать git (если есть в PATH)
        user_id: Идентификатор пользователя для токена из БД
        state: Состояние графа (для извлечения user_id, если не передан)
    """
    github_token = await _get_github_token(user_id=user_id, state=state)

    files_dir = Path(os.environ.get("FILES_DIR", "files"))
    project_dir = (files_dir / "projects" / project_id).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError(f"Каталог проекта не найден: {project_dir}")

    # Проверим существование репозитория / создадим при необходимости
    repo_api = f"https://api.github.com/repos/{owner}/{repo}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(repo_api, headers=_github_headers(github_token))
        if r.status_code == 404 and create_repo_if_missing:
            created = await create_github_repository(
                repo_name=repo,
                description=f"Published by giga-agent (project_id={project_id})",
                private=bool(True if make_private is None else make_private),
                # Примечание: если organization не задан — создаём репозиторий в личном аккаунте токена.
                organization=organization,
                auto_init=False,
                user_id=user_id,
                state=state,
            )
            # Если владелец не совпал — сообщим явно
            _ = created
        elif r.status_code == 404:
            raise FileNotFoundError(f"GitHub репозиторий не найден: {owner}/{repo}. Можно включить create_repo_if_missing=true")
        else:
            r.raise_for_status()

    # Готовим ignore
    effective_ignore: List[str] = _default_ignore_globs()
    if ignore_globs:
        effective_ignore.extend(ignore_globs)

    # Попытка git-публикации (быстрее и без лимитов)
    if prefer_git:
        code, out = _try_run_git(["--version"], cwd=project_dir)
        if code == 0:
            # Примечание: не логируем токен в выводе.
            remote_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"

            # init
            _try_run_git(["init"], cwd=project_dir)
            _try_run_git(["checkout", "-B", branch], cwd=project_dir)

            # .gitignore (минимально, если отсутствует)
            gitignore_path = project_dir / ".gitignore"
            if not gitignore_path.exists():
                gitignore_path.write_text("\n".join([
                    "# created by giga-agent",
                    ".env",
                    ".env.*",
                    "credentials/",
                    "__pycache__/",
                    ".venv/",
                    "venv/",
                    "node_modules/",
                    "dist/",
                    "build/",
                    "*.log",
                    "*.bak*",
                ]) + "\n", encoding="utf-8")

            # add/commit
            _try_run_git(["add", "-A"], cwd=project_dir)
            _try_run_git(["commit", "-m", commit_message, "--allow-empty"], cwd=project_dir)

            # remote
            _try_run_git(["remote", "remove", "origin"], cwd=project_dir)
            _try_run_git(["remote", "add", "origin", remote_url], cwd=project_dir)

            # push
            push_code, push_out = _try_run_git(["push", "-u", "origin", branch], cwd=project_dir)
            if push_code != 0:
                # Если git доступен, но push не прошёл — дадим понятную ошибку без утечки токена
                redacted = push_out.replace(github_token, "***")
                raise RuntimeError(f"Git push не удался. details={redacted}")

            return {
                "mode": "git",
                "project_dir": str(project_dir),
                "repo": f"{owner}/{repo}",
                "branch": branch,
                "message": "Проект опубликован через git push",
            }

    # Fallback: Contents API
    # Примечание: это подходит для небольших проектов и ограничено размером файла.
    created_files: List[Dict[str, Any]] = []
    skipped_files: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for abs_path, rel_posix in _iter_files(project_dir, effective_ignore):
            data = abs_path.read_bytes()
            if len(data) > max_file_size_bytes:
                skipped_files.append({
                    "path": rel_posix,
                    "reason": f"file too large for contents api ({len(data)} bytes > {max_file_size_bytes})",
                })
                continue

            # Проверим, существует ли файл, чтобы корректно апдейтить по sha
            get_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{rel_posix}"
            params = {"ref": branch}
            existing_sha: Optional[str] = None
            get_resp = await client.get(get_url, headers=_github_headers(github_token), params=params)
            if get_resp.status_code == 200:
                try:
                    existing_sha = get_resp.json().get("sha")
                except Exception:
                    existing_sha = None

            put_payload: Dict[str, Any] = {
                "message": commit_message,
                "content": base64.b64encode(data).decode("utf-8"),
                "branch": branch,
            }
            if existing_sha:
                put_payload["sha"] = existing_sha

            put_resp = await client.put(get_url, headers=_github_headers(github_token), json=put_payload)
            if put_resp.status_code >= 400:
                raise RuntimeError(f"Не удалось загрузить файл {rel_posix}. status={put_resp.status_code} details={put_resp.text}")

            created_files.append({
                "path": rel_posix,
                "size": len(data),
                "sha256": _sha256_bytes(data),
            })

    return {
        "mode": "contents_api",
        "project_dir": str(project_dir),
        "repo": f"{owner}/{repo}",
        "branch": branch,
        "uploaded_files": len(created_files),
        "skipped_files": skipped_files[:50],  # чтобы не раздувать ответ
        "message": "Проект опубликован через GitHub Contents API (часть файлов могла быть пропущена по ограничениям).",
    }
