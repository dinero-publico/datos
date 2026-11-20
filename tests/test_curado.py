"""Capa curated: las tablas en Parquet salen con las columnas de TABLAS y sin retocar los datos."""
import json
from decimal import Decimal

import pytest

from dinero_datos import curado
from dinero_datos.fuentes import PERSONA_FISICA


def _publicado(tmp_path):
    d = {
        "ccaa.json": {"economica": {"1": "Gastos de Personal", "10": "Altos cargos"},
                      "anios": [{"anio": 2025, "comunidades": [{
                          "codigo": "01", "comunidad": "Andalucía", "foral": False, "total": 3.5,
                          "politicas": [{"codigo": "11", "politica": "Justicia", "area": "Servicios públicos básicos",
                                         "importe": 3.5, "capitulos": [1.25, 2.25, 0, 0, 0, 0, 0, 0, 0]}],
                          "gastos": {"1": 1.25, "10": 0.5}}]}],
                      "prorrogados": {"Andalucía": {"2025": {"base": 2024, "iguales": 8, "politicas": 21, "mismo_total": True}}}},
        "pge.json": {"politicas": [{"codigo": "11", "politica": "Justicia", "valores": {"2024-P": 2.0},
                                    "programas": [{"codigo": "111N", "programa": "Gobierno del Poder Judicial",
                                                   "valores": {"2023": 1.5, "2024-P": None}}]}],
                     "ejercicios": [{"columna": "2023", "anio": 2023, "prorrogado": False, "base": None}]},
        "entregas.json": {"anios": [{"anio": 2026, "norma": "RDL", "filas": [
            {"comunidad": "Madrid", "irpf": 10.5, "iva": 2.0, "total": 12.5}]}]},
        "cofog.json": {"divisiones": {"01": "Servicios públicos generales"},
                       "subsectores": {"central": [{"anio": 2024, "provisional": True, "total": 5.0,
                                                    "divisiones": {"01": 5.0}, "transferencias_aapp": 1.0}]},
                       "comunidades": [{"anio": 2024, "provisional": True, "filas": [
                           {"comunidad": "Ceuta", "foral": False, "total": 1.0, "divisiones": {"01": 1.0}}]}]},
        "estado.json": {"anios": [{"anio": 2026, "provisional": False, "pib": 1780669.0, "partidas": [
            {"codigo": "", "concepto": "Recursos", "bloque": "recursos", "nivel": 0, "valores": [1.0, 2.0]}]}]},
        "poblacion.json": {"provisionales": ["2026"], "territorios": {"España": {"2025": 49000000, "2026": 49500000}}},
        "subvenciones.json": {"partidos": {"2025": {
            "beneficiarios": [["G28570927", "PARTIDO POPULAR", 100.5, 2]],
            "organos": [["ESTADO", "MINISTERIO DEL INTERIOR", "D.G. DE POLÍTICA INTERIOR", 100.5]]}}},
        "subvenciones-2025.json": {"anio": 2025, "beneficiarios": [
            ["A85309219", "RED ELÉCTRICA DE ESPAÑA, S.A.U.", 761946962.65], ["", PERSONA_FISICA, 360000.0]]},
        "subvenciones-motivos-2025.json": {"anio": 2025, "beneficiarios": {
            "A85309219": {"total": 761946962.65, "c": [["878635", "SUBVENCIÓN", 761946962.65, 1]]}},
            "convocatorias": {"878635": {"titulo": "Ayudas", "finalidad": "Industria y Energía",
                                         "organo": ["ESTADO", "MINISTERIO", "SECRETARÍA"], "tipo": "Concesión directa",
                                         "mrr": True, "detalle": True}}},
        "contratos-2025-03.json": {
            "mes": "2025-03", "enlace": "https://x/?id=",
            "campos": ["id", "enlace", "organo", "expediente", "lote", "titulo", "adjudicatario", "sin_iva",
                       "con_iva", "fecha", "tipo", "procedimiento", "sistema", "ofertas", "pyme", "cpv", "nuts", "ue", "comparte"],
            "organos": [["Ayuntamiento de Soria", "P4227700J", "Entidades locales"]],
            "adjudicatarios": [["B12345674", "LIMPIEZAS, S.L."], ["", PERSONA_FISICA]],
            "adjudicaciones": [
                [1, "abc", 0, "E1", "1", "Limpieza", 0, 1000.0, 1210.0, "2025-03-06", "2", "1", "0", 3, 1, "90910000", "ES417", "NO-EU", 0],
                [1, "abc", 0, "E1", "2", "Limpieza", 1, 500.0, 605.0, "2025-03-06", "2", "1", "0", 1, 0, "90910000", "ES417", "NO-EU", 0],
                [2, "", 0, "AM", "", "Acuerdo marco", 0, 9e6, None, "2025-03-10", "1", "1", "1", None, None, "", "", "EU", 0]]},
    }
    for nombre, obj in d.items():
        (tmp_path / nombre).write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    return tmp_path


