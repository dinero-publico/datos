"""Análisis de los datos normalizados.

Dos tareas, ambas sin red y repetibles sobre los JSON ya transformados:

1. Enriquecer los datos con información derivada que la web necesita y que no
   viene tal cual en los ficheros oficiales (se guarda en claves propias de cada
   JSON, para que la descarga siguiente no las confunda con datos de origen):
     * pge.json  → "ejercicios": año en que rige cada columna de la SEPG y si es prórroga.
     * ccaa.json → "prorrogados": presupuestos autonómicos que repiten el del año anterior.

2. Comprobar la coherencia de cada fuente (sumas, totales, años presentes) y dejar
   el resultado en informe.json.
"""
from __future__ import annotations

import datetime as dt
import re

# Claves que añade el análisis. La descarga las descarta al comparar con lo guardado.
CLAVES_DERIVADAS = {"pge.json": ("ejercicios",), "ccaa.json": ("prorrogados",)}

# Un presupuesto autonómico se considera prorrogado si repite el total exacto o al menos
# este número de políticas al céntimo respecto al año anterior. Con presupuesto nuevo casi
# nunca coinciden más de 2 o 3 (comprobado con 2016-2026).
MIN_POLITICAS_IGUALES = 5


# --------------------------------------------------------------------------- #
# Datos derivados
# --------------------------------------------------------------------------- #
def ejercicios_pge(pge: dict) -> list[dict]:
    """Año en que rige cada columna de la serie de la SEPG.

    «2025-P» es el presupuesto de 2025 prorrogado para 2026 (la SEPG lo publicó en
    enero de 2026): rige al año siguiente y procede del último presupuesto aprobado.
    """
    out, base = [], None
    for col in pge["columnas"]:
        m = re.fullmatch(r"(\d{4})(-P)?", col)
        if not m:
            continue
        y, prorr = int(m.group(1)), bool(m.group(2))
        if not prorr:
            base = y
        out.append({"columna": col, "anio": y + 1 if prorr else y, "prorrogado": prorr, "base": base if prorr else None})
    return out


def prorrogados_ccaa(ccaa: dict) -> dict:
    """{comunidad: {año: {"base", "iguales", "politicas", "mismo_total"}}} de los presupuestos prorrogados."""
    por_anio = {a["anio"]: {c["comunidad"]: c for c in a["comunidades"]} for a in ccaa["anios"]}
    out: dict[str, dict[str, dict]] = {}
    for y in sorted(por_anio):
        for com, c in por_anio[y].items():
            p = por_anio.get(y - 1, {}).get(com)
            if not p:
                continue
            prev = {q["codigo"]: q["importe"] for q in p["politicas"]}
            pols = [q for q in c["politicas"] if q["importe"]]
            iguales = sum(1 for q in pols if q["codigo"] in prev and abs(prev[q["codigo"]] - q["importe"]) < 0.01)
            mismo_total = abs(c["total"] - p["total"]) < 1e-4 * abs(p["total"])
            if iguales >= MIN_POLITICAS_IGUALES or mismo_total:
                ant = out.get(com, {}).get(str(y - 1))
                out.setdefault(com, {})[str(y)] = {
                    "base": ant["base"] if ant else y - 1,  # último año con presupuesto propio
                    "iguales": iguales,
                    "politicas": len(pols),
                    "mismo_total": mismo_total,
                }
    return out


def enriquecer(nombre: str, obj: dict) -> dict:
    """Devuelve una copia de obj con sus claves derivadas recalculadas."""
    obj = dict(obj)
    if nombre == "pge.json":
        obj["ejercicios"] = ejercicios_pge(obj)
    elif nombre == "ccaa.json":
        obj["prorrogados"] = prorrogados_ccaa(obj)
    return obj


def sin_derivadas(nombre: str, obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k not in CLAVES_DERIVADAS.get(nombre, ())}


# --------------------------------------------------------------------------- #
# Comprobaciones de coherencia
# --------------------------------------------------------------------------- #
class Informe:
    def __init__(self):
        self.pruebas: list[dict] = []

    def prueba(self, fuente: str, nombre: str, fallos: list[str], total: int | None = None, avisos: list[str] | None = None):
        """Los avisos son diferencias explicadas por la propia fuente: no cuentan como fallo."""
        p = {"fuente": fuente, "prueba": nombre, "ok": not fallos, "casos": total, "fallos": fallos[:20], "n_fallos": len(fallos)}
        if avisos:
            p["avisos"] = avisos[:20]
        self.pruebas.append(p)


