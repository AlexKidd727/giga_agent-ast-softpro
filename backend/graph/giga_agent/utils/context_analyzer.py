"""
Анализатор размера контекста LLM

Модуль для отслеживания и анализа размера контекста, 
отправляемого в LLM, с разбивкой по компонентам.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import tiktoken

logger = logging.getLogger(__name__)

# Путь для сохранения статистики
STATS_DIR = os.environ.get("CONTEXT_STATS_DIR", "/tmp/context_stats")


@dataclass
class ContextComponent:
    """Компонент контекста с размером в токенах"""
    name: str
    tokens: int
    chars: int
    content_preview: str = ""  # Первые 200 символов
    

@dataclass 
class ContextAnalysis:
    """Результат анализа контекста"""
    timestamp: str
    user_query: str
    total_tokens: int
    total_chars: int
    components: List[ContextComponent] = field(default_factory=list)
    messages_count: int = 0
    tools_count: int = 0
    model_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "user_query": self.user_query,
            "total_tokens": self.total_tokens,
            "total_chars": self.total_chars,
            "components": [asdict(c) for c in self.components],
            "messages_count": self.messages_count,
            "tools_count": self.tools_count,
            "model_name": self.model_name,
        }


class ContextAnalyzer:
    """Анализатор размера контекста"""
    
    def __init__(self):
        # Используем tiktoken для подсчета токенов (cl100k_base - GPT-4/Claude compatible)
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = None
            logger.warning("tiktoken не доступен, используем приблизительный подсчет токенов")
        
        # Создаем директорию для статистики
        os.makedirs(STATS_DIR, exist_ok=True)
    
    def count_tokens(self, text: str) -> int:
        """Подсчет токенов в тексте"""
        if not text:
            return 0
        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception:
                pass
        # Fallback: приблизительно 4 символа на токен
        return len(text) // 4
    
    def analyze_message(self, msg: Any) -> ContextComponent:
        """Анализ одного сообщения"""
        msg_type = getattr(msg, 'type', 'unknown')
        content = ""
        
        if hasattr(msg, 'content'):
            content = str(msg.content) if msg.content else ""
        
        # Добавляем tool_calls если есть
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            content += f"\n[tool_calls: {len(msg.tool_calls)}]"
            for tc in msg.tool_calls:
                if isinstance(tc, dict):
                    content += f"\n  - {tc.get('name', 'unknown')}: {str(tc.get('args', {}))[:100]}"
        
        tokens = self.count_tokens(content)
        
        return ContextComponent(
            name=f"message_{msg_type}",
            tokens=tokens,
            chars=len(content),
            content_preview=content[:200] if content else ""
        )
    
    def analyze_context(
        self,
        messages: List[Any],
        system_prompt: str,
        user_instructions: str = "",
        rag_info: str = "",
        user_secrets: str = "",
        tools: List[Any] = None,
        model_name: str = "",
        user_query: str = ""
    ) -> ContextAnalysis:
        """
        Полный анализ контекста
        
        Args:
            messages: Список сообщений
            system_prompt: Системный промпт
            user_instructions: Пользовательские инструкции
            rag_info: RAG информация
            user_secrets: Секреты пользователя
            tools: Список инструментов
            model_name: Название модели
            user_query: Исходный запрос пользователя
        """
        components = []
        total_tokens = 0
        total_chars = 0
        
        # 1. Системный промпт
        sys_tokens = self.count_tokens(system_prompt)
        sys_chars = len(system_prompt)
        components.append(ContextComponent(
            name="system_prompt",
            tokens=sys_tokens,
            chars=sys_chars,
            content_preview=system_prompt[:200]
        ))
        total_tokens += sys_tokens
        total_chars += sys_chars
        
        # 2. Пользовательские инструкции
        if user_instructions:
            ui_tokens = self.count_tokens(user_instructions)
            ui_chars = len(user_instructions)
            components.append(ContextComponent(
                name="user_instructions",
                tokens=ui_tokens,
                chars=ui_chars,
                content_preview=user_instructions[:200]
            ))
            total_tokens += ui_tokens
            total_chars += ui_chars
        
        # 3. RAG информация
        if rag_info:
            rag_tokens = self.count_tokens(rag_info)
            rag_chars = len(rag_info)
            components.append(ContextComponent(
                name="rag_info",
                tokens=rag_tokens,
                chars=rag_chars,
                content_preview=rag_info[:200]
            ))
            total_tokens += rag_tokens
            total_chars += rag_chars
        
        # 4. Секреты пользователя
        if user_secrets:
            sec_tokens = self.count_tokens(user_secrets)
            sec_chars = len(user_secrets)
            components.append(ContextComponent(
                name="user_secrets",
                tokens=sec_tokens,
                chars=sec_chars,
                content_preview="[SECRETS HIDDEN]"
            ))
            total_tokens += sec_tokens
            total_chars += sec_chars
        
        # 5. Сообщения (группируем по типу)
        msg_by_type: Dict[str, List[ContextComponent]] = {}
        for msg in messages:
            comp = self.analyze_message(msg)
            msg_type = comp.name
            if msg_type not in msg_by_type:
                msg_by_type[msg_type] = []
            msg_by_type[msg_type].append(comp)
        
        # Суммируем по типам
        for msg_type, comps in msg_by_type.items():
            type_tokens = sum(c.tokens for c in comps)
            type_chars = sum(c.chars for c in comps)
            components.append(ContextComponent(
                name=f"messages_{msg_type}_x{len(comps)}",
                tokens=type_tokens,
                chars=type_chars,
                content_preview=f"{len(comps)} сообщений типа {msg_type}"
            ))
            total_tokens += type_tokens
            total_chars += type_chars
        
        # 6. Инструменты
        tools_count = 0
        if tools:
            tools_str = json.dumps(tools, ensure_ascii=False, default=str)
            tools_tokens = self.count_tokens(tools_str)
            tools_chars = len(tools_str)
            tools_count = len(tools)
            components.append(ContextComponent(
                name=f"tools_x{tools_count}",
                tokens=tools_tokens,
                chars=tools_chars,
                content_preview=f"{tools_count} инструментов: {[t.get('name', 'unknown') if isinstance(t, dict) else str(t)[:20] for t in tools[:5]]}"
            ))
            total_tokens += tools_tokens
            total_chars += tools_chars
        
        # Сортируем компоненты по размеру (от большего к меньшему)
        components.sort(key=lambda x: x.tokens, reverse=True)
        
        analysis = ContextAnalysis(
            timestamp=datetime.now().isoformat(),
            user_query=user_query[:100] if user_query else "",
            total_tokens=total_tokens,
            total_chars=total_chars,
            components=components,
            messages_count=len(messages),
            tools_count=tools_count,
            model_name=model_name
        )
        
        return analysis
    
    def log_analysis(self, analysis: ContextAnalysis):
        """Логирование анализа в консоль"""
        logger.info("=" * 60)
        logger.info(f"[CONTEXT_ANALYSIS] Query: {analysis.user_query}")
        logger.info(f"[CONTEXT_ANALYSIS] Total: {analysis.total_tokens} tokens, {analysis.total_chars} chars")
        logger.info(f"[CONTEXT_ANALYSIS] Messages: {analysis.messages_count}, Tools: {analysis.tools_count}")
        logger.info("-" * 60)
        
        for comp in analysis.components:
            pct = (comp.tokens / analysis.total_tokens * 100) if analysis.total_tokens > 0 else 0
            logger.info(f"[CONTEXT_ANALYSIS]   {comp.name}: {comp.tokens} tokens ({pct:.1f}%)")
        
        logger.info("=" * 60)
        
        # Также выводим в print для видимости в логах Docker
        print(f"\n{'='*60}")
        print(f"[CONTEXT] Query: {analysis.user_query}")
        print(f"[CONTEXT] TOTAL: {analysis.total_tokens} tokens ({analysis.total_chars} chars)")
        print(f"[CONTEXT] Messages: {analysis.messages_count}, Tools: {analysis.tools_count}")
        print(f"{'-'*60}")
        for comp in analysis.components:
            pct = (comp.tokens / analysis.total_tokens * 100) if analysis.total_tokens > 0 else 0
            print(f"[CONTEXT]   {comp.name}: {comp.tokens} tokens ({pct:.1f}%)")
        print(f"{'='*60}\n")
    
    def save_analysis(self, analysis: ContextAnalysis):
        """Сохранение анализа в файл"""
        try:
            filename = os.path.join(
                STATS_DIR, 
                f"context_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(analysis.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"[CONTEXT_ANALYSIS] Saved to {filename}")
        except Exception as e:
            logger.warning(f"[CONTEXT_ANALYSIS] Failed to save: {e}")
    
    def get_statistics(self, last_n: int = 10) -> Dict[str, Any]:
        """Получение статистики по последним N анализам"""
        try:
            files = sorted(
                [f for f in os.listdir(STATS_DIR) if f.startswith("context_")],
                reverse=True
            )[:last_n]
            
            analyses = []
            for f in files:
                with open(os.path.join(STATS_DIR, f), 'r', encoding='utf-8') as fp:
                    analyses.append(json.load(fp))
            
            if not analyses:
                return {"message": "No data available"}
            
            # Агрегированная статистика
            total_tokens_list = [a["total_tokens"] for a in analyses]
            
            # Статистика по компонентам
            component_stats: Dict[str, List[int]] = {}
            for a in analyses:
                for comp in a.get("components", []):
                    name = comp["name"].split("_x")[0]  # Убираем счетчик
                    if name not in component_stats:
                        component_stats[name] = []
                    component_stats[name].append(comp["tokens"])
            
            return {
                "count": len(analyses),
                "avg_tokens": sum(total_tokens_list) / len(total_tokens_list),
                "max_tokens": max(total_tokens_list),
                "min_tokens": min(total_tokens_list),
                "component_averages": {
                    k: sum(v) / len(v) for k, v in component_stats.items()
                },
                "recent_queries": [a["user_query"] for a in analyses[:5]]
            }
        except Exception as e:
            return {"error": str(e)}


# Глобальный экземпляр анализатора
_analyzer: Optional[ContextAnalyzer] = None


def get_context_analyzer() -> ContextAnalyzer:
    """Получение глобального анализатора"""
    global _analyzer
    if _analyzer is None:
        _analyzer = ContextAnalyzer()
    return _analyzer


def analyze_and_log_context(
    messages: List[Any],
    system_prompt: str,
    user_instructions: str = "",
    rag_info: str = "",
    user_secrets: str = "",
    tools: List[Any] = None,
    model_name: str = "",
    user_query: str = "",
    save: bool = True
) -> ContextAnalysis:
    """
    Удобная функция для анализа и логирования контекста
    
    Вызывать перед отправкой запроса в LLM для отслеживания размера контекста.
    """
    analyzer = get_context_analyzer()
    analysis = analyzer.analyze_context(
        messages=messages,
        system_prompt=system_prompt,
        user_instructions=user_instructions,
        rag_info=rag_info,
        user_secrets=user_secrets,
        tools=tools,
        model_name=model_name,
        user_query=user_query
    )
    
    # Логируем только если включен анализ (по умолчанию включен)
    if os.environ.get("CONTEXT_ANALYSIS_ENABLED", "1") == "1":
        analyzer.log_analysis(analysis)
        if save:
            analyzer.save_analysis(analysis)
    
    return analysis
