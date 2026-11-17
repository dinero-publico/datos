"""Comprueba el análisis: años de los ejercicios del Estado, prórrogas autonómicas e informe."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dinero_datos import analisis as an  # noqa: E402
from dinero_datos import fuentes as fd  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def test_ejercicios_pge_con_fixture():
    pge = fd.parse_pge((FX / "pge_consolidados_2025-P.xlsx").read_bytes())
    ej = {e["columna"]: e for e in an.ejercicios_pge(pge)}
    assert ej["2018"] == {"columna": "2018", "anio": 2018, "prorrogado": False, "base": None}
    assert ej["2018-P"]["anio"] == 2019 and ej["2018-P"]["base"] == 2018
    assert ej["2019-P"]["anio"] == 2020
    assert ej["2025-P"] == {"columna": "2025-P", "anio": 2026, "prorrogado": True, "base": 2023}
    anios = [e["anio"] for e in ej.values()]
    assert len(anios) == len(set(anios))


def _com(nombre, total, importes):
    return {"comunidad": nombre, "total": total, "politicas": [{"codigo": str(i), "importe": v} for i, v in enumerate(importes)]}


def test_prorrogados_ccaa():
    base = [100.0, 50.0, 30.0, 20.0, 10.0, 5.0, 1.0]
    nuevo = [v * 1.03 for v in base]
    casi = base[:5] + [6.0, 2.0]  # repite 5 políticas: prórroga con ajustes
    ccaa = {"anios": [
        {"anio": 2024, "comunidades": [_com("A", 216.0, base), _com("B", 216.0, base)]},
        {"anio": 2025, "comunidades": [_com("A", 216.0, base), _com("B", 222.48, nuevo)]},
        {"anio": 2026, "comunidades": [_com("A", 218.0, casi), _com("B", 222.48, [v * 1.01 for v in nuevo])]},
    ]}
    pr = an.prorrogados_ccaa(ccaa)
    assert pr["A"]["2025"]["base"] == 2024 and pr["A"]["2025"]["iguales"] == 7
    assert pr["A"]["2026"]["base"] == 2024  # sigue sin presupuesto propio desde 2024
    assert pr["A"]["2026"]["iguales"] == 5
    assert pr["B"] == {"2026": {"base": 2025, "iguales": 0, "politicas": 7, "mismo_total": True}}


def test_informe_detecta_descuadres():
    entregas = {"anios": [{"anio": 2026, "filas": [
        {"comunidad": "X", "irpf": 1, "iva": 1, "impuestos_especiales": 1, "fondo_suficiencia": 1, "fondo_garantia": 1, "total": 5},
        {"comunidad": "Y", "irpf": 1, "iva": 1, "impuestos_especiales": 1, "fondo_suficiencia": 1, "fondo_garantia": 1, "total": 9},
    ]}]}
    inf = an.informe({"entregas.json": entregas})
    p = next(q for q in inf["pruebas"] if q["fuente"] == "entregas" and "suman" in q["prueba"])
    assert not p["ok"] and p["n_fallos"] == 1 and "Y" in p["fallos"][0]
    assert any(q["prueba"] == "El fichero existe" for q in inf["pruebas"])  # faltan las demás fuentes


def test_enriquecer_y_quitar_derivadas():
    pge = {"columnas": ["2023", "2023-P"], "politicas": []}
    e = an.enriquecer("pge.json", pge)
    assert e["ejercicios"][1]["anio"] == 2024
    assert an.sin_derivadas("pge.json", e) == pge
