"""
Скрипт для проверки текущего провайдера и модели из Redis
"""
import os
import sys
import redis
from typing import Optional, Tuple

def get_agent_env(tag: str = None):
    """Получение ключа переменной окружения для модели"""
    if tag is None:
        return "GIGA_AGENT_LLM"
    else:
        return f"GIGA_AGENT_LLM_{tag.upper()}"

def parse_provider_model(llm_str: str) -> Tuple[str, str]:
    """Парсинг провайдера и модели из строки"""
    if not llm_str:
        return "unknown", ""
    
    if llm_str.startswith("openrouter:"):
        model = llm_str.replace("openrouter:", "")
        return "openrouter", model
    elif llm_str.startswith("deepseek:"):
        model = llm_str.replace("deepseek:", "")
        return "deepseek", model
    elif llm_str.startswith("openai:"):
        model = llm_str.replace("openai:", "")
        return "openai", model
    else:
        return "unknown", llm_str

def check_redis_provider(tag: Optional[str] = None) -> dict:
    """Проверка текущего провайдера и модели из Redis"""
    result = {
        "provider": "unknown",
        "model": "",
        "llm_str": "",
        "source": "not_found",
        "env_key": get_agent_env(tag),
        "redis_key": None
    }
    
    env_key = get_agent_env(tag)
    redis_key = f"provider:llm:{env_key}"
    
    try:
        redis_uri = os.getenv("REDIS_URI", "redis://localhost:6379")
        redis_client = redis.from_url(redis_uri, decode_responses=True)
        
        # Проверяем Redis
        saved_llm_str = redis_client.get(redis_key)
        if saved_llm_str:
            result["llm_str"] = saved_llm_str
            result["redis_key"] = redis_key
            result["source"] = "redis"
            provider, model = parse_provider_model(saved_llm_str)
            result["provider"] = provider
            result["model"] = model
            return result
        
        # Если в Redis нет, проверяем переменную окружения
        llm_str = os.getenv(env_key, "")
        if llm_str:
            result["llm_str"] = llm_str
            result["source"] = "environment"
            provider, model = parse_provider_model(llm_str)
            result["provider"] = provider
            result["model"] = model
            return result
        
        # Если ничего не найдено
        result["source"] = "not_found"
        return result
        
    except ImportError:
        result["error"] = "Redis библиотека не установлена"
        return result
    except Exception as e:
        result["error"] = str(e)
        return result

def main():
    """Основная функция"""
    print("=" * 60)
    print("Проверка текущего провайдера и модели")
    print("=" * 60)
    
    # Проверяем основную модель
    result = check_redis_provider(tag=None)
    
    print(f"\nОсновная модель (GIGA_AGENT_LLM):")
    print(f"  Провайдер: {result['provider']}")
    print(f"  Модель: {result['model']}")
    print(f"  Полная строка: {result['llm_str']}")
    print(f"  Источник: {result['source']}")
    if result.get('redis_key'):
        print(f"  Redis ключ: {result['redis_key']}")
    if result.get('error'):
        print(f"  Ошибка: {result['error']}")
    
    # Проверяем REPL модель
    result_repl = check_redis_provider(tag="repl")
    if result_repl['source'] != 'not_found':
        print(f"\nREPL модель (GIGA_AGENT_LLM_REPL):")
        print(f"  Провайдер: {result_repl['provider']}")
        print(f"  Модель: {result_repl['model']}")
        print(f"  Полная строка: {result_repl['llm_str']}")
        print(f"  Источник: {result_repl['source']}")
    
    print("\n" + "=" * 60)
    
    # Возвращаем код выхода
    if result.get('error'):
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