def _casi(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def comprobar_estado(d: dict, inf: Informe):
    fallos, n = [], 0
    for a in d["anios"]:
        n += 1
        meses = len(a["meses"])
        for p in a["partidas"]:
            if len(p["valores"]) != meses:
                fallos.append(f"{a['anio']} {p['codigo'] or p['concepto']}: {len(p['valores'])} valores para {meses} meses")
        if not any(p["codigo"] == "B.9" for p in a["partidas"]):
            fallos.append(f"{a['anio']}: falta el saldo B.9")
    inf.prueba("estado", "Cada partida tiene un valor por mes publicado y existe el saldo B.9", fallos, n)
    ys = sorted(a["anio"] for a in d["anios"])
    huecos = [str(y) for y in range(ys[0], ys[-1] + 1) if y not in ys]
    inf.prueba("estado", "Serie de años sin huecos", [f"falta {y}" for y in huecos], len(ys))


def comprobar_pge(d: dict, inf: Informe):
    # En la serie reclasificada de la SEPG, algunas políticas tienen importe sin programas en años
    # antiguos (p. ej. la 28 en 2017-2020) y el total no las incluye: ese importe ya está contado en
    # otra política. Si la diferencia con el total es exactamente eso, es un aviso, no un fallo.
    sin_programas = lambda col: [p for p in d["politicas"] if p["valores"].get(col)
                                 and p.get("programas") and not any(g["valores"].get(col) for g in p["programas"])]
    fallos, avisos = [], []
    for col in d["columnas"]:
        suma = sum(p["valores"].get(col) or 0 for p in d["politicas"])
        tot = (d.get("total") or {}).get(col)
        if tot is None or _casi(suma, tot, max(1.0, abs(tot) * 1e-4)):
            continue
        sp = sin_programas(col)
        if sp and _casi(suma - sum(p["valores"][col] for p in sp), tot, max(1.0, abs(tot) * 1e-4)):
            avisos.append(f"{col}: el total no incluye {', '.join(p['codigo'] for p in sp)} ({sum(p['valores'][col] for p in sp):.2f} M€, sin programas en ese año)")
        else:
            fallos.append(f"{col}: políticas {suma:.2f} ≠ total {tot:.2f}")
    inf.prueba("pge", "La suma de las políticas coincide con el total de cada ejercicio", fallos, len(d["columnas"]), avisos)
    fallos, avisos = [], []
    for p in d["politicas"]:
        for col in d["columnas"]:
            v = p["valores"].get(col)
            s = sum(g["valores"].get(col) or 0 for g in p.get("programas", []))
            if not v or not p.get("programas") or _casi(s, v, max(1.0, abs(v) * 1e-3)):
                continue
            (avisos if s == 0 else fallos).append(f"{p['codigo']} {col}: programas {s:.2f} ≠ política {v:.2f}")
    inf.prueba("pge", "La suma de los programas coincide con su política", fallos, len(d["politicas"]) * len(d["columnas"]), avisos)
    años = [e["anio"] for e in ejercicios_pge(d)]
    inf.prueba("pge", "Cada ejercicio corresponde a un año distinto", [f"año repetido: {y}" for y in set(años) if años.count(y) > 1], len(años))


CONCEPTOS_ENTREGAS = ("irpf", "iva", "impuestos_especiales", "fondo_suficiencia", "fondo_garantia")


def comprobar_entregas(d: dict, inf: Informe):
    fallos, n = [], 0
    for a in d["anios"]:
        for f in a["filas"]:
            n += 1
            partes = [f.get(k) for k in CONCEPTOS_ENTREGAS]
            if f.get("total") is not None and all(v is not None for v in partes) and not _casi(sum(partes), f["total"], 0.05):
                fallos.append(f"{a['anio']} {f['comunidad']}: conceptos {sum(partes):.2f} ≠ total {f['total']:.2f}")
    inf.prueba("entregas", "Los conceptos de cada comunidad suman su total", fallos, n)
    fallos = [f"{a['anio']}: {len(a['filas'])} territorios" for a in d["anios"] if len(a["filas"]) != 17]
    inf.prueba("entregas", "Cada año tiene las 15 comunidades de régimen común más Ceuta y Melilla", fallos, len(d["anios"]))


def comprobar_ccaa(d: dict, inf: Informe):
    f_pol, f_cap, f_eco, n_pol, n_cap, n_eco = [], [], [], 0, 0, 0
    for a in d["anios"]:
        for c in a["comunidades"]:
            n_pol += 1
            s = sum(p["importe"] for p in c["politicas"])
            if not _casi(s, c["total"], 0.05):
                f_pol.append(f"{a['anio']} {c['comunidad']}: políticas {s:.2f} ≠ total {c['total']:.2f}")
            for p in c["politicas"]:
                if p.get("capitulos"):
                    n_cap += 1
                    sc = sum(v or 0 for v in p["capitulos"])
                    if not _casi(sc, p["importe"], 0.05):
                        f_cap.append(f"{a['anio']} {c['comunidad']} {p['codigo']}: capítulos {sc:.2f} ≠ {p['importe']:.2f}")
            g = c.get("gastos")
            if g:
                n_eco += 1
                caps = sum(v for k, v in g.items() if len(k) == 1 and k.isdigit())
                if not _casi(caps, c["total"], 0.05):
                    f_eco.append(f"{a['anio']} {c['comunidad']}: capítulos económicos {caps:.2f} ≠ total {c['total']:.2f}")
    inf.prueba("ccaa", "Las políticas de cada comunidad suman su presupuesto", f_pol, n_pol)
    inf.prueba("ccaa", "Los capítulos de cada política suman su importe", f_cap, n_cap)
    inf.prueba("ccaa", "La clasificación económica suma el presupuesto", f_eco, n_eco)
    fallos = [f"{a['anio']}: {len(a['comunidades'])} comunidades" for a in d["anios"] if len(a["comunidades"]) < 17]
    inf.prueba("ccaa", "Cada año tiene las 17 comunidades", fallos, len(d["anios"]))


def comprobar_cofog(d: dict, inf: Informe):
    fallos, n = [], 0
    for sub, serie in d["subsectores"].items():
        for a in serie:
            n += 1
            s = sum(a["divisiones"].values())
            if not _casi(s, a["total"], max(2.0, abs(a["total"]) * 1e-4)):
                fallos.append(f"{sub} {a['anio']}: divisiones {s:.0f} ≠ total {a['total']:.0f}")
    for a in d["comunidades"]:
        for f in a["filas"]:
            n += 1
            s = sum(f["divisiones"].values())
            if not _casi(s, f["total"], max(2.0, abs(f["total"]) * 1e-4)):
                fallos.append(f"{f['comunidad']} {a['anio']}: divisiones {s:.0f} ≠ total {f['total']:.0f}")
    inf.prueba("cofog", "Las diez divisiones suman el total de cada administración y comunidad", fallos, n)


def comprobar_poblacion(d: dict, inf: Informe):
    t = d["territorios"]
    esp = t.get("España", {})
    partes = [k for k in t if k != "España"]
    fallos = []
    for y, v in esp.items():
        s = sum(t[k].get(y, 0) for k in partes)
        if abs(s - v) > 10:
            fallos.append(f"{y}: comunidades + Ceuta y Melilla = {s} ≠ España {v}")
    inf.prueba("poblacion", "Comunidades, Ceuta y Melilla suman la población de España", fallos, len(esp))


def comprobar_subvenciones(d: dict, inf: Informe):
    g = d["grandes"]
    fallos = []
    for a, x in g.items():
        if x["total_fuente"] is not None and x["beneficiarios"] != x["total_fuente"]:
            fallos.append(f"{a}: {x['beneficiarios']} beneficiarios, la BDNS declara {x['total_fuente']}")
    inf.prueba("subvenciones", "Están todos los grandes beneficiarios que declara la BDNS", fallos, len(g))
    fallos = []
    for a, x in g.items():
        s = sum(v[1] for v in x["por_tipo"].values())
        n = sum(v[0] for v in x["por_tipo"].values())
        if n != x["beneficiarios"] or not _casi(s, x["total"], 1.0):
            fallos.append(f"{a}: tipos {n} / {s:.0f} € ≠ total {x['beneficiarios']} / {x['total']:.0f} €")
        if x["minimo"] is not None and x["minimo"] < d["umbral"]:
            fallos.append(f"{a}: hay beneficiarios por debajo de {d['umbral']} € ({x['minimo']})")
    inf.prueba("subvenciones", "Los tipos de entidad suman el total y nadie queda por debajo del umbral", fallos, len(g))
    fallos = []
    for a, x in d["partidos"].items():
        s = sum(b[2] for b in x["beneficiarios"])
        n = sum(b[3] for b in x["beneficiarios"])
        if n != x["concesiones"] or not _casi(s, x["total"], 1.0):
            fallos.append(f"{a}: beneficiarios {n} / {s:.0f} € ≠ {x['concesiones']} / {x['total']:.0f} €")
    inf.prueba("subvenciones", "Las subvenciones a partidos por beneficiario suman el total", fallos, len(d["partidos"]))
    fallos, n = [], 0
    for a, x in g.items():
        m = x.get("motivos")
        if not m:
            continue
        n += 1
        for k in ("por_finalidad", "por_instrumento", "por_administracion", "por_procedimiento"):
            if not _casi(sum(m[k].values()), m["importe"], 1.0):
                fallos.append(f"{a}: {k} suma {sum(m[k].values()):.0f} € ≠ {m['importe']:.0f} €")
        if m["cobertura"] is not None and not 0 < m["cobertura"] <= 1.01:
            fallos.append(f"{a}: cobertura {m['cobertura']}")
    if n:
        inf.prueba("subvenciones", "Los motivos (finalidad, instrumento, administración, procedimiento) suman lo consultado", fallos, n)


def comprobar_contratos(d: dict, inf: Informe):
    fallos = []
    for a, x in d["anios"].items():
        for k in ("por_tipo", "por_procedimiento", "por_administracion", "por_comunidad", "por_mes"):
            n = sum(v[0] for v in x[k].values())
            s = sum(v[1] for v in x[k].values())
            if n != x["adjudicaciones"] or not _casi(s, x["importe"], 1.0):
                fallos.append(f"{a}: {k} suma {n} / {s:.0f} € ≠ {x['adjudicaciones']} / {x['importe']:.0f} €")
    inf.prueba("contratos", "Las adjudicaciones por tipo, procedimiento, administración, comunidad y mes suman el total", fallos, len(d["anios"]))
    fallos = []
    for a in d["anios"]:
        meses_a = [m for m in d["cobertura"]["meses"] if m.startswith(a)]
        if a >= d["cobertura"]["desde"][:4] and not meses_a:
            fallos.append(f"{a}: no se ha descargado ningún mes")
    inf.prueba("contratos", "Hay meses descargados para cada año publicado", fallos, len(d["anios"]))


COMPROBACIONES = {
    "estado.json": comprobar_estado, "pge.json": comprobar_pge, "entregas.json": comprobar_entregas,
    "ccaa.json": comprobar_ccaa, "cofog.json": comprobar_cofog, "poblacion.json": comprobar_poblacion,
    "subvenciones.json": comprobar_subvenciones,
}
# Fuentes que solo se actualizan desde un ordenador local (su ausencia no es un fallo).
OPCIONALES = {"contratos.json": comprobar_contratos}


def informe(datos: dict[str, dict]) -> dict:
    """Ejecuta todas las comprobaciones sobre {fichero: json} y devuelve el informe."""
    inf = Informe()
    for nombre, fn in COMPROBACIONES.items():
        if nombre not in datos:
            inf.prueba(nombre.removesuffix(".json"), "El fichero existe", [f"falta {nombre}"])
            continue
        try:
            fn(datos[nombre], inf)
        except Exception as e:  # un formato inesperado es un fallo de la prueba, no del análisis
            inf.prueba(nombre.removesuffix(".json"), "El fichero tiene el formato esperado", [f"{type(e).__name__}: {e}"])
    for nombre, fn in OPCIONALES.items():
        if nombre in datos:
            try:
                fn(datos[nombre], inf)
            except Exception as e:
                inf.prueba(nombre.removesuffix(".json"), "El fichero tiene el formato esperado", [f"{type(e).__name__}: {e}"])
    ok = sum(p["ok"] for p in inf.pruebas)
    return {
        "generado": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "resumen": {"pruebas": len(inf.pruebas), "correctas": ok, "con_fallos": len(inf.pruebas) - ok},
        "pruebas": inf.pruebas,
    }
