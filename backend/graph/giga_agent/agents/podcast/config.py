from typing import TypedDict, List, Union, Literal

from langchain_core.messages import AnyMessage

from giga_agent.agents.podcast.schema import ShortDialogue, MediumDialogue
from giga_agent.utils.llm import load_llm
from giga_agent.utils.types import UploadedFile

podcast_llm = load_llm().with_config(tags=["nostream"])


class ConfigSchema(TypedDict):
    save_files: bool


class PodcastState(TypedDict):
    messages: List[AnyMessage]
    use_messages: bool
    url: str
    podcast_text: str
    dialogue: Union[ShortDialogue, MediumDialogue]
    question: str
    tone: Literal["entertaining", "formal"]
    length: Literal["short", "medium"]
    audio: UploadedFile
    transcript: str
