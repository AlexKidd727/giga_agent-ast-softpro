from typing import IO, Mapping, Optional, Tuple, Union, TypedDict, Literal

FileContent = Union[IO[bytes], bytes, str]
FileTypes = Union[
    # file (or bytes)
    FileContent,
    # (filename, file (or bytes))
    Tuple[Optional[str], FileContent],
    # (filename, file (or bytes), content_type)
    Tuple[Optional[str], FileContent, Optional[str]],
    # (filename, file (or bytes), content_type, headers)
    Tuple[Optional[str], FileContent, Optional[str], Mapping[str, str]],
]

UploadedFileType = Literal["image", "plotly_graph", "html", "text", "audio", "other"]


class UploadedFile(TypedDict):
    path: str
    size: int
    file_type: UploadedFileType
    image_id: Optional[str]
    image_path: Optional[str]


class CollectionMetadata(TypedDict):
    description: str


class Collection(TypedDict):
    name: str
    uuid: str
    metadata: CollectionMetadata
