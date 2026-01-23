"""
Агент для генерации проектов (кодер)
Адаптирован из lm_chat/coder_service.py
"""

from giga_agent.agents.coder_agent.graph import coder_agent, coder_plan, coder_generate, graph

__all__ = ["coder_agent", "coder_plan", "coder_generate", "graph"]

