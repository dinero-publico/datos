"""Capa curated: las tablas del modelo de datos en Parquet (docs/modelo-de-datos.md).

Lee los JSON de publicado/v1/ (ya transformados, comprobados y sin datos personales) y
los reparte en una tabla por hecho y por catálogo, con las columnas de sql/esquema.sql.
Ese fichero es la definición única: aquí solo se dice de dónde sale cada valor.

Cambios respecto a los JSON, todos mecánicos:
  · importes en euros (las fuentes en millones se multiplican por 10⁶, con dos decimales);
  · territorios por código NUTS (ES, ES61…), porque cada fuente usa su propio código;
  · filas «largas»: una por año, territorio, concepto… en vez de listas por columnas;
  · los índices de los ficheros de contratos se sustituyen por el NIF y el id del órgano.

El Parquet necesita pyarrow (requirements-plataforma.txt); construir las tablas, no.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from decimal import Decimal
from pathlib import Path

from . import contratos as con
from . import fuentes as f

log = logging.getLogger("dinero_datos")

ESQUEMA = Path(__file__).resolve().parents[1] / "sql" / "esquema.sql"
# Tablas del esquema que no salen de los JSON: las llena el paso de carga.
SOLO_CARGA = {"fuente", "carga"}
COLUMNAS_CARGA = {"carga_id"}

CENTIMO = Decimal("0.01")
MILLON = Decimal(1_000_000)

ESPANA = "ES"
NUTS_DE = {nombre: nuts for nuts, nombre in con.NUTS2.items()} | {"España": ESPANA}


# --------------------------------------------------------------------------- #
# Esquema
# --------------------------------------------------------------------------- #
def esquema(ruta: Path = ESQUEMA) -> dict[str, list[tuple[str, str]]]:
    """{tabla: [(columna, tipo)]} leído de sql/esquema.sql (una columna por línea)."""
    tablas, actual = {}, None
    for linea in ruta.read_text("utf-8").splitlines():
        linea = linea.split("--")[0].strip()
        if m := re.match(r"CREATE TABLE (\w+) \($", linea):
            actual = tablas.setdefault(m[1], [])
        elif actual is not None and linea.startswith(")"):
            actual = None
        elif actual is not None and linea and not re.match(r"(PRIMARY|UNIQUE|FOREIGN|CHECK|CONSTRAINT)\b", linea):
            nombre, tipo = re.match(r"(\w+) (\w+(?:\(\d+,\d+\))?)", linea).groups()
            actual.append((nombre, tipo))
    return tablas


def columnas(tabla: str, esq: dict | None = None) -> list[str]:
    return [c for c, _ in (esq or esquema())[tabla] if c not in COLUMNAS_CARGA]


# --------------------------------------------------------------------------- #
# Conversión de valores
# --------------------------------------------------------------------------- #
def euros(v) -> Decimal | None:
    return None if v is None else Decimal(str(v)).quantize(CENTIMO)


def millones(v) -> Decimal | None:
    return None if v is None else (Decimal(str(v)) * MILLON).quantize(CENTIMO)


def nif_o_nada(nif: str | None) -> str | None:
    return nif or None


def id_organo(fuente: str, nombre: str, nif: str | None = None, superior: str | None = None) -> str:
    clave = "|".join([fuente, nombre or "", nif or "", superior or ""])
    return hashlib.sha1(clave.encode()).hexdigest()[:16]


class Tablas:
    """Acumula filas por tabla con las columnas del esquema, en su orden."""

    def __init__(self, esq: dict | None = None):
        self.esq = esq or esquema()
        self.filas: dict[str, list[tuple]] = {}
        self._orden: dict[str, list[str]] = {}

    def add(self, tabla: str, **valores) -> None:
        orden = self._orden.get(tabla)
        if orden is None:
            orden = self._orden[tabla] = columnas(tabla, self.esq)
        if set(valores) != set(orden):
            raise ValueError(f"{tabla}: sobran {set(valores) - set(orden)} y faltan {set(orden) - set(valores)}")
        self.filas.setdefault(tabla, []).append(tuple(valores[c] for c in orden))


# --------------------------------------------------------------------------- #
# Construcción de las tablas
# --------------------------------------------------------------------------- #
def territorio(nombre: str) -> str:
    try:
        return NUTS_DE[nombre]
    except KeyError:
        raise ValueError(f"territorio desconocido: {nombre!r}") from None


def construir(carpeta: Path, esq: dict | None = None) -> Tablas:
    def leer(nombre):
        p = carpeta / nombre
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    t = Tablas(esq)
    nombres: dict[tuple, list] = {}  # (nif, nombre, fuente) -> [primer, último año]
    organos: dict[str, dict] = {}

    def visto(nif, nombre, fuente, anio):
        if nif and nombre:
            r = nombres.setdefault((nif, nombre, fuente), [anio, anio])
            r[0], r[1] = min(r[0], anio), max(r[1], anio)

    def organo(fuente, nombre, nif=None, administracion=None, superior=None):
        i = id_organo(fuente, nombre, nif, superior)
        organos.setdefault(i, dict(id=i, fuente_id=fuente, nombre=nombre, nif=nif_o_nada(nif),
                                   administracion=administracion, superior=superior))
        return i

    _catalogos(t, leer)
    _presupuestos(t, leer)
    _subvenciones(t, carpeta, leer, visto, organo)
    _contratos(t, carpeta, visto, organo)

    for o in organos.values():
        t.add("organo", **o)
    _entidades(t, nombres, {o["nif"]: o["nombre"] for o in organos.values() if o["nif"]})
    return t


def _catalogos(t: Tablas, leer) -> None:
    ccaa = leer("ccaa.json") or {}
    forales = {c["comunidad"]: (c["codigo"], c["foral"])
               for a in ccaa.get("anios", []) for c in a["comunidades"]}
    t.add("territorio", codigo=ESPANA, nombre="España", nivel="pais", codigo_sgcief=None, foral=False)
    for nuts, nombre in sorted(con.NUTS2.items()):
        cod, foral = forales.get(nombre, (None, False))
        t.add("territorio", codigo=nuts, nombre=nombre, nivel="comunidad", codigo_sgcief=cod, foral=foral)

    listas = {"tipo_nif": f.NIF_TIPOS, "contrato_tipo": con.TIPOS,
              "contrato_procedimiento": con.PROCEDIMIENTOS, "contrato_sistema": con.SISTEMAS}
    for lista, codigos in listas.items():
        for codigo, nombre in codigos.items():
            t.add("codigo_lista", lista=lista, codigo=codigo, nombre=nombre)

    for codigo, nombre in (ccaa.get("economica") or {}).items():
        t.add("economica", codigo=codigo, nombre=nombre, capitulo=int(codigo[0]))
    for codigo, nombre in ((leer("cofog.json") or {}).get("divisiones") or {}).items():
        t.add("cofog_division", codigo=codigo, nombre=nombre)

    # Políticas: nombres de los PGE y el área de gasto de los presupuestos autonómicos.
    politicas: dict[str, dict] = {}
    for a in ccaa.get("anios", []):
        for c in a["comunidades"]:
            for p in c["politicas"]:
                politicas.setdefault(p["codigo"], dict(codigo=p["codigo"], nombre=p["politica"], area=p.get("area")))
    pge = leer("pge.json") or {}
    for p in pge.get("politicas", []):
        d = politicas.setdefault(p["codigo"], dict(codigo=p["codigo"], nombre=p["politica"], area=None))
        d["nombre"] = p["politica"]
        for pr in p.get("programas", []):
            t.add("programa", codigo=pr["codigo"], nombre=pr["programa"], politica=p["codigo"])
    for d in politicas.values():
        t.add("politica", **d)


def _presupuestos(t: Tablas, leer) -> None:
    pge = leer("pge.json")
    if pge:
        ejercicios = {e["columna"]: e for e in pge.get("ejercicios", [])}
        for p in pge["politicas"]:
            for pr in p.get("programas", []):
                for col, v in pr["valores"].items():
                    if v is None:
                        continue
                    e = ejercicios.get(col, {})
                    t.add("presupuesto_estado", columna=col, ejercicio=e.get("anio", int(col[:4])),
                          prorrogado=e.get("prorrogado", col.endswith("-P")), base=e.get("base"),
                          programa=pr["codigo"], credito_inicial=millones(v))

    ccaa = leer("ccaa.json")
    if ccaa:
        for a in ccaa["anios"]:
            for c in a["comunidades"]:
                ter = territorio(c["comunidad"])
                for p in c["politicas"]:
                    for i, v in enumerate(p.get("capitulos") or []):
                        if v is not None:
                            t.add("presupuesto_ccaa", anio=a["anio"], territorio=ter, politica=p["codigo"],
                                  capitulo=i + 1, credito_inicial=millones(v))
                for cod, v in (c.get("gastos") or {}).items():
                    if v is not None:
                        t.add("presupuesto_ccaa_economica", anio=a["anio"], territorio=ter, economica=cod,
                              credito_inicial=millones(v))
        for nombre, anios in (ccaa.get("prorrogados") or {}).items():
            for anio, p in anios.items():
                t.add("presupuesto_ccaa_prorroga", anio=int(anio), territorio=territorio(nombre), base=p["base"],
                      politicas_iguales=p["iguales"], politicas=p["politicas"], mismo_total=p["mismo_total"])

    ent = leer("entregas.json")
    if ent:
        for a in ent["anios"]:
            for fila in a["filas"]:
                for concepto, v in fila.items():
                    if concepto in ("comunidad", "total") or not isinstance(v, (int, float)) or isinstance(v, bool):
                        continue
                    t.add("entrega_a_cuenta", anio=a["anio"], territorio=territorio(fila["comunidad"]),
                          concepto=concepto, importe=millones(v), norma=a.get("norma"))

    cofog = leer("cofog.json")
    if cofog:
        def gasto(anio, sub, ter, prov, fila):
            for div, v in (fila.get("divisiones") or {}).items():
                if v is not None:
                    t.add("gasto_cofog", anio=anio, subsector=sub, territorio=ter, division=div,
                          importe=millones(v), provisional=prov)
            if fila.get("total") is not None:
                t.add("gasto_cofog_total", anio=anio, subsector=sub, territorio=ter, total=millones(fila["total"]),
                      transferencias_aapp=millones(fila.get("transferencias_aapp")), provisional=prov)
        for sub, filas in cofog["subsectores"].items():
            for x in filas:
                gasto(x["anio"], sub, ESPANA, bool(x.get("provisional")), x)
        for a in cofog.get("comunidades", []):
            for x in a["filas"]:
                gasto(a["anio"], "regional", territorio(x["comunidad"]), bool(a.get("provisional")), x)

    est = leer("estado.json")
    if est:
        for a in est["anios"]:
            prov = bool(a.get("provisional"))
            if a.get("pib") is not None:
                t.add("pib", anio=a["anio"], importe=millones(a["pib"]))
            for orden, p in enumerate(a["partidas"]):
                for mes, v in enumerate(p["valores"], start=1):
                    t.add("ejecucion_estado", anio=a["anio"], mes=mes, orden=orden, bloque=p["bloque"],
                          nivel=p["nivel"], codigo=p["codigo"] or None, concepto=p["concepto"],
                          importe_acumulado=millones(v), provisional=prov)

    pob = leer("poblacion.json")
    if pob:
        provisionales = set(map(str, pob.get("provisionales") or []))
        for nombre, anios in pob["territorios"].items():
            for anio, n in anios.items():
                if n is not None:
                    t.add("poblacion", anio=int(anio), territorio=territorio(nombre), habitantes=n,
                          provisional=anio in provisionales)


def _subvenciones(t: Tablas, carpeta: Path, leer, visto, organo) -> None:
    for p in sorted(carpeta.glob("subvenciones-[0-9][0-9][0-9][0-9].json")):
        d = json.loads(p.read_text("utf-8"))
        anio = d["anio"]
        for puesto, (nif, nombre, imp) in enumerate(d["beneficiarios"], start=1):
            t.add("subvencion_anual", anio=anio, puesto=puesto, nif=nif_o_nada(nif), nombre=nombre,
                  importe_equivalente=euros(imp))
            visto(nif, nombre, "bdns", anio)

    convocatorias: dict[str, tuple[int, dict]] = {}
    for p in sorted(carpeta.glob("subvenciones-motivos-*.json")):
        d = json.loads(p.read_text("utf-8"))
        anio = d["anio"]
        for nif, b in d["beneficiarios"].items():
            for cod, instrumento, imp, n in b["c"]:
                t.add("subvencion_concesion", anio=anio, nif=nif, convocatoria=cod, instrumento=instrumento,
                      importe=euros(imp), concesiones=n)
        for cod, c in d["convocatorias"].items():
            if cod not in convocatorias or convocatorias[cod][0] <= anio:  # la ficha más reciente
                convocatorias[cod] = (anio, c)
    for cod, (_, c) in sorted(convocatorias.items()):
        org = c.get("organo") or [None, None, None]
        oid = organo("bdns", org[2], None, org[0], org[1]) if org[2] else None
        t.add("convocatoria", codigo=cod, titulo=c.get("titulo"), finalidad=c.get("finalidad"), organo_id=oid,
              procedimiento=c.get("tipo"), mrr=c.get("mrr"), detalle=bool(c.get("detalle")))

    sub = leer("subvenciones.json") or {}
    for anio, x in (sub.get("partidos") or {}).items():
        for nif, nombre, imp, n in x.get("beneficiarios", []):
            t.add("subvencion_partido", anio=int(anio), nif=nif, nombre=nombre, importe=euros(imp), concesiones=n)
            visto(nif, nombre, "bdns", int(anio))
        for nivel, superior, nombre, imp in x.get("organos", []):
            t.add("subvencion_partido_organo", anio=int(anio), organo_id=organo("bdns", nombre, None, nivel, superior),
                  importe=euros(imp))


def _contratos(t: Tablas, carpeta: Path, visto, organo) -> None:
    licitaciones: set[int] = set()
    for p in sorted(carpeta.glob("contratos-[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        d = json.loads(p.read_text("utf-8"))
        anio = int(d["mes"][:4])
        i = {c: n for n, c in enumerate(d["campos"])}
        org = [organo("placsp", *o) for o in d["organos"]]
        adj = d["adjudicatarios"]
        enlace = d.get("enlace") or con.ENLACE
        for r in d["adjudicaciones"]:
            lid = r[i["id"]]
            if lid not in licitaciones:
                licitaciones.add(lid)
                t.add("licitacion", id=lid, fuente_id="placsp",
                      enlace=enlace + r[i["enlace"]] if r[i["enlace"]] else None,
                      organo_id=org[r[i["organo"]]], expediente=r[i["expediente"]] or None,
                      objeto=r[i["titulo"]], tipo=r[i["tipo"]], procedimiento=r[i["procedimiento"]],
                      sistema=r[i["sistema"]], cpv=r[i["cpv"]] or None, territorio=r[i["nuts"]] or None,
                      fondos_ue=None if r[i["ue"]] is None else r[i["ue"]] == "EU")
            nif, nombre = adj[r[i["adjudicatario"]]]
            visto(nif, nombre, "placsp", anio)
            pyme = r[i["pyme"]]
            t.add("adjudicacion", licitacion_id=lid, lote=r[i["lote"]] or "", nif=nif_o_nada(nif), nombre=nombre,
                  objeto=r[i["titulo"]], fecha=r[i["fecha"]], importe_sin_iva=euros(r[i["sin_iva"]]),
                  importe_con_iva=euros(r[i["con_iva"]]), ofertas=r[i["ofertas"]],
                  pyme=None if pyme is None else bool(pyme),
                  es_valor_maximo=r[i["sistema"]] in con.SISTEMAS_VALOR_MAXIMO,
                  importe_compartido=bool(r[i["comparte"]]))


def _entidades(t: Tablas, nombres: dict, organos: dict[str, str]) -> None:
    """entidad y entidad_nombre: cada NIF visto en cualquier fuente, con el nombre más reciente."""
    ultimo: dict[str, tuple] = {}
    for (nif, nombre, fuente), (primer, ult) in sorted(nombres.items()):
        t.add("entidad_nombre", nif=nif, nombre=nombre, fuente_id=fuente, primer_anio=primer, ultimo_anio=ult)
        if nif not in ultimo or ult >= ultimo[nif][0]:
            ultimo[nif] = (ult, nombre)
    for nif in sorted(set(ultimo) | set(organos)):
        tipo = f.tipo_nif(nif)
        nombre = ultimo[nif][1] if nif in ultimo else organos[nif]
        t.add("entidad", nif=nif, tipo_nif=tipo, nombre=nombre, es_publica=tipo in ("P", "Q", "S") or nif in organos)


# --------------------------------------------------------------------------- #
# Parquet
# --------------------------------------------------------------------------- #
def _tipo_arrow(pa, tipo: str):
    if m := re.fullmatch(r"numeric\((\d+),(\d+)\)", tipo):
        return pa.decimal128(int(m[1]), int(m[2]))
    return {"text": pa.string(), "smallint": pa.int16(), "integer": pa.int32(), "bigint": pa.int64(),
            "bigserial": pa.int64(), "boolean": pa.bool_(), "date": pa.date32(),
            "timestamptz": pa.timestamp("s", tz="UTC")}[tipo]


def exportar(origen: Path, destino: Path) -> dict[str, int]:
    """Escribe destino/<tabla>.parquet para cada tabla. Devuelve las filas de cada una."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("Falta pyarrow: pip install -r requirements-plataforma.txt") from None
    esq = esquema()
    t = construir(origen, esq)
    destino.mkdir(parents=True, exist_ok=True)
    resumen = {}
    for tabla, filas in sorted(t.filas.items()):
        cols = [(c, ty) for c, ty in esq[tabla] if c not in COLUMNAS_CARGA]
        datos = {}
        for n, (c, ty) in enumerate(cols):
            valores = [r[n] for r in filas]
            if ty == "date":
                valores = [dt.date.fromisoformat(v) if v else None for v in valores]
            datos[c] = pa.array(valores, type=_tipo_arrow(pa, ty))
        tmp = destino / f".{tabla}.parquet.part"
        pq.write_table(pa.table(datos), tmp, compression="zstd")
        tmp.replace(destino / f"{tabla}.parquet")
        resumen[tabla] = len(filas)
        log.info("  %-28s %9d filas", tabla, len(filas))
    return resumen
