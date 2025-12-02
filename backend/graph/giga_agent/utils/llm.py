import asyncio
import os
from typing import Dict, Optional, Literal
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from gigachat.exceptions import ResponseError
from langchain_gigachat import GigaChat, GigaChatEmbeddings

from giga_agent.utils.env import load_project_env
from giga_agent.utils.types import FileTypes

GIGACHAT_PROVIDER = "gigachat:"

load_project_env()


def get_agent_env(tag: str = None):
    if tag is None:
        return "GIGA_AGENT_LLM"
    else:
        return f"GIGA_AGENT_LLM_{tag.upper()}"


def load_gigachat(tag: str = None, is_main: bool = False):
    llm_str = os.getenv(get_agent_env(tag))
    kwargs = {}
    if is_main:
        kwargs = dict(
            timeout=os.getenv("MAIN_GIGACHAT_TIMEOUT", 70),
            user=os.getenv("MAIN_GIGACHAT_USER"),
            password=os.getenv("MAIN_GIGACHAT_PASSWORD"),
            credentials=os.getenv("MAIN_GIGACHAT_CREDENTIALS"),
            scope=os.getenv("MAIN_GIGACHAT_SCOPE"),
            base_url=os.getenv("MAIN_GIGACHAT_BASE_URL"),
            top_p=os.getenv("MAIN_GIGACHAT_TOP_P", 0.5),
            verbose=os.getenv("MAIN_GIGACHAT_VERBOSE", "False"),
        )
    return GigaChat(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
        profanity_check=False,
        verify_ssl_certs=False,
        max_tokens=1280000,
        **kwargs,
    )


def load_gigachat_embeddings():
    llm_str = os.getenv("GIGA_AGENT_EMBEDDINGS")
    return GigaChatEmbeddings(
        model=llm_str[len(GIGACHAT_PROVIDER) :],
    )


def is_llm_gigachat(tag: str = None):
    llm_str = os.getenv(get_agent_env(tag))
    return llm_str.startswith(GIGACHAT_PROVIDER)


# Singletons cache
_LLM_SINGLETONS: Dict[str, object] = {}
_EMBEDDINGS_SINGLETON: Optional[object] = None


def load_llm(tag: str = None, is_main: bool = False):
    env_key = get_agent_env(tag)
    # TODO: Поправить логику загрузки LLM кредов (сейчас это вообще что-то страшное)
    singleton_key = env_key
    if is_main:
        singleton_key = "MAIN_" + singleton_key
    if singleton_key in _LLM_SINGLETONS:
        return _LLM_SINGLETONS[singleton_key]

    llm_str = os.getenv(env_key)
    if llm_str is None:
        raise RuntimeError(f"{env_key} is empty! Fill it with your model")

    if llm_str.startswith(GIGACHAT_PROVIDER):
        llm = load_gigachat(tag=tag, is_main=is_main)
    else:
        # Для DeepSeek моделей пытаемся включить reasoning mode через параметры
        # Если модель содержит "deepseek", добавляем параметры для reasoning
        if "deepseek" in llm_str.lower():
            try:
                # Пробуем инициализировать с параметрами reasoning
                # langchain-deepseek может поддерживать параметр reasoning_mode или similar
                llm = init_chat_model(
                    llm_str,
                    # Если API поддерживает, можно добавить параметры:
                    # model_kwargs={"reasoning_mode": True} или другие параметры
                )
            except Exception as e:
                # Если не получилось с параметрами, используем стандартную инициализацию
                print(f"⚠️  Не удалось инициализировать DeepSeek с reasoning параметрами: {e}")
                llm = init_chat_model(llm_str)
        else:
            llm = init_chat_model(llm_str)

    _LLM_SINGLETONS[singleton_key] = llm
    return llm


def load_embeddings():
    global _EMBEDDINGS_SINGLETON

    if _EMBEDDINGS_SINGLETON is not None:
        return _EMBEDDINGS_SINGLETON

    emb_str = os.getenv("GIGA_AGENT_EMBEDDINGS")
    if emb_str is None:
        raise RuntimeError("GIGA_AGENT_EMBEDDINGS is empty! Fill it with your model")

    if emb_str.startswith(GIGACHAT_PROVIDER):
        embeddings = load_gigachat_embeddings()
    else:
        embeddings = init_embeddings(emb_str)

    _EMBEDDINGS_SINGLETON = embeddings
    return embeddings


def is_llm_image_inline():
    llm_str = os.getenv("GIGA_AGENT_LLM")
    if llm_str is None:
        raise RuntimeError("GIGA_AGENT_LLM is empty! Fill it with your model")
    return llm_str.startswith(GIGACHAT_PROVIDER)


async def upload_file_with_retry(
    file: FileTypes, purpose: Literal["general", "assistant"] = "general", retries=3
):
    llm = load_llm()
    retry = 0
    while retry < retries:
        try:
            file = await llm.aupload_file(file, purpose)
            return file.id_
        except ResponseError as e:
            if e.args[1] != 504:
                raise e
            else:
                retry += 1
            await asyncio.sleep(0.5)
