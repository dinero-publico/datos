from dinero_publico.bruto.v1 import cabecera_pb2 as _cabecera_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Licitacion(_message.Message):
    __slots__ = ("cabecera", "id", "enlace", "actualizado", "anulada", "anulada_en", "estado_codigo", "expediente", "organo", "proyecto", "lotes", "proceso", "programa_financiacion", "resultados")
    CABECERA_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    ENLACE_FIELD_NUMBER: _ClassVar[int]
    ACTUALIZADO_FIELD_NUMBER: _ClassVar[int]
    ANULADA_FIELD_NUMBER: _ClassVar[int]
    ANULADA_EN_FIELD_NUMBER: _ClassVar[int]
    ESTADO_CODIGO_FIELD_NUMBER: _ClassVar[int]
    EXPEDIENTE_FIELD_NUMBER: _ClassVar[int]
    ORGANO_FIELD_NUMBER: _ClassVar[int]
    PROYECTO_FIELD_NUMBER: _ClassVar[int]
    LOTES_FIELD_NUMBER: _ClassVar[int]
    PROCESO_FIELD_NUMBER: _ClassVar[int]
    PROGRAMA_FINANCIACION_FIELD_NUMBER: _ClassVar[int]
    RESULTADOS_FIELD_NUMBER: _ClassVar[int]
    cabecera: _cabecera_pb2.Cabecera
    id: str
    enlace: str
    actualizado: str
    anulada: bool
    anulada_en: str
    estado_codigo: str
    expediente: str
    organo: Organo
    proyecto: Proyecto
    lotes: _containers.RepeatedCompositeFieldContainer[Lote]
    proceso: Proceso
    programa_financiacion: str
    resultados: _containers.RepeatedCompositeFieldContainer[Resultado]
    def __init__(self, cabecera: _Optional[_Union[_cabecera_pb2.Cabecera, _Mapping]] = ..., id: _Optional[str] = ..., enlace: _Optional[str] = ..., actualizado: _Optional[str] = ..., anulada: _Optional[bool] = ..., anulada_en: _Optional[str] = ..., estado_codigo: _Optional[str] = ..., expediente: _Optional[str] = ..., organo: _Optional[_Union[Organo, _Mapping]] = ..., proyecto: _Optional[_Union[Proyecto, _Mapping]] = ..., lotes: _Optional[_Iterable[_Union[Lote, _Mapping]]] = ..., proceso: _Optional[_Union[Proceso, _Mapping]] = ..., programa_financiacion: _Optional[str] = ..., resultados: _Optional[_Iterable[_Union[Resultado, _Mapping]]] = ...) -> None: ...

class Organo(_message.Message):
    __slots__ = ("nombre", "nif", "dir3", "tipo_codigo", "superiores")
    NOMBRE_FIELD_NUMBER: _ClassVar[int]
    NIF_FIELD_NUMBER: _ClassVar[int]
    DIR3_FIELD_NUMBER: _ClassVar[int]
    TIPO_CODIGO_FIELD_NUMBER: _ClassVar[int]
    SUPERIORES_FIELD_NUMBER: _ClassVar[int]
    nombre: str
    nif: str
    dir3: str
    tipo_codigo: str
    superiores: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, nombre: _Optional[str] = ..., nif: _Optional[str] = ..., dir3: _Optional[str] = ..., tipo_codigo: _Optional[str] = ..., superiores: _Optional[_Iterable[str]] = ...) -> None: ...

class Proyecto(_message.Message):
    __slots__ = ("nombre", "tipo_codigo", "subtipo_codigo", "cpv", "nuts", "lugar", "valor_estimado", "presupuesto_sin_iva", "presupuesto_con_iva")
    NOMBRE_FIELD_NUMBER: _ClassVar[int]
    TIPO_CODIGO_FIELD_NUMBER: _ClassVar[int]
    SUBTIPO_CODIGO_FIELD_NUMBER: _ClassVar[int]
    CPV_FIELD_NUMBER: _ClassVar[int]
    NUTS_FIELD_NUMBER: _ClassVar[int]
    LUGAR_FIELD_NUMBER: _ClassVar[int]
    VALOR_ESTIMADO_FIELD_NUMBER: _ClassVar[int]
    PRESUPUESTO_SIN_IVA_FIELD_NUMBER: _ClassVar[int]
    PRESUPUESTO_CON_IVA_FIELD_NUMBER: _ClassVar[int]
    nombre: str
    tipo_codigo: str
    subtipo_codigo: str
    cpv: _containers.RepeatedScalarFieldContainer[str]
    nuts: str
    lugar: str
    valor_estimado: _cabecera_pb2.Importe
    presupuesto_sin_iva: _cabecera_pb2.Importe
    presupuesto_con_iva: _cabecera_pb2.Importe
    def __init__(self, nombre: _Optional[str] = ..., tipo_codigo: _Optional[str] = ..., subtipo_codigo: _Optional[str] = ..., cpv: _Optional[_Iterable[str]] = ..., nuts: _Optional[str] = ..., lugar: _Optional[str] = ..., valor_estimado: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ..., presupuesto_sin_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ..., presupuesto_con_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ...) -> None: ...

