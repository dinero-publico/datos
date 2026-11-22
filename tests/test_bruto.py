"""Capa bruto: registros tal cual, personas físicas disociadas, formato Confluent y control de carga."""
import io
import zipfile

import pytest

pytest.importorskip("google.protobuf")

from dinero_datos import bruto, emitir
from dinero_datos import contratos as c
from dinero_publico.bruto.v1 import contratos_pb2, poblacion_pb2
from dinero_publico.control.v1 import carga_pb2

from test_contratos import CAB, entrada, zip_mes


def carga_memoria(entidad="contratos", fuente="placsp"):
    m = emitir.Memoria()
    return m, emitir.Carga(fuente, entidad, kafka=m, registro=m, almacen=m)


def mensajes(m, topic, clase):
    return [emitir.deserializar(v, clase)[1] for t, _, v in m.mensajes if t == topic and v is not None]


def test_formato_confluent_ida_y_vuelta():
    d = poblacion_pb2.DatoPoblacion(serie_codigo="ECP320", valor=49128297.0)
    b = emitir.serializar(d, 7)
    assert b[:6] == b"\x00\x00\x00\x00\x07\x00"
    assert emitir.deserializar(b, poblacion_pb2.DatoPoblacion) == (7, d)


def test_licitacion_tal_cual_y_persona_fisica(tmp_path):
    z = zip_mes(tmp_path, "202603", entrada("1", "2026-03-11T10:00:00+01:00",
                [("B12345674", "Obras, S.L.", 1000.5, "1"), ("12345678Z", "Juan Pérez", 500.0, "2")],
                lotes={"1": "Asfaltado", "2": "Aceras"}))
    m, carga = carga_memoria()
    with carga:
        proc = carga.original(z, url="https://x/202603.zip", extension="zip", anio="2026")
        ultimas, _ = bruto.leer_mes_bruto(z, proc, carga)
        for lic in ultimas.values():
            carga.emitir(lic)
    (lic,) = mensajes(m, emitir.topic_bruto("contratos"), contratos_pb2.Licitacion)
    assert lic.cabecera.clave == "1" and lic.id == "1" and lic.expediente == "EXP-1"
    assert lic.organo.nif == "P4100000A" and list(lic.organo.superiores) == ["Sevilla", "Andalucía", "ENTIDADES LOCALES", "Sector Público"]
    assert lic.estado_codigo == "RES" and lic.proyecto.tipo_codigo == "3" and list(lic.proyecto.cpv) == ["45233120"]
    assert lic.proceso.procedimiento_codigo == "1" and lic.programa_financiacion == "EU"
    assert [l.nombre for l in lic.lotes] == ["Asfaltado", "Aceras"]
    r1, r2 = lic.resultados
    # Importes como texto, tal cual, con su moneda.
    assert (r1.importe_sin_iva.valor, r1.importe_sin_iva.moneda, r1.pyme, r1.ofertas_recibidas) == ("1000.5", "EUR", "true", "1")
    assert (r1.adjudicatarios[0].nif, r1.adjudicatarios[0].nombre) == ("B12345674", "Obras, S.L.")
    # La persona física sale sin NIF ni nombre, solo marcada.
    assert (r2.adjudicatarios[0].nif, r2.adjudicatarios[0].nombre, r2.adjudicatarios[0].persona_fisica) == ("", "", True)
    p = lic.cabecera.procedencia
    assert p.fuente == "placsp" and p.ruta_original.startswith("s3://memoria/originales/placsp/2026/")
    assert p.ubicacion.entrada_atom == "1" and p.ubicacion.fichero_en_zip == "f0.atom"
    assert len(m.objetos) == 1  # el ZIP original, una vez


