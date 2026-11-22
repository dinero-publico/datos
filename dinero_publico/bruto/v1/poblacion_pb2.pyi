from dinero_publico.bruto.v1 import cabecera_pb2 as _cabecera_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DatoPoblacion(_message.Message):
    __slots__ = ("cabecera", "serie_codigo", "serie_nombre", "territorio", "fecha_ms", "anio", "periodo_id", "tipo_dato_id", "unidad_id", "escala_id", "valor", "secreto")
    CABECERA_FIELD_NUMBER: _ClassVar[int]
    SERIE_CODIGO_FIELD_NUMBER: _ClassVar[int]
    SERIE_NOMBRE_FIELD_NUMBER: _ClassVar[int]
    TERRITORIO_FIELD_NUMBER: _ClassVar[int]
    FECHA_MS_FIELD_NUMBER: _ClassVar[int]
    ANIO_FIELD_NUMBER: _ClassVar[int]
    PERIODO_ID_FIELD_NUMBER: _ClassVar[int]
    TIPO_DATO_ID_FIELD_NUMBER: _ClassVar[int]
    UNIDAD_ID_FIELD_NUMBER: _ClassVar[int]
    ESCALA_ID_FIELD_NUMBER: _ClassVar[int]
    VALOR_FIELD_NUMBER: _ClassVar[int]
    SECRETO_FIELD_NUMBER: _ClassVar[int]
    cabecera: _cabecera_pb2.Cabecera
    serie_codigo: str
    serie_nombre: str
    territorio: str
    fecha_ms: int
    anio: int
    periodo_id: int
    tipo_dato_id: int
    unidad_id: int
    escala_id: int
    valor: float
    secreto: bool
    def __init__(self, cabecera: _Optional[_Union[_cabecera_pb2.Cabecera, _Mapping]] = ..., serie_codigo: _Optional[str] = ..., serie_nombre: _Optional[str] = ..., territorio: _Optional[str] = ..., fecha_ms: _Optional[int] = ..., anio: _Optional[int] = ..., periodo_id: _Optional[int] = ..., tipo_dato_id: _Optional[int] = ..., unidad_id: _Optional[int] = ..., escala_id: _Optional[int] = ..., valor: _Optional[float] = ..., secreto: _Optional[bool] = ...) -> None: ...