class Lote(_message.Message):
    __slots__ = ("id", "nombre", "cpv", "presupuesto_sin_iva", "presupuesto_con_iva")
    ID_FIELD_NUMBER: _ClassVar[int]
    NOMBRE_FIELD_NUMBER: _ClassVar[int]
    CPV_FIELD_NUMBER: _ClassVar[int]
    PRESUPUESTO_SIN_IVA_FIELD_NUMBER: _ClassVar[int]
    PRESUPUESTO_CON_IVA_FIELD_NUMBER: _ClassVar[int]
    id: str
    nombre: str
    cpv: _containers.RepeatedScalarFieldContainer[str]
    presupuesto_sin_iva: _cabecera_pb2.Importe
    presupuesto_con_iva: _cabecera_pb2.Importe
    def __init__(self, id: _Optional[str] = ..., nombre: _Optional[str] = ..., cpv: _Optional[_Iterable[str]] = ..., presupuesto_sin_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ..., presupuesto_con_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ...) -> None: ...

class Proceso(_message.Message):
    __slots__ = ("procedimiento_codigo", "sistema_codigo", "urgencia_codigo")
    PROCEDIMIENTO_CODIGO_FIELD_NUMBER: _ClassVar[int]
    SISTEMA_CODIGO_FIELD_NUMBER: _ClassVar[int]
    URGENCIA_CODIGO_FIELD_NUMBER: _ClassVar[int]
    procedimiento_codigo: str
    sistema_codigo: str
    urgencia_codigo: str
    def __init__(self, procedimiento_codigo: _Optional[str] = ..., sistema_codigo: _Optional[str] = ..., urgencia_codigo: _Optional[str] = ...) -> None: ...

class Resultado(_message.Message):
    __slots__ = ("codigo", "lote", "fecha_adjudicacion", "fecha_formalizacion", "ofertas_recibidas", "pyme", "adjudicatarios", "importe_sin_iva", "importe_con_iva")
    CODIGO_FIELD_NUMBER: _ClassVar[int]
    LOTE_FIELD_NUMBER: _ClassVar[int]
    FECHA_ADJUDICACION_FIELD_NUMBER: _ClassVar[int]
    FECHA_FORMALIZACION_FIELD_NUMBER: _ClassVar[int]
    OFERTAS_RECIBIDAS_FIELD_NUMBER: _ClassVar[int]
    PYME_FIELD_NUMBER: _ClassVar[int]
    ADJUDICATARIOS_FIELD_NUMBER: _ClassVar[int]
    IMPORTE_SIN_IVA_FIELD_NUMBER: _ClassVar[int]
    IMPORTE_CON_IVA_FIELD_NUMBER: _ClassVar[int]
    codigo: str
    lote: str
    fecha_adjudicacion: str
    fecha_formalizacion: str
    ofertas_recibidas: str
    pyme: str
    adjudicatarios: _containers.RepeatedCompositeFieldContainer[Adjudicatario]
    importe_sin_iva: _cabecera_pb2.Importe
    importe_con_iva: _cabecera_pb2.Importe
    def __init__(self, codigo: _Optional[str] = ..., lote: _Optional[str] = ..., fecha_adjudicacion: _Optional[str] = ..., fecha_formalizacion: _Optional[str] = ..., ofertas_recibidas: _Optional[str] = ..., pyme: _Optional[str] = ..., adjudicatarios: _Optional[_Iterable[_Union[Adjudicatario, _Mapping]]] = ..., importe_sin_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ..., importe_con_iva: _Optional[_Union[_cabecera_pb2.Importe, _Mapping]] = ...) -> None: ...

class Adjudicatario(_message.Message):
    __slots__ = ("nif", "nombre", "persona_fisica")
    NIF_FIELD_NUMBER: _ClassVar[int]
    NOMBRE_FIELD_NUMBER: _ClassVar[int]
    PERSONA_FISICA_FIELD_NUMBER: _ClassVar[int]
    nif: str
    nombre: str
    persona_fisica: bool
    def __init__(self, nif: _Optional[str] = ..., nombre: _Optional[str] = ..., persona_fisica: _Optional[bool] = ...) -> None: ...
