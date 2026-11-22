import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Cabecera(_message.Message):
    __slots__ = ("clave", "carga_id", "procedencia")
    CLAVE_FIELD_NUMBER: _ClassVar[int]
    CARGA_ID_FIELD_NUMBER: _ClassVar[int]
    PROCEDENCIA_FIELD_NUMBER: _ClassVar[int]
    clave: str
    carga_id: str
    procedencia: Procedencia
    def __init__(self, clave: _Optional[str] = ..., carga_id: _Optional[str] = ..., procedencia: _Optional[_Union[Procedencia, _Mapping]] = ...) -> None: ...

class Procedencia(_message.Message):
    __slots__ = ("fuente", "url", "sha256_original", "ruta_original", "descargado_en", "ubicacion", "version_ingesta")
    FUENTE_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    SHA256_ORIGINAL_FIELD_NUMBER: _ClassVar[int]
    RUTA_ORIGINAL_FIELD_NUMBER: _ClassVar[int]
    DESCARGADO_EN_FIELD_NUMBER: _ClassVar[int]
    UBICACION_FIELD_NUMBER: _ClassVar[int]
    VERSION_INGESTA_FIELD_NUMBER: _ClassVar[int]
    fuente: str
    url: str
    sha256_original: str
    ruta_original: str
    descargado_en: _timestamp_pb2.Timestamp
    ubicacion: Ubicacion
    version_ingesta: str
    def __init__(self, fuente: _Optional[str] = ..., url: _Optional[str] = ..., sha256_original: _Optional[str] = ..., ruta_original: _Optional[str] = ..., descargado_en: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., ubicacion: _Optional[_Union[Ubicacion, _Mapping]] = ..., version_ingesta: _Optional[str] = ...) -> None: ...

class Ubicacion(_message.Message):
    __slots__ = ("excel", "entrada_atom", "api", "fichero_en_zip")
    EXCEL_FIELD_NUMBER: _ClassVar[int]
    ENTRADA_ATOM_FIELD_NUMBER: _ClassVar[int]
    API_FIELD_NUMBER: _ClassVar[int]
    FICHERO_EN_ZIP_FIELD_NUMBER: _ClassVar[int]
    excel: CeldaExcel
    entrada_atom: str
    api: RespuestaApi
    fichero_en_zip: str
    def __init__(self, excel: _Optional[_Union[CeldaExcel, _Mapping]] = ..., entrada_atom: _Optional[str] = ..., api: _Optional[_Union[RespuestaApi, _Mapping]] = ..., fichero_en_zip: _Optional[str] = ...) -> None: ...

class CeldaExcel(_message.Message):
    __slots__ = ("hoja", "fila", "columnas")
    HOJA_FIELD_NUMBER: _ClassVar[int]
    FILA_FIELD_NUMBER: _ClassVar[int]
    COLUMNAS_FIELD_NUMBER: _ClassVar[int]
    hoja: str
    fila: int
    columnas: str
    def __init__(self, hoja: _Optional[str] = ..., fila: _Optional[int] = ..., columnas: _Optional[str] = ...) -> None: ...

class RespuestaApi(_message.Message):
    __slots__ = ("peticion", "posicion")
    PETICION_FIELD_NUMBER: _ClassVar[int]
    POSICION_FIELD_NUMBER: _ClassVar[int]
    peticion: str
    posicion: int
    def __init__(self, peticion: _Optional[str] = ..., posicion: _Optional[int] = ...) -> None: ...

class Importe(_message.Message):
    __slots__ = ("valor", "moneda")
    VALOR_FIELD_NUMBER: _ClassVar[int]
    MONEDA_FIELD_NUMBER: _ClassVar[int]
    valor: str
    moneda: str
    def __init__(self, valor: _Optional[str] = ..., moneda: _Optional[str] = ...) -> None: ...
