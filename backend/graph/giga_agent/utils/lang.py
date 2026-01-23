import os

from giga_agent.utils.env import load_project_env

load_project_env()

LANG = os.getenv("GIGA_AGENT_LANG", "ru-ru")