def test_ultima_version_y_anuladas(tmp_path):
    vieja = entrada("5", "2026-03-01T10:00:00+01:00", [("B12345674", "A", 1.0, "")])
    nueva = entrada("5", "2026-03-20T10:00:00+01:00", [("B12345674", "B", 2.0, "")])
    borrada = '<at:deleted-entry ref="https://x/licitacionesPerfilContratante/9" when="2026-03-21T00:00:00+01:00"/>'
    z = zip_mes(tmp_path, "202603", nueva, vieja + borrada)
    m, carga = carga_memoria()
    with carga:
        proc = carga.original(z, url="u", extension="zip", anio="2026")
        ultimas, anuladas = bruto.leer_mes_bruto(z, proc, carga)
    assert ultimas["5"].resultados[0].adjudicatarios[0].nombre == "B"
    assert ultimas["9"].anulada and ultimas["9"].anulada_en.startswith("2026-03-21")


def test_control_de_carga(tmp_path):
    m, carga = carga_memoria("poblacion", "ine_poblacion")
    with carga:
        proc = carga.original(b'{"COD": "X"}', url="https://ine/X", extension="json", anio=2026)
        carga.emitir(poblacion_pb2.DatoPoblacion(cabecera=carga.cabecera("X:1", proc, api={"peticion": "X", "posicion": 0}),
                                                 serie_codigo="X", valor=1.0))
    ini, fin = mensajes(m, emitir.TOPIC_CONTROL, carga_pb2.Carga)
    assert ini.estado == carga_pb2.Carga.ESTADO_INICIADA and fin.estado == carga_pb2.Carga.ESTADO_COMPLETADA
    assert fin.registros == 1 and fin.topic == "dinero-publico.bruto.poblacion.v1" and fin.originales[0].bytes == 12
    # El fin de la carga va después de sus registros.
    assert [t for t, _, _ in m.mensajes][-1] == emitir.TOPIC_CONTROL


def test_carga_fallida_se_anota():
    m, carga = carga_memoria("poblacion", "ine_poblacion")
    with pytest.raises(RuntimeError):
        with carga:
            raise RuntimeError("el INE no responde")
    fin = mensajes(m, emitir.TOPIC_CONTROL, carga_pb2.Carga)[-1]
    assert fin.estado == carga_pb2.Carga.ESTADO_FALLIDA and "el INE no responde" in fin.error


def test_poblacion_desde_la_api(monkeypatch):
    tabla = [{"COD": "ECP320", "Nombre": "Total Nacional. Todas las edades. Total. Población. Número. "}]
    serie = {"COD": "ECP320", "Nombre": "Total Nacional. Todas las edades. Total. Población. Número. ", "FK_Unidad": 3, "FK_Escala": 1,
             "Data": [{"Fecha": 1735686000000, "FK_TipoDato": 1, "FK_Periodo": 19, "Anyo": 2025, "Valor": 49128297.0, "Secreto": False},
                      {"Fecha": 1767222000000, "FK_TipoDato": 2, "FK_Periodo": 19, "Anyo": 2026, "Valor": 49500000.0, "Secreto": False}]}

    class R:
        def __init__(self, d):
            import json
            self.status_code, self.content, self._d = 200, json.dumps(d).encode(), d

        def json(self):
            return self._d

    class DL:
        def _request(self, metodo, url):
            return R(tabla if "DATOS_TABLA" in url else serie)

    m, carga = carga_memoria("poblacion", "ine_poblacion")
    with carga:
        bruto.emitir_poblacion(carga, DL())
    datos = mensajes(m, emitir.topic_bruto("poblacion"), poblacion_pb2.DatoPoblacion)
    assert [(d.cabecera.clave, d.anio, d.valor, d.tipo_dato_id, d.territorio) for d in datos] == [
        ("ECP320:1735686000000", 2025, 49128297.0, 1, "Total Nacional"), ("ECP320:1767222000000", 2026, 49500000.0, 2, "Total Nacional")]
    assert datos[0].cabecera.procedencia.ubicacion.api.peticion == "DATOS_SERIE/ECP320?nult=120"
