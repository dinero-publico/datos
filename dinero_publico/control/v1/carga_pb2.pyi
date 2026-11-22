import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Carga(_message.Message):
    __slots__ = ("carga_id", "fuente", "estado", "inicio", "fin", "registros", "topic", "originales", "version_ingesta", "error")
    class Estado(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        ESTADO_UNSPECIFIED: _ClassVar[Carga.Estado]
        ESTADO_INICIADA: _ClassVar[Carga.Estado]
        ESTADO_COMPLETADA: _ClassVar[Carga.Estado]
        ESTADO_FALLIDA: _ClassVar[Carga.Estado]
    ESTADO_UNSPECIFIED: Carga.Estado
    ESTADO_INICIADA: Carga.Estado
    ESTADO_COMPLETADA: Carga.Estado
    ESTADO_FALLIDA: Carga.Estado
    CARGA_ID_FIELD_NUMBER: _ClassVar[int]
    FUENTE_FIELD_NUMBER: _ClassVar[int]
    ESTADO_FIELD_NUMBER: _ClassVar[int]
    INICIO_FIELD_NUMBER: _ClassVar[int]
    FIN_FIELD_NUMBER: _ClassVar[int]
    REGISTROS_FIELD_NUMBER: _ClassVar[int]
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    ORIGINALES_FIELD_NUMBER: _ClassVar[int]
    VERSION_INGESTA_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    carga_id: str
    fuente: str
    estado: Carga.Estado
    inicio: _timestamp_pb2.Timestamp
    fin: _timestamp_pb2.Timestamp
    registros: int
    topic: str
    originales: _containers.RepeatedCompositeFieldContainer[Original]
    version_ingesta: str
    error: str
    def __init__(self, carga_id: _Optional[str] = ..., fuente: _Optional[str] = ..., estado: _Optional[_Union[Carga.Estado, str]] = ..., inicio: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., fin: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., registros: _Optional[int] = ..., topic: _Optional[str] = ..., originales: _Optional[_Iterable[_Union[Original, _Mapping]]] = ..., version_ingesta: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class Original(_message.Message):
    __slots__ = ("url", "sha256", "ruta", "bytes")
    URL_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    RUTA_FIELD_NUMBER: _ClassVar[int]
    BYTES_FIELD_NUMBER: _ClassVar[int]
    url: str
    sha256: str
    ruta: str
    bytes: int
    def __init__(self, url: _Optional[str] = ..., sha256: _Optional[str] = ..., ruta: _Optional[str] = ..., bytes: _Optional[int] = ...) -> None: ...
