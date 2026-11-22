"""Emisión a la plataforma: originales a Garage (S3) y registros brutos a Kafka en Protobuf.

Cada carga de una fuente:
  1. publica en dinero-publico.control.cargas.v1 un Carga «iniciada»;
  2. guarda cada fichero original en el bucket (originales/<fuente>/<año>/<sha256>.<ext>), solo
     si no estaba ya;
  3. emite un mensaje por registro de la fuente en su topic, con su clave natural;
  4. publica la Carga «completada» (o «fallida») con el número de registros y los originales.

Formato de cada mensaje, el de Confluent (Apicurio, Kafbat y los clientes Java y Go lo leen):
    0x00 · id del esquema (4 bytes) · índice del mensaje en el .proto · bytes Protobuf
El id se pide a Apicurio por subject (<topic>-value): no se puede emitir contra un esquema
que no esté registrado. Se escribe a mano porque el serializador de confluent-kafka no lee el
descriptor «serialized» de Apicurio 3.3.4 (llega en binario y no en base64).

Configuración por variables de entorno (en cronos las ponen los Secrets de Ansible):
    KAFKA_BOOTSTRAP, KAFKA_JAAS (sasl.jaas.config del usuario SCRAM), APICURIO_URL,
    AWS_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, BUCKET.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
import uuid
from pathlib import Path

log = logging.getLogger("dinero_datos")

APLICACION = "dinero-publico"
TOPIC_CONTROL = f"{APLICACION}.control.cargas.v1"
VERSION = os.environ.get("DINERO_VERSION", "desarrollo")


def topic_bruto(entidad: str) -> str:
    return f"{APLICACION}.bruto.{entidad}.v1"


# --------------------------------------------------------------------------- #
# Formato Confluent
# --------------------------------------------------------------------------- #
def serializar(mensaje, id_esquema: int) -> bytes:
    """Mensaje Protobuf en formato Confluent. Índice [0] (primer mensaje del .proto): un byte 0."""
    return b"\x00" + id_esquema.to_bytes(4, "big") + b"\x00" + mensaje.SerializeToString()


def _varint_zigzag(b: bytes, i: int) -> tuple[int, int]:
    n = desp = 0
    while True:
        x = b[i]
        i += 1
        n |= (x & 0x7F) << desp
        desp += 7
        if not x & 0x80:
            return (n >> 1) ^ -(n & 1), i


def deserializar(b: bytes, clase):
    """(id del esquema, mensaje) de unos bytes en formato Confluent."""
    if not b or b[0] != 0:
        raise ValueError("no es formato Confluent")
    id_esquema = int.from_bytes(b[1:5], "big")
    cuantos, i = _varint_zigzag(b, 5)
    for _ in range(cuantos):
        _, i = _varint_zigzag(b, i)
    return id_esquema, clase.FromString(b[i:])


def ahora_ts():
    from google.protobuf.timestamp_pb2 import Timestamp
    t = Timestamp()
    t.GetCurrentTime()
    return t


# --------------------------------------------------------------------------- #
# Destinos reales (Kafka, Apicurio, Garage) y de prueba
# --------------------------------------------------------------------------- #
class Registro:
    """Ids de los esquemas en Apicurio (API compatible con Confluent)."""

    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/apis/ccompat/v7"
        self._ids: dict[str, int] = {}

    def id_esquema(self, topic: str) -> int:
        if topic not in self._ids:
            import requests
            subject = f"{topic}-value"
            r = requests.get(f"{self.url}/subjects/{subject}/versions/latest", timeout=30)
            if r.status_code == 404:
                raise RuntimeError(f"El esquema {subject} no está registrado en Apicurio (ansible-playbook dinero-publico.yml --tags esquemas)")
            r.raise_for_status()
            self._ids[topic] = r.json()["id"]
        return self._ids[topic]


class Kafka:
    """Productor de Kafka con el usuario SCRAM de la aplicación. Falla si algún envío falla."""

    def __init__(self, bootstrap: str, jaas: str):
        from confluent_kafka import Producer
        usuario = re.search(r'username="([^"]*)"', jaas).group(1)
        clave = re.search(r'password="([^"]*)"', jaas).group(1)
        self._p = Producer({
            "bootstrap.servers": bootstrap, "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": "SCRAM-SHA-512", "sasl.username": usuario, "sasl.password": clave,
            "enable.idempotence": True, "acks": "all", "compression.type": "zstd",
            "linger.ms": 50, "batch.size": 262144,
        })
        self.errores: list[str] = []

    def _entregado(self, err, msg):
        if err is not None:
            self.errores.append(f"{msg.topic()}[{msg.key()}]: {err}")

    def enviar(self, topic: str, clave: str, valor: bytes | None) -> None:
        while True:
            try:
                self._p.produce(topic, key=clave.encode(), value=valor, on_delivery=self._entregado)
                break
            except BufferError:  # cola local llena: se espera a que salga lo pendiente
                self._p.poll(1)
        self._p.poll(0)

    def vaciar(self) -> None:
        pendientes = self._p.flush(120)
        if pendientes:
            self.errores.append(f"{pendientes} mensajes sin confirmar tras 120 s")
        if self.errores:
            raise RuntimeError(f"Fallaron {len(self.errores)} envíos a Kafka: {self.errores[:3]}")


class Almacen:
    """Bucket S3 de Garage para los originales."""

    def __init__(self, bucket: str):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self._s3 = boto3.client("s3", config=Config(s3={"addressing_style": "path"},
                                                    request_checksum_calculation="when_required",
                                                    response_checksum_validation="when_required"))

    def existe(self, ruta: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._s3.head_object(Bucket=self.bucket, Key=ruta)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def subir(self, ruta: str, fichero: Path, metadatos: dict[str, str]) -> None:
        self._s3.upload_file(str(fichero), self.bucket, ruta, ExtraArgs={"Metadata": metadatos})


class Memoria:
    """Kafka, registro y almacén en memoria, para los tests."""

    def __init__(self):
        self.mensajes: list[tuple[str, str, bytes | None]] = []
        self.objetos: dict[str, tuple[bytes, dict]] = {}
        self.errores: list[str] = []

    # Registro
    def id_esquema(self, topic: str) -> int:
        return 1000 + sorted({topic_bruto("poblacion"), topic_bruto("contratos"), TOPIC_CONTROL, topic}).index(topic)

    # Kafka
    def enviar(self, topic, clave, valor):
        self.mensajes.append((topic, clave, valor))

    def vaciar(self):
        pass

    # Almacén
    bucket = "memoria"

    def existe(self, ruta):
        return ruta in self.objetos

    def subir(self, ruta, fichero, metadatos):
        self.objetos[ruta] = (Path(fichero).read_bytes(), metadatos)


# --------------------------------------------------------------------------- #
# Una carga
# --------------------------------------------------------------------------- #
class Carga:
    """Una carga de una fuente hacia la plataforma. Úsese con «with»:

        with Carga("ine_poblacion", "poblacion") as carga:
            proc = carga.original(contenido, url="…", extension="json", anio=2026)
            carga.emitir(clave, mensaje_con_cabecera)
    """

    def __init__(self, fuente: str, entidad: str, *, kafka=None, registro=None, almacen=None):
        self.fuente = fuente
        self.topic = topic_bruto(entidad)
        self.carga_id = f"{fuente}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        self.kafka = kafka or Kafka(os.environ["KAFKA_BOOTSTRAP"], os.environ["KAFKA_JAAS"])
        self.registro = registro or Registro(os.environ["APICURIO_URL"])
        self.almacen = almacen or Almacen(os.environ["BUCKET"])
        self.registros = 0
        self.originales: list[dict] = []
        self._id_bruto = self.registro.id_esquema(self.topic)
        self._id_control = self.registro.id_esquema(TOPIC_CONTROL)
        self._inicio = ahora_ts()

    # -- control --------------------------------------------------------------
    def _control(self, estado, error: str = "") -> None:
        from dinero_publico.control.v1 import carga_pb2
        c = carga_pb2.Carga(carga_id=self.carga_id, fuente=self.fuente, estado=estado, inicio=self._inicio,
                            registros=self.registros, topic=self.topic, version_ingesta=VERSION, error=error[:2000],
                            originales=[carga_pb2.Original(**o) for o in self.originales])
        if estado != carga_pb2.Carga.ESTADO_INICIADA:
            c.fin.CopyFrom(ahora_ts())
        self.kafka.enviar(TOPIC_CONTROL, self.carga_id, serializar(c, self._id_control))

    def __enter__(self):
        from dinero_publico.control.v1 import carga_pb2
        self._control(carga_pb2.Carga.ESTADO_INICIADA)
        log.info("  carga %s → %s", self.carga_id, self.topic)
        return self

    def __exit__(self, tipo, exc, tb):
        from dinero_publico.control.v1 import carga_pb2
        try:
            self.kafka.vaciar()  # primero que lleguen los registros; después, el fin de la carga
        except Exception as e:
            exc = exc or e
        if exc is None:
            self._control(carga_pb2.Carga.ESTADO_COMPLETADA)
        else:
            self._control(carga_pb2.Carga.ESTADO_FALLIDA, f"{type(exc).__name__}: {exc}")
        self.kafka.vaciar()
        log.info("  %s: %d registros, %d originales%s", self.carga_id, self.registros, len(self.originales),
                 "" if exc is None else f" · FALLIDA: {exc}")
        return False

    # -- originales ---------------------------------------------------------------
    def original(self, contenido: bytes | Path, *, url: str, extension: str, anio: int | str):
        """Guarda el original (si no estaba) y devuelve su Procedencia, sin ubicación."""
        from dinero_publico.bruto.v1 import cabecera_pb2
        if isinstance(contenido, Path):
            fichero, h, tam = contenido, hashlib.sha256(), contenido.stat().st_size
            with open(contenido, "rb") as f:
                for trozo in iter(lambda: f.read(1 << 20), b""):
                    h.update(trozo)
            sha = h.hexdigest()
        else:
            import tempfile
            sha, tam = hashlib.sha256(contenido).hexdigest(), len(contenido)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix="." + extension)
            tmp.write(contenido)
            tmp.close()
            fichero = Path(tmp.name)
        ruta = f"originales/{self.fuente}/{anio}/{sha}.{extension}"
        try:
            if not self.almacen.existe(ruta):
                self.almacen.subir(ruta, fichero, {"url": url[:1024], "fuente": self.fuente, "carga": self.carga_id})
        finally:
            if not isinstance(contenido, Path):
                fichero.unlink(missing_ok=True)
        self.originales.append({"url": url, "sha256": sha, "ruta": f"s3://{self.almacen.bucket}/{ruta}", "bytes": tam})
        return cabecera_pb2.Procedencia(fuente=self.fuente, url=url, sha256_original=sha,
                                        ruta_original=f"s3://{self.almacen.bucket}/{ruta}",
                                        descargado_en=ahora_ts(), version_ingesta=VERSION)

    # -- registros ------------------------------------------------------------------
    def cabecera(self, clave: str, procedencia, **ubicacion):
        """Cabecera de un registro: la procedencia del original más su ubicación dentro de él."""
        from dinero_publico.bruto.v1 import cabecera_pb2
        p = cabecera_pb2.Procedencia()
        p.CopyFrom(procedencia)
        if ubicacion:
            p.ubicacion.CopyFrom(cabecera_pb2.Ubicacion(**ubicacion))
        return cabecera_pb2.Cabecera(clave=clave, carga_id=self.carga_id, procedencia=p)

    def emitir(self, mensaje) -> None:
        self.kafka.enviar(self.topic, mensaje.cabecera.clave, serializar(mensaje, self._id_bruto))
        self.registros += 1

    def borrar(self, clave: str) -> None:
        """Tombstone: la clave desaparece del topic compactado."""
        self.kafka.enviar(self.topic, clave, None)
