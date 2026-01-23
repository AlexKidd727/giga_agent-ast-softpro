## GitHub: создание репозитория и публикация проекта

Модель: **GPT-5.2** — использована как основной агент для аккуратного расширения существующего Python-инструмента в стиле проекта и с проверками безопасности.

### Что добавлено

- `create_github_repository`: создаёт репозиторий (в аккаунте или организации)
- `publish_project_to_github`: публикует проект из `FILES_DIR/projects/<project_id>/` в репозиторий

### Требования

- Нужен GitHub токен с правами:
  - **repo** (для приватных репозиториев) или **public_repo** (для публичных)
  - если создаёте репозиторий в org — нужны права создавать репозитории в организации
- Токен берётся:
  - из БД пользователя (предпочтительно), либо
  - из env `GITHUB_PERSONAL_ACCESS_TOKEN`

### Пример сценария

1) Сгенерировать проект через `coder_generate`, получить `project_id`.
2) Создать репозиторий в личном аккаунте:
   - `create_github_repository(repo_name="my-new-repo", private=true)`
3) Опубликовать fullstack проект в репозиторий:
   - `publish_project_to_github(owner="my-login", repo="my-new-repo", project_id="<project_id>")`
4) Если хотите «всё в один шаг», можно так:
   - `publish_project_to_github(owner="my-login", repo="my-new-repo", project_id="<project_id>", create_repo_if_missing=true, make_private=true)`

### Как именно публикуется

Инструмент сначала пытается использовать `git` (если доступен в окружении), иначе переключается на GitHub Contents API.

#### Защита от утечек

По умолчанию не загружаются:
- `.env`, `.env.*`
- `credentials/`
- `.git/`, `node_modules/`, `dist/`, `build/`, `__pycache__/` и прочие кэши
- `*.bak*`

Если нужно — можно передать дополнительные исключения через `ignore_globs`.