@pytest.fixture
def tablas(tmp_path):
    t = curado.construir(_publicado(tmp_path))
    cols = {tabla: curado.columnas(tabla, t.esq) for tabla in t.filas}
    return {tabla: [dict(zip(cols[tabla], r)) for r in filas] for tabla, filas in t.filas.items()}


def test_todas_las_tablas(tablas):
    assert set(tablas) == set(curado.TABLAS)


def test_millones_a_euros_y_territorios_nuts(tablas):
    assert curado.millones(1.25) == Decimal("1250000.00")
    ccaa = {(r["politica"], r["capitulo"]): r for r in tablas["presupuesto_ccaa"]}
    assert ccaa["11", 2]["credito_inicial"] == Decimal("2250000.00") and ccaa["11", 2]["territorio"] == "ES61"
    assert {r["concepto"] for r in tablas["entrega_a_cuenta"]} == {"irpf", "iva"}  # sin el total
    assert {r["territorio"] for r in tablas["gasto_cofog"]} == {"ES", "ES63"}
    assert tablas["poblacion"][1] == {"anio": 2026, "territorio": "ES", "habitantes": 49500000, "provisional": True}
    assert [r["programa"] for r in tablas["presupuesto_estado"]] == ["111N"]  # sin los valores vacíos
    assert tablas["pib"][0]["importe"] == Decimal("1780669000000.00")


def test_personas_fisicas_sin_nif_ni_entidad(tablas):
    fis = [r for r in tablas["subvencion_anual"] + tablas["adjudicacion"] if r["nombre"] == PERSONA_FISICA]
    assert len(fis) == 2 and all(r["nif"] is None for r in fis)
    assert all(r["nombre"] != PERSONA_FISICA for r in tablas["entidad"] + tablas["entidad_nombre"])


def test_contratos_licitacion_y_valor_maximo(tablas):
    assert [r["id"] for r in tablas["licitacion"]] == [1, 2]  # una por licitación, aunque tenga lotes
    am = [r for r in tablas["adjudicacion"] if r["licitacion_id"] == 2][0]
    assert am["es_valor_maximo"] and am["lote"] == "" and am["importe_con_iva"] is None
    lic = tablas["licitacion"][0]
    assert lic["enlace"] == "https://x/?id=abc" and lic["fondos_ue"] is False
    assert tablas["licitacion"][1]["enlace"] is None


def test_entidades_y_organos(tablas):
    ent = {r["nif"]: r for r in tablas["entidad"]}
    assert ent["P4227700J"]["es_publica"] and ent["P4227700J"]["nombre"] == "Ayuntamiento de Soria"
    assert not ent["B12345674"]["es_publica"] and ent["B12345674"]["tipo_nif"] == "B"
    assert {r["fuente_id"] for r in tablas["organo"]} == {"placsp", "bdns"}
    conv = tablas["convocatoria"][0]
    assert conv["organo_id"] in {r["id"] for r in tablas["organo"]} and conv["mrr"] is True


def test_parquet(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    destino = tmp_path / "curated"
    filas = curado.exportar(_publicado(tmp_path), destino)
    t = pq.read_table(destino / "adjudicacion.parquet")
    assert t.num_rows == filas["adjudicacion"] == 3
    assert str(t.schema.field("importe_sin_iva").type) == "decimal128(16, 2)"
    assert str(t.schema.field("fecha").type) == "date32[day]"
