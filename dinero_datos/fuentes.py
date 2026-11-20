#!/usr/bin/env python3
"""Fuentes: descarga de los ficheros oficiales y transformación a JSON normalizado.

Fuentes (todas del Ministerio de Hacienda):
  * IGAE   - Operaciones no financieras del Estado, serie mensual (contabilidad nacional)
  * SEPG   - Presupuestos Generales del Estado consolidados: políticas y programas de gasto
  * SGFAL  - Entregas a cuenta del sistema de financiación autonómica, por comunidad
  * SGCIEF - Presupuestos iniciales de las comunidades autónomas por política de gasto

Además (IGAE e INE):
  * IGAE   - Gasto ejecutado por función (COFOG) de cada administración y de cada comunidad
  * INE    - Población residente a 1 de enero, para los euros por habitante
  * BDNS   - Grandes beneficiarios de subvenciones y subvenciones a partidos políticos (IGAE)

Cada función fetch_* descarga los originales de una fuente (y guarda copia en raw/)
y devuelve su JSON normalizado. La orquestación está en dinero_datos/cli.py.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import openpyxl
import requests

ROOT = Path(__file__).resolve().parents[1]
# Carpetas de trabajo: por defecto dentro del repositorio; en un contenedor, en sus volúmenes.
RAW_DIR = Path(os.environ.get("DINERO_RAW") or ROOT / "raw")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 dinero-publico-datos"
)
TIMEOUT = 60

IGAE_ESTADO_URL = (
    "https://www.igae.pap.hacienda.gob.es/sitios/igae/es-ES/Contabilidad/"
    "ContabilidadNacional/Publicaciones/Documents/Estado-M/M_ESTADO_{year}.xlsx"
)
IGAE_ESTADO_PAGE = (
    "https://www.igae.pap.hacienda.gob.es/sitios/igae/es-ES/Contabilidad/"
    "ContabilidadNacional/Publicaciones/Paginas/EstadoOperacionesNF.aspx"
)
SEPG_PAGE = (
    "https://www.sepg.pap.hacienda.gob.es/sitios/sepg/es-ES/Presupuestos/"
    "DocumentacionEstadisticas/Estadisticas/Paginas/Estadisticas.aspx"
)
ENTREGAS_PAGE = (
    "https://www.hacienda.gob.es/es-es/cdi/paginas/sistemasfinanciaciondeuda/"
    "informacionccaas/informes%20financiacion%20comunidades%20autonomas1.aspx"
)
CCAA_BASE = "https://serviciostelematicosext.hacienda.gob.es/SGCIEF/PublicacionPresupuestos/aspx/"
COFOG_BASE = (
    "https://www.igae.pap.hacienda.gob.es/sitios/igae/es-ES/Contabilidad/"
    "ContabilidadNacional/Publicaciones/Paginas/"
)
# Páginas de la IGAE con la clasificación funcional (COFOG) de cada subsector.
COFOG_PAGES = {
    "central": "iacofogAC.aspx",
    "regional": "iacofogCA.aspx",
    "local": "iacofogCL.aspx",
    "seguridad_social": "iacofog.aspx",
}
COFOG_DIVISIONES = {
    "01": "Servicios públicos generales",
    "02": "Defensa",
    "03": "Orden público y seguridad",
    "04": "Asuntos económicos",
    "05": "Protección del medio ambiente",
    "06": "Vivienda y servicios comunitarios",
    "07": "Sanidad",
    "08": "Ocio, cultura y religión",
    "09": "Educación",
    "10": "Protección social",
}
# Nombres de las hojas COFOG por comunidad -> nombre corto usado en la web.
COFOG_NOMBRES = {
    "baleares": "Illes Balears",
    "castilla - la mancha": "Castilla-La Mancha",
    "región de murcia": "Murcia",
    "comunidad foral de navarra": "Navarra",
    "comunitat valenciana": "C. Valenciana",
}

# INE, Estadística Continua de Población: población residente por comunidad.
INE_API = "https://servicios.ine.es/wstempus/js/ES/"
INE_TABLA_POBLACION = 56940  # Población residente por fecha, sexo y edad (desde 1971), por comunidad
INE_PAGINA = "https://www.ine.es/jaxiT3/Tabla.htm?t=56940"
INE_NOMBRES = {
    "total nacional": "España",
    "asturias, principado de": "Asturias",
    "balears, illes": "Illes Balears",
    "castilla - la mancha": "Castilla-La Mancha",
    "comunitat valenciana": "C. Valenciana",
    "madrid, comunidad de": "Madrid",
    "murcia, región de": "Murcia",
    "navarra, comunidad foral de": "Navarra",
    "rioja, la": "La Rioja",
}

# Años de histórico que se guardan de cada fuente.
YEARS_BACK = 10

# Códigos de comunidad que usa la base de datos de presupuestos autonómicos.
CCAA = {
    "01": "Andalucía",
    "02": "Aragón",
    "03": "Asturias",
    "04": "Illes Balears",
    "05": "Canarias",
    "06": "Cantabria",
    "07": "Castilla y León",
    "08": "Castilla-La Mancha",
    "09": "Cataluña",
    "10": "Extremadura",
    "11": "Galicia",
    "12": "Madrid",
    "13": "Murcia",
    "14": "Navarra",
    "15": "País Vasco",
    "16": "La Rioja",
    "17": "C. Valenciana",
}
FORALES = {"14", "15"}

# Nombres tal y como aparecen en el Excel de entregas a cuenta -> nombre corto.
ENTREGAS_NOMBRES = {
    "cataluña": "Cataluña",
    "galicia": "Galicia",
    "andalucía": "Andalucía",
    "principado de asturias": "Asturias",
    "cantabria": "Cantabria",
    "la rioja": "La Rioja",
    "región de murcia": "Murcia",
    "c. valenciana": "C. Valenciana",
    "comunitat valenciana": "C. Valenciana",
    "comunidad valenciana": "C. Valenciana",
    "aragón": "Aragón",
    "castilla-la mancha": "Castilla-La Mancha",
    "canarias": "Canarias",
    "extremadura": "Extremadura",
    "illes balears": "Illes Balears",
    "comunidad de madrid": "Madrid",
    "castilla y león": "Castilla y León",
    "melilla": "Melilla",
    "ceuta": "Ceuta",
}

AREAS_FUNCIONALES = {
    "1": "Servicios públicos básicos",
    "2": "Protección y promoción social",
    "3": "Bienes públicos preferentes",
    "4": "Actuaciones económicas",
    "9": "Actuaciones de carácter general",
}

log = logging.getLogger("dinero_datos")


class SourceError(RuntimeError):
    """Error recuperable de una fuente concreta."""


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
class _LinkInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.hidden: dict[str, str] = {}
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._href = a["href"]
            self._text = []
        elif tag == "input" and (a.get("type") or "").lower() == "hidden" and a.get("name"):
            self.hidden[a["name"]] = a.get("value") or ""

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def parse_html(html: str) -> _LinkInputParser:
    p = _LinkInputParser()
    p.feed(html)
    return p


def is_xlsx(content: bytes) -> bool:
    return content[:2] == b"PK"


class Downloader:
    """Descarga con reintentos y, opcionalmente, guarda una copia en raw/."""

    def __init__(self, offline_dir: Path | None, save_raw: bool = True, delay: float = 1.0):
        self.offline_dir = offline_dir
        self.save_raw = save_raw and offline_dir is None
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last: Exception | None = None
        for attempt in range(1, 4):
            try:
                r = self.session.request(method, url, timeout=TIMEOUT, **kw)
                time.sleep(self.delay)
                return r
            except requests.RequestException as e:  # red, DNS, timeout...
                last = e
                log.warning("  intento %d fallido para %s: %s", attempt, url, e)
                time.sleep(5 * attempt)
        raise SourceError(f"No se pudo conectar con {url}: {last}")

    def html(self, url: str) -> str:
        r = self._request("GET", url)
        if r.status_code != 200:
            raise SourceError(f"{url} respondió {r.status_code}")
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    def xlsx(self, url: str, raw_name: str, *, missing_ok: bool = False, **kw) -> bytes | None:
        """Devuelve el contenido del Excel, o None si no existe y missing_ok."""
        if self.offline_dir is not None:
            path = self.offline_dir / raw_name
            if path.exists():
                return path.read_bytes()
            if missing_ok:
                return None
            raise SourceError(f"No existe {path} en modo offline")
        method = kw.pop("method", "GET")
        r = self._request(method, url, **kw)
        if r.status_code == 404 and missing_ok:
            return None
        if r.status_code != 200 or not is_xlsx(r.content):
            if missing_ok and r.status_code in (403, 404):
                return None
            raise SourceError(
                f"{url} no devolvió un Excel (HTTP {r.status_code}, {r.headers.get('content-type')})"
            )
        if self.save_raw:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_DIR / raw_name).write_bytes(r.content)
        return r.content


# --------------------------------------------------------------------------- #
# Utilidades de parseo
# --------------------------------------------------------------------------- #
def load_wb(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content), data_only=True)


def num(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def sheet_title(ws) -> str:
    """Primer texto no vacío de la hoja (su título)."""
    for r in ws.iter_rows(max_row=5, values_only=True):
        for v in r:
            if v not in (None, ""):
                return clean(v)
    return ""


def cell(r, i):
    return r[i] if r is not None and i < len(r) else None


def clean(s) -> str:
    return " ".join(str(s or "").split())


def r2(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


# --------------------------------------------------------------------------- #
# 1. IGAE: operaciones no financieras del Estado, serie mensual
# --------------------------------------------------------------------------- #
SALDOS = {"B.9", "SALDO PRIMARIO", "B.8g"}


def parse_estado(content: bytes) -> dict:
    wb = load_wb(content)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    anio, provisional, actualizado = None, False, None
    for r in rows[:6]:
        t = clean(r[0]) if r else ""
        m = re.search(r"Año\s+(\d{4})(\(P\))?", t)
        if m:
            anio, provisional = int(m.group(1)), bool(m.group(2))
        m = re.search(r"actualizaci[oó]n:\s*(\d{1,2}/\d{1,2}/\d{4})", t, re.I)
        if m:
            d, mth, y = m.group(1).split("/")
            actualizado = f"{y}-{int(mth):02d}-{int(d):02d}"

    hdr = next(i for i, r in enumerate(rows) if clean(cell(r, 1)).upper() == "CONCEPTOS")
    meses_all = [clean(v) for v in rows[hdr][2:] if v]

    partidas, bloque = [], None
    for r in rows[hdr + 1 :]:
        codigo, concepto = clean(cell(r, 0)), clean(cell(r, 1))
        if not codigo and not concepto:
            continue
        if concepto.lower().startswith("pro-memoria") or codigo.lower().startswith("pro-memoria"):
            break
        if codigo.lower().startswith("fuente"):
            break
        vals = [num(v) for v in r[2 : 2 + len(meses_all)]]
        if not concepto and codigo:  # filas de cabecera escritas en la columna A
            concepto, codigo = codigo, ""
        up = concepto.upper()
        if up.startswith("RECURSOS NO FINANCIEROS"):
            bloque, nivel = "recursos", 0
        elif up.startswith("EMPLEOS NO FINANCIEROS"):
            bloque, nivel = "empleos", 0
        elif up.startswith(("RECURSOS CORRIENTES", "RECURSOS DE CAPITAL", "EMPLEOS CORRIENTES", "EMPLEOS DE CAPITAL")):
            nivel = 1
        elif codigo in SALDOS or up.startswith("SALDO PRIMARIO"):
            bloque, nivel = "saldos", 0
            codigo = codigo or "SALDO PRIMARIO"
        else:
            nivel = 2
        if all(v is None for v in vals):
            continue
        partidas.append(
            {
                "codigo": codigo,
                "concepto": concepto[:1] + concepto[1:].lower() if concepto.isupper() else concepto,
                "bloque": bloque,
                "nivel": nivel,
                "valores": vals,
            }
        )

    # Meses con dato: los que tiene el total de recursos.
    total = next(p for p in partidas if p["bloque"] == "recursos" and p["nivel"] == 0)
    n = max((i + 1 for i, v in enumerate(total["valores"]) if v is not None), default=0)
    if n == 0:
        raise SourceError("El Excel del Estado no tiene ningún mes con datos")
    for p in partidas:
        p["valores"] = [r2(v, 1) for v in p["valores"][:n]]

    pib = None
    if len(wb.worksheets) > 1:
        for r in wb.worksheets[1].iter_rows(values_only=True):
            vals = [v for v in (r or ()) if v not in (None, "")]
            if len(vals) >= 2 and clean(vals[0]).upper() == "PIB":
                pib = num(vals[1])
    return {
        "anio": anio,
        "provisional": provisional,
        "actualizado": actualizado,
        "unidad": "millones de euros, acumulado desde enero",
        "meses": meses_all[:n],
        "pib": pib,
        "partidas": partidas,
    }


def fetch_estado(dl: Downloader, years: list[int]) -> dict:
    out = []
    for y in years:
        url = IGAE_ESTADO_URL.format(year=y)
        content = dl.xlsx(url, f"M_ESTADO_{y}.xlsx", missing_ok=True)
        if content is None:
            log.info("  Estado %s: aún no publicado", y)
            continue
        d = parse_estado(content)
        d["url"] = url
        out.append(d)
        log.info("  Estado %s: %d meses, %d partidas", d["anio"], len(d["meses"]), len(d["partidas"]))
    if not out:
        raise SourceError("No se encontró ningún año de la serie mensual del Estado")
    out.sort(key=lambda d: d["anio"], reverse=True)
    return {"fuente": IGAE_ESTADO_PAGE, "anios": out}


# --------------------------------------------------------------------------- #
# 2. SEPG: PGE consolidados, políticas y programas de gasto
# --------------------------------------------------------------------------- #
def _header_cols(row) -> list[tuple[int, str]]:
    return [(i, clean(v)) for i, v in enumerate(row) if re.fullmatch(r"\d{4}(-P)?", clean(v))]


def parse_pge(content: bytes) -> dict:
    wb = load_wb(content)
    # Programas (hoja 1.6): filas de programa y filas de subtotal "11 JUSTICIA".
    ws = next(s for s in wb.worksheets if sheet_title(s).startswith("1.6"))
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    h = next(i for i, r in enumerate(rows) if r and clean(r[0]).lower().startswith("programas"))
    cols = _header_cols(rows[h])
    labels = [c for _, c in cols]

    politicas, pendientes = [], []
    for r in rows[h + 1 :]:
        a, b = clean(cell(r, 0)), clean(cell(r, 1))
        vals = {lab: r2(num(cell(r, i)), 2) for i, lab in cols}
        if a and b:
            pendientes.append({"codigo": a, "programa": b, "valores": vals})
            continue
        m = re.fullmatch(r"(\d{2})\s+(.+)", b) if not a else None
        if m:
            nombre = m.group(2).strip()
            politicas.append(
                {
                    "codigo": m.group(1),
                    "politica": nombre[:1] + nombre[1:].lower(),
                    "valores": vals,
                    "programas": [p for p in pendientes if any(v for v in p["valores"].values())],
                }
            )
            pendientes = []

    # Nombres "bonitos" y total de la hoja 1.4, si coinciden en número.
    total = None
    ws14 = next((s for s in wb.worksheets if sheet_title(s).startswith("1.4")), None)
    if ws14 is not None:
        rows14 = [list(r) for r in ws14.iter_rows(values_only=True)]
        h14 = next(i for i, r in enumerate(rows14) if r and clean(r[0]).lower().startswith("pol"))
        cols14 = _header_cols(rows14[h14])
        nombres = []
        for r in rows14[h14 + 1 :]:
            a = clean(cell(r, 0))
            if not a or a.lower().startswith("fuente"):
                break
            if a.upper().startswith("CAPÍTULOS") or a.upper().startswith("CAPITULOS"):
                total = {lab: r2(num(cell(r, i)), 2) for i, lab in cols14}
                break
            nombres.append(a)
        # La hoja 1.4 escribe los nombres con mayúsculas correctas; se emparejan
        # por el comienzo del nombre (la 1.4 puede desdoblar alguna política).
        def norm(t: str) -> str:
            t = t.lower()
            for a, b in zip("áéíóúü", "aeiouu"):
                t = t.replace(a, b)
            return re.sub(r"[^a-z]", "", t)

        for p in politicas:
            clave = norm(p["politica"])[:14]
            match = [n for n in nombres if norm(n).startswith(clave)]
            if len(match) == 1:
                p["politica"] = match[0]
    if not politicas:
        raise SourceError("No se encontraron políticas de gasto en el Excel de la SEPG")
    return {"columnas": labels, "total": total, "politicas": politicas}


def fetch_pge(dl: Downloader) -> dict:
    if dl.offline_dir is not None:
        files = sorted(dl.offline_dir.glob("pge_consolidados_*.xlsx"), reverse=True)
        if not files:
            raise SourceError("No hay pge_consolidados_*.xlsx en modo offline")
        etiqueta = files[0].stem.replace("pge_consolidados_", "")
        url, content = SEPG_PAGE, files[0].read_bytes()
    else:
        page = parse_html(dl.html(SEPG_PAGE))
        cands = []
        for href, _ in page.links:
            if re.search(r"01%20Presupuestos%20Generales%20del%20Estado%20Consolidados\.xlsx$", href, re.I) or \
               re.search(r"01 Presupuestos Generales del Estado Consolidados\.xlsx$", href, re.I):
                m = re.search(r"/Documents/(\d{4}(?:-P)?)/", href)
                if m:
                    cands.append((m.group(1), urljoin(SEPG_PAGE, href)))
        if not cands:
            raise SourceError("No se encontró el Excel de PGE consolidados en la página de la SEPG")
        # El más reciente: mayor año; a igualdad, la versión sin prorrogar no existe a la vez.
        cands.sort(key=lambda c: (int(c[0][:4]), c[0].endswith("-P") is False), reverse=True)
        etiqueta, url = cands[0]
        content = dl.xlsx(url, f"pge_consolidados_{etiqueta}.xlsx")
    d = parse_pge(content)
    d.update({"etiqueta": etiqueta, "prorrogado": etiqueta.endswith("-P"), "url": url, "fuente": SEPG_PAGE})
    log.info("  PGE %s: %d políticas", etiqueta, len(d["politicas"]))
    return d


# --------------------------------------------------------------------------- #
# 3. Entregas a cuenta del sistema de financiación autonómica
# --------------------------------------------------------------------------- #
def parse_entregas(content: bytes) -> dict:
    wb = load_wb(content)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    titulo = " ".join(clean(r[0]) for r in rows[:4] if r and r[0])
    h = next(i for i, r in enumerate(rows) if r and clean(r[0]).lower().startswith("comunidad"))
    hdr = [clean(v).lower() for v in rows[h]]

    def col(pred):
        for i, t in enumerate(hdr):
            if pred(t):
                return i
        return None

    c = {
        "irpf": col(lambda t: "irpf" in t),
        "iva": col(lambda t: "valor añadido" in t),
        "impuestos_especiales": col(lambda t: t.startswith("total ii.ee")),
        "fondo_suficiencia": col(lambda t: "suficiencia" in t),
        "fondo_garantia": col(lambda t: "garantía" in t or "garantia" in t),
        "total": col(lambda t: t.startswith("total entregas a cuenta") and "impuestos" not in t),
    }
    if c["total"] is None:
        c["total"] = len(hdr) - 1 - hdr[::-1].index(next(t for t in hdr[::-1] if t))
    filas = []
    for r in rows[h + 1 :]:
        nombre = clean(cell(r, 0))
        if not nombre:
            continue
        low = nombre.lower()
        if low.startswith("total general") or low.startswith("fuente"):
            break
        if low.startswith("total"):
            continue
        corto = ENTREGAS_NOMBRES.get(low.strip(), nombre.strip())
        fila = {"comunidad": corto}
        for k, i in c.items():
            fila[k] = r2(num(cell(r, i)) if i is not None else None, 2)
        filas.append(fila)
    if not filas:
        raise SourceError("El Excel de entregas a cuenta no tiene filas de comunidades")
    m = re.search(r"Real Decreto[- ]Ley[^)]*|Ley[^)]*", titulo)
    return {"norma": m.group(0).strip() if m else None, "filas": filas}


def fetch_entregas(dl: Downloader, max_years: int = YEARS_BACK) -> dict:
    anios = []
    if dl.offline_dir is not None:
        found = []
        for f in dl.offline_dir.glob("entregas-a-cuenta-*.xlsx"):
            m = re.search(r"(\d{4})", f.name)
            if m:
                found.append((int(m.group(1)), f.name, ENTREGAS_PAGE))
    else:
        page = parse_html(dl.html(ENTREGAS_PAGE))
        found, seen = [], set()
        for href, _ in page.links:
            # Los nombres cambian según el año: entregas-a-cuenta-2026.xlsx,
            # entrega_a_cuenta_2021.xlsx, financiacion_entregas_a_cuenta_2019.xlsx…
            m = re.search(r"entregas?[-_]a[-_]cuenta[-_](\d{4})[^/]*\.xlsx$", href, re.I)
            if m and int(m.group(1)) not in seen:
                seen.add(int(m.group(1)))
                found.append((int(m.group(1)), f"entregas-a-cuenta-{m.group(1)}.xlsx", urljoin(ENTREGAS_PAGE, href)))
    found.sort(reverse=True)
    for year, raw_name, url in found[:max_years]:
        content = dl.xlsx(url, raw_name)
        d = parse_entregas(content)
        d.update({"anio": year, "url": url})
        anios.append(d)
        log.info("  Entregas %s: %d filas", year, len(d["filas"]))
    if not anios:
        raise SourceError("No se encontró ningún Excel de entregas a cuenta")
    return {"fuente": ENTREGAS_PAGE, "anios": anios}


# --------------------------------------------------------------------------- #
# 4. Presupuestos de las comunidades autónomas por política de gasto
# --------------------------------------------------------------------------- #
def parse_funcional(content: bytes) -> dict:
    """Presupuesto por política de gasto.

    Acepta la «Clasificación funcional» (una columna de importe) y la
    «Clasificación funcional por capítulos» (una columna por capítulo y un total);
    en este segundo caso cada política lleva su reparto por capítulos.
    """
    wb = load_wb(content)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    anio = None
    for r in rows[:12]:
        m = re.search(r"Ejercicio\s+(\d{4})", clean(r[0]) if r else "")
        if m:
            anio = int(m.group(1))
    # El título del documento también empieza por «Áreas y políticas…»: la cabecera
    # de la tabla es la última fila así antes de los datos.
    cands = [i for i, r in enumerate(rows[:25]) if r and clean(r[0]).lower().startswith("áreas y pol")]
    if not cands:
        raise SourceError("Formato inesperado en el Excel de presupuestos autonómicos")
    h = cands[-1]
    etiquetas = [(i, clean(v)) for i, v in enumerate(rows[h]) if i > 0 and clean(v) and clean(v) != "None"]
    col_total = next((i for i, t in etiquetas if t.lower() == "total"), 1)
    caps = [(i, t) for i, t in etiquetas if i != col_total] if len(etiquetas) > 1 else []
    politicas, total = [], None
    for r in rows[h + 1 :]:
        a = clean(cell(r, 0))
        if not a:
            continue
        v = num(cell(r, col_total))
        if a.lower().startswith("total"):
            total = v
            break
        m = re.fullmatch(r"(\d{1,2})\.\s*(.+)", a)
        if not m or len(m.group(1)) != 2 or v is None:
            continue
        p = {
            "codigo": m.group(1),
            "politica": m.group(2).strip(),
            "area": AREAS_FUNCIONALES.get(m.group(1)[0], "Otras"),
            # El Excel da miles de euros; lo pasamos a millones.
            "importe": r2(v / 1000, 2),
        }
        if caps:
            p["capitulos"] = [r2((num(cell(r, i)) or 0) / 1000, 2) for i, _ in caps]
        politicas.append(p)
    out = {"anio": anio, "total": r2(total / 1000, 2) if total is not None else None, "politicas": politicas}
    if caps:
        out["capitulos"] = [t for _, t in caps]
    return out


def parse_gastos(content: bytes) -> dict:
    """Desglose económico de los gastos: capítulo, artículo, concepto y subconcepto."""
    wb = load_wb(content)
    rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    partidas, total = [], None
    for r in rows:
        a = str(cell(r, 0) or "")
        v = num(cell(r, 1))
        if clean(a).lower().startswith("total gastos"):
            total = v
            break
        m = re.fullmatch(r"\s*(\d{1,4}|\dt)\.\s*(.+?)\s*", a)
        if not m or v is None or v == 0:
            continue
        partidas.append({"codigo": m.group(1), "nombre": m.group(2), "importe": r2(v / 1000, 2)})
    if not partidas or total is None:
        raise SourceError("Formato inesperado en el desglose de gastos autonómico")
    caps = sum(p["importe"] for p in partidas if len(p["codigo"]) == 1)
    if abs(caps - total / 1000) > 1:
        raise SourceError(f"El desglose de gastos no cuadra: capítulos {caps:.0f} frente a total {total / 1000:.0f}")
    return {"total": r2(total / 1000, 2), "partidas": partidas}


class CcaaSession:
    """La aplicación de Hacienda exige abrir sesión antes de descargar."""

    # Tipo de descarga -> prefijo del fichero guardado en raw/.
    TIPOS = {"FuncionalCapDC": "funcional", "GastosDC": "gastos"}

    def __init__(self, dl: Downloader):
        self.dl = dl
        self.ready = False
        self.clave = None

    def start(self, year: int, tipo: str) -> None:
        s = self.dl
        s._request("GET", CCAA_BASE + "inicio.aspx")
        page = parse_html(s.html(CCAA_BASE + "SelDescargaDC.aspx"))
        data = dict(page.hidden)
        data.update(
            {
                "ctl00$MainContent$ano": str(year),
                "ctl00$MainContent$autonomia": "00",
                "ctl00$MainContent$tipoDescarga": f"../aspx/Descarga{tipo}.aspx?cdcdad=",
                "ctl00$MainContent$botonAceptar.x": "5",
                "ctl00$MainContent$botonAceptar.y": "5",
            }
        )
        s._request("POST", CCAA_BASE + "SelDescargaDC.aspx", data=data)
        self.ready, self.clave = True, (year, tipo)

    def get(self, code: str, year: int, tipo: str = "FuncionalCapDC") -> bytes | None:
        raw = f"{self.TIPOS[tipo]}_{code}_{year}.xlsx"
        if self.dl.offline_dir is not None:
            return self.dl.xlsx("", raw, missing_ok=True)
        url = f"{CCAA_BASE}Descarga{tipo}.aspx?cdcdad={code}&ano={year}"
        for intento in range(2):
            if not self.ready or self.clave != (year, tipo):
                self.start(year, tipo)
            try:
                return self.dl.xlsx(url, raw)
            except SourceError:
                if intento == 0:  # la sesión puede haber caducado
                    self.ready = False
                    continue
                raise
        return None


def fetch_ccaa(dl: Downloader, years: list[int], previo: dict | None = None, reuse_before: int | None = None) -> dict:
    """Presupuestos por política de cada comunidad.

    Los presupuestos iniciales de años cerrados no cambian: los años anteriores a
    `reuse_before` se toman de `previo` (el JSON ya guardado) si están completos,
    para no repetir cientos de descargas cada día.
    """
    sess = CcaaSession(dl)
    previo = previo or {}
    guardados = {a["anio"]: a for a in previo.get("anios", [])}
    capitulos = previo.get("capitulos")
    economica = dict(previo.get("economica", {}))

    def completo(a):
        cs = a.get("comunidades", [])
        return len(cs) >= len(CCAA) and all("gastos" in c and "capitulos" in c["politicas"][0] for c in cs)

    out = []
    for y in years:
        if reuse_before is not None and y < reuse_before and completo(guardados.get(y, {})):
            out.append(guardados[y])
            log.info("  CCAA %s: reutilizado", y)
            continue
        comunidades = []
        for code, nombre in CCAA.items():
            try:
                content = sess.get(code, y)
            except SourceError as e:
                log.warning("  %s %s: %s", nombre, y, e)
                continue
            if content is None:
                continue
            d = parse_funcional(content)
            if not d["politicas"] or d["total"] is None:
                continue
            capitulos = d.get("capitulos") or capitulos
            comunidades.append(
                {"codigo": code, "comunidad": nombre, "foral": code in FORALES, "total": d["total"], "politicas": d["politicas"]}
            )
        # Desglose económico (segunda pasada: la aplicación pide abrir sesión por tipo de descarga).
        for c in comunidades:
            try:
                content = sess.get(c["codigo"], y, "GastosDC")
                g = parse_gastos(content) if content else None
            except SourceError as e:
                log.warning("  %s %s (desglose): %s", c["comunidad"], y, e)
                g = None
            if g:
                for p in g["partidas"]:
                    economica.setdefault(p["codigo"], p["nombre"])
                c["gastos"] = {p["codigo"]: p["importe"] for p in g["partidas"]}
        if comunidades:
            out.append({"anio": y, "comunidades": comunidades})
            log.info("  CCAA %s: %d comunidades, %d con desglose", y, len(comunidades), sum("gastos" in c for c in comunidades))
    if not out:
        raise SourceError("No se pudo descargar ningún presupuesto autonómico")
    out.sort(key=lambda a: a["anio"], reverse=True)
    return {
        "fuente": CCAA_BASE + "inicio.aspx",
        "unidad": "millones de euros",
        "capitulos": capitulos,
        "economica": dict(sorted(economica.items(), key=lambda kv: (kv[0].replace("t", "~"),))),
        "anios": out,
    }


# --------------------------------------------------------------------------- #
# 5. IGAE: gasto ejecutado por función (COFOG), por subsector y por comunidad
# --------------------------------------------------------------------------- #
def _cofog_tabla(rows: list[list]) -> dict:
    """Lee una tabla COFOG: la fila «GASTO TOTAL» repartida por divisiones.

    Sirve para las hojas por comunidad (solo divisiones) y para las series
    (divisiones con sus grupos: se usan las columnas «Total 01» y el grupo 01.8,
    «Transferencias de carácter general entre administraciones públicas»).
    """
    def es_total(r):
        return any(clean(cell(r, i)).upper() == "GASTO TOTAL" for i in (0, 1))

    t = next((i for i, r in enumerate(rows) if es_total(r)), None)
    if t is None:
        raise SourceError("Tabla COFOG sin fila «GASTO TOTAL»")
    fila = rows[t]
    anio, provisional = None, False
    for r in rows[:t]:
        m = re.fullmatch(r"(\d{4})\s*(\(P\))?", clean(cell(r, 0)))
        if m:
            anio, provisional = int(m.group(1)), bool(m.group(2))
    divs, total, grupo018 = {}, None, None
    for r in rows[max(0, t - 3) : t]:
        for i, v in enumerate(r):
            s = clean(v)
            m = re.match(r"(?:Total\s+)?(\d{2})\.?\s*(?:\D|$)", s)
            if s.upper() == "TOTAL":
                total = num(cell(fila, i))
            elif re.fullmatch(r"Total\s+\d{2}", s):
                divs[s[-2:]] = num(cell(fila, i))
            elif s.startswith("01.8"):
                grupo018 = num(cell(fila, i))
            elif m and not re.match(r"\d{2}\.\d", s) and s[:2] not in divs:
                divs[m.group(1)] = num(cell(fila, i))
    divs = {k: r2(v, 1) for k, v in divs.items() if k in COFOG_DIVISIONES and v is not None}
    if len(divs) < 8:
        raise SourceError(f"Tabla COFOG con columnas inesperadas: {sorted(divs)}")
    if total is None:
        total = sum(divs.values())
    out = {"anio": anio, "provisional": provisional, "total": r2(total, 1), "divisiones": divs}
    if grupo018 is not None:
        out["transferencias_aapp"] = r2(grupo018, 1)
    return out


def parse_cofog_serie(content: bytes, desde: int | None = None) -> list[dict]:
    """Serie anual de un subsector (una hoja por año)."""
    wb = load_wb(content)
    out = []
    for ws in wb.worksheets:
        if not re.fullmatch(r"\d{4}", ws.title.strip()):
            continue
        if desde is not None and int(ws.title) < desde:
            continue
        d = _cofog_tabla([list(r) for r in ws.iter_rows(max_row=12, values_only=True)])
        d["anio"] = d["anio"] or int(ws.title)
        out.append(d)
    if not out:
        raise SourceError("La serie COFOG no tiene hojas de años")
    return sorted(out, key=lambda d: d["anio"])


def parse_cofog_detalle(content: bytes) -> dict:
    """Detalle por comunidad de un año (una hoja por comunidad)."""
    wb = load_wb(content)
    filas, anio, provisional = [], None, False
    for ws in wb.worksheets:
        if not ws.title.lower().startswith("tabla"):
            continue
        rows = [list(r) for r in ws.iter_rows(max_row=12, values_only=True)]
        nombre = clean(cell(rows[0], 0))
        if nombre.upper().startswith("ADMINISTRACI"):  # tabla del conjunto de comunidades
            continue
        d = _cofog_tabla(rows)
        anio, provisional = d["anio"] or anio, d["provisional"] or provisional
        corto = COFOG_NOMBRES.get(nombre.lower(), nombre)
        filas.append({"comunidad": corto, "foral": corto in ("Navarra", "País Vasco"), "total": d["total"], "divisiones": d["divisiones"]})
    if len(filas) < 17:
        raise SourceError(f"El detalle COFOG por comunidad solo tiene {len(filas)} comunidades")
    return {"anio": anio, "provisional": provisional, "filas": filas}


def _cofog_links(dl: Downloader, page: str) -> list[tuple[str, str]]:
    p = parse_html(dl.html(COFOG_BASE + page))
    return [(urljoin(COFOG_BASE + page, h), t) for h, t in p.links if re.search(r"\.xlsx$", h, re.I)]


def fetch_cofog(dl: Downloader, desde: int) -> dict:
    series = {}
    for sub, page in COFOG_PAGES.items():
        raw = f"cofog_serie_{sub}.xlsx"
        if dl.offline_dir is not None:
            content = dl.xlsx("", raw, missing_ok=True)
            url = COFOG_BASE + page
        else:
            links = [(u, t) for u, t in _cofog_links(dl, page) if "serie" in t.lower() and "detalle" not in u.lower()]
            if not links:
                log.warning("  COFOG %s: no se encontró la serie", sub)
                continue
            url = links[0][0]
            content = dl.xlsx(url, raw)
        if content is None:
            continue
        series[sub] = parse_cofog_serie(content, desde)
        log.info("  COFOG %s: %d–%d", sub, series[sub][0]["anio"], series[sub][-1]["anio"])
    if "central" not in series or "regional" not in series:
        raise SourceError("Faltan las series COFOG de la Administración central o regional")

    detalle = []
    if dl.offline_dir is not None:
        found = [(int(m.group(1)), f.name) for f in dl.offline_dir.glob("COFOG_A_Detalle_CCAA_*.xlsx")
                 for m in [re.search(r"(\d{4})", f.name)] if m]
        found = [(y, "", n) for y, n in found]
    else:
        found = []
        for u, _ in _cofog_links(dl, COFOG_PAGES["regional"]):
            m = re.search(r"COFOG_A_Detalle_CCAA_(\d{4})\.xlsx$", u, re.I)
            if m:
                found.append((int(m.group(1)), u, f"COFOG_A_Detalle_CCAA_{m.group(1)}.xlsx"))
    for y, url, raw in sorted(set(found), reverse=True):
        if y < desde:
            continue
        d = parse_cofog_detalle(dl.xlsx(url, raw))
        d["anio"] = d["anio"] or y
        detalle.append(d)
        log.info("  COFOG por comunidad %s: %d comunidades", d["anio"], len(d["filas"]))
    return {
        "fuente": COFOG_BASE + COFOG_PAGES["regional"],
        "fuente_central": COFOG_BASE + COFOG_PAGES["central"],
        "unidad": "millones de euros, gasto ejecutado (contabilidad nacional)",
        "divisiones": COFOG_DIVISIONES,
        "subsectores": series,
        "comunidades": sorted(detalle, key=lambda d: d["anio"], reverse=True),
    }


# --------------------------------------------------------------------------- #
# 6. INE: población residente a 1 de enero, por comunidad
# --------------------------------------------------------------------------- #
def series_poblacion(tabla: list[dict]) -> dict[str, str]:
    """De la tabla del INE, el código de la serie «total, todas las edades» de cada territorio."""
    out = {}
    for s in tabla:
        partes = [clean(p) for p in s.get("Nombre", "").split(".")]
        if "Todas las edades" not in partes or "Hombres" in partes or "Mujeres" in partes:
            continue
        territorio = next((p for p in partes if p and p not in ("Total", "Todas las edades", "Población", "Número")), None)
        if territorio:
            out[INE_NOMBRES.get(territorio.lower(), territorio)] = s["COD"]
    return out


def parse_serie_poblacion(serie: dict, desde: int) -> tuple[dict[str, int], list[str]]:
    """Valores a 1 de enero (periodo 19 del INE) por año; y los años provisionales."""
    valores, provisionales = {}, []
    for x in serie.get("Data", []):
        if x.get("FK_Periodo") != 19 or x.get("Valor") is None or x["Anyo"] < desde:
            continue
        valores[str(x["Anyo"])] = int(x["Valor"])
        if x.get("FK_TipoDato") == 2:
            provisionales.append(str(x["Anyo"]))
    return valores, provisionales


def fetch_poblacion(dl: Downloader, desde: int) -> dict:
    if dl.offline_dir is not None:
        raise SourceError("La población se consulta en la API del INE; no hay modo offline")

    def get_json(url):
        r = dl._request("GET", url)
        if r.status_code != 200:
            raise SourceError(f"{url} respondió {r.status_code}")
        return r.json()

    codigos = series_poblacion(get_json(f"{INE_API}DATOS_TABLA/{INE_TABLA_POBLACION}?nult=1"))
    faltan = [n for n in list(CCAA.values()) + ["España"] if n not in codigos]
    if faltan:
        raise SourceError(f"El INE no devolvió la población de: {', '.join(faltan)}")
    territorios, provisionales = {}, set()
    for nombre, cod in sorted(codigos.items()):
        valores, prov = parse_serie_poblacion(get_json(f"{INE_API}DATOS_SERIE/{cod}?nult=120"), desde)
        if valores:
            territorios[nombre] = valores
            provisionales.update(prov)
    log.info("  Población: %d territorios, %s–%s", len(territorios), min(territorios["España"]), max(territorios["España"]))
    return {
        "fuente": INE_PAGINA,
        "fecha": "1 de enero de cada año",
        "provisionales": sorted(provisionales),
        "territorios": territorios,
    }


# --------------------------------------------------------------------------- #
# 7. BDNS: grandes beneficiarios de subvenciones y subvenciones a partidos
# --------------------------------------------------------------------------- #
BDNS_API = "https://www.infosubvenciones.es/bdnstrans/api/"
BDNS_WEB = "https://www.infosubvenciones.es/bdnstrans/GE/es/"
BDNS_ORIGEN = "Intervención General de la Administración del Estado"
BDNS_UMBRAL = 100_000  # «grandes beneficiarios»: ayuda equivalente total en el año ≥ 100.000 €
BDNS_PAGINA = 10_000
BDNS_TOP = 100  # beneficiarios por año en el fichero principal; la lista completa va aparte
BDNS_TOP_MOTIVOS = 1000  # beneficiarios por año de los que se consultan sus concesiones (el motivo)
BDNS_MAX_PETICIONES = 2500  # consultas de motivos por ejecución, para no abusar de la API
# De cada beneficiario se pide el detalle (finalidad, procedimiento, fondos) de las convocatorias que
# suman este porcentaje de lo que recibió; las demás (muchas, de importe pequeño) quedan con su título.
BDNS_COBERTURA_DETALLE = 0.98

# Tipo de entidad según la primera letra del NIF (Orden EHA/451/2008).
NIF_TIPOS = {
    "A": "Sociedades anónimas", "B": "Sociedades limitadas", "C": "Sociedades colectivas",
    "D": "Sociedades comanditarias", "E": "Comunidades de bienes", "F": "Cooperativas",
    "G": "Asociaciones y fundaciones", "H": "Comunidades de propietarios", "J": "Sociedades civiles",
    "N": "Entidades extranjeras", "P": "Ayuntamientos y entidades locales", "Q": "Organismos públicos",
    "R": "Entidades religiosas", "S": "Órganos de la Administración", "U": "Uniones temporales de empresas",
    "V": "Otras entidades", "W": "Establecimientos de no residentes",
    "fisica": "Personas físicas", "otro": "Otros identificadores (sobre todo extranjeros)",
}
PERSONA_FISICA = "Persona física (nombre no publicado)"
_DNI_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"


def es_persona_fisica(nif: str) -> bool:
    """NIF de persona física: DNI o NIE con letra de control válida, o NIF K/L/M.

    Ante un número de 8 cifras sin letra se asume también persona física, por prudencia.
    """
    nif = nif.upper().replace("-", "")
    if re.fullmatch(r"\d{8}", nif) or re.fullmatch(r"[KLM]\d{7}[A-Z0-9]", nif):
        return True
    m = re.fullmatch(r"([XYZ]?)(\d{7,8})([A-Z])", nif)
    if not m:
        return False
    pre, digitos, letra = m.groups()
    if pre:
        if len(digitos) != 7:
            return False
        digitos = str("XYZ".index(pre)) + digitos
    return _DNI_LETRAS[int(digitos) % 23] == letra


def tipo_nif(nif: str) -> str:
    if not nif or es_persona_fisica(nif):
        return "fisica"
    c = nif[:1].upper()
    return c if c in NIF_TIPOS and len(c) == 1 and not c.isdigit() else "otro"


def separar_beneficiario(texto: str) -> tuple[str, str]:
    """«B12345678 NOMBRE, S.L.» → («B12345678», «NOMBRE, S.L.»). Las personas físicas se disocian."""
    nif, _, nombre = (texto or "").strip().partition(" ")
    if not nombre:
        nif, nombre = "", nif
    if tipo_nif(nif) == "fisica":
        return "", PERSONA_FISICA
    return nif.upper(), clean(nombre)


def _bdns_get(dl: Downloader, ruta: str, **params) -> dict | list:
    r = dl._request("GET", BDNS_API + ruta, params={"vpd": "GE", **params})
    if r.status_code != 200:
        raise SourceError(f"{BDNS_API}{ruta} respondió {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise SourceError(f"{BDNS_API}{ruta} no devolvió JSON") from e


def _bdns_todo(dl: Downloader, ruta: str, clave_id: str, **params) -> tuple[list[dict], int]:
    """Todas las páginas de una búsqueda; devuelve (filas sin duplicados, total que declara la API)."""
    filas, vistos, total, pagina = [], set(), 0, 0
    while True:
        d = _bdns_get(dl, ruta, page=pagina, pageSize=BDNS_PAGINA, **params)
        total = d.get("totalElements", 0)
        for x in d.get("content", []):
            if x.get(clave_id) not in vistos:
                vistos.add(x.get(clave_id))
                filas.append(x)
        if d.get("last", True) or not d.get("content"):
            return filas, total
        pagina += 1


def parse_grandes_beneficiarios(filas: list[dict]) -> list[list]:
    """Filas de la API → [[nif, nombre, euros], ...] ordenadas de mayor a menor importe."""
    out = []
    for x in filas:
        nif, nombre = separar_beneficiario(x.get("beneficiario", ""))
        out.append([nif, nombre, r2(float(x.get("ayudaETotal") or 0))])
    out.sort(key=lambda b: (-b[2], b[1]))
    return out


def resumen_beneficiarios(benef: list[list]) -> dict:
    por_tipo: dict[str, list] = {}
    for nif, _, imp in benef:
        t = por_tipo.setdefault(tipo_nif(nif), [0, 0.0])
        t[0] += 1
        t[1] += imp
    total = sum(b[2] for b in benef)
    return {
        "beneficiarios": len(benef),
        "total": r2(total),
        "minimo": benef[-1][2] if benef else None,
        "por_tipo": {k: [v[0], r2(v[1])] for k, v in sorted(por_tipo.items(), key=lambda kv: -kv[1][1])},
        "top": benef[:BDNS_TOP],
    }


def parse_partidos(filas: list[dict]) -> dict:
    """Concesiones a partidos y grupos políticos de un año, agregadas por NIF y por administración."""
    por_nif: dict[str, dict] = {}
    niveles: dict[str, float] = {}
    organos: dict[tuple, float] = {}
    for x in filas:
        imp = float(x.get("importe") or 0)
        nif, nombre = separar_beneficiario(x.get("beneficiario", ""))
        b = por_nif.setdefault(nif or nombre, {"nif": nif, "nombres": {}, "importe": 0.0, "n": 0})
        b["importe"] += imp
        b["n"] += 1
        b["nombres"][nombre] = b["nombres"].get(nombre, 0) + imp
        nivel = clean(x.get("nivel1") or "") or "SIN DATO"
        niveles[nivel] = niveles.get(nivel, 0) + imp
        org = (nivel, clean(x.get("nivel2") or ""), clean(x.get("nivel3") or ""))
        organos[org] = organos.get(org, 0) + imp
    benef = [[b["nif"], max(b["nombres"], key=b["nombres"].get), r2(b["importe"]), b["n"]] for b in por_nif.values()]
    benef.sort(key=lambda b: (-b[2], b[1]))
    return {
        "concesiones": len(filas),
        "total": r2(sum(niveles.values())),
        "por_nivel": {k: r2(v) for k, v in sorted(niveles.items(), key=lambda kv: -kv[1])},
        "organos": [[*k, r2(v)] for k, v in sorted(organos.items(), key=lambda kv: -kv[1])[:25]],
        "beneficiarios": benef,
    }


SIN_CLASIFICAR = "Sin clasificar (convocatorias pequeñas)"


def procedimiento(tipo: str | None) -> str:
    """«Concesión directa - instrumental» → «Concesión directa»."""
    return clean((tipo or "").split(" - ")[0]) or "Sin información"


def agrupar_concesiones(filas: list[dict]) -> tuple[list[list], dict[str, dict]]:
    """Concesiones de un beneficiario → [[convocatoria, instrumento, euros, n], ...] y {convocatoria: {titulo, organo}}.

    Se usa la ayuda equivalente, la misma medida que el total de grandes beneficiarios.
    """
    grupos: dict[tuple, list] = {}
    titulos = {}
    for x in filas:
        num = str(x.get("numeroConvocatoria") or "")
        instr = clean(x.get("instrumento") or "") or "SIN INFORMACIÓN"
        g = grupos.setdefault((num, instr), [num, instr, 0.0, 0])
        g[2] += float(x.get("ayudaEquivalente") or 0)
        g[3] += 1
        if num and num not in titulos:
            titulos[num] = {"titulo": clean(x.get("convocatoria") or ""),
                            "organo": [clean(x.get(k) or "") for k in ("nivel1", "nivel2", "nivel3")]}
    out = [[g[0], g[1], r2(g[2]), g[3]] for g in grupos.values()]
    out.sort(key=lambda g: -g[2])
    return out, titulos


def parse_convocatoria(d: dict | None, base: dict | None = None) -> dict:
    """Detalle de una convocatoria de la API → lo que se publica de ella.

    Sin detalle (d=None) queda el título y el órgano que traen las propias concesiones.
    """
    base = base or {}
    if not d:
        return {"titulo": base.get("titulo", ""), "finalidad": None, "organo": base.get("organo") or ["", "", ""],
                "tipo": None, "mrr": None, "detalle": False}
    org = d.get("organo") or {}
    return {
        "titulo": clean(d.get("descripcion") or "") or base.get("titulo", ""),
        "finalidad": clean(d.get("descripcionFinalidad") or "") or None,
        "organo": [clean(org.get(k) or "") for k in ("nivel1", "nivel2", "nivel3")],
        "tipo": clean(d.get("tipoConvocatoria") or "") or None,
        "mrr": bool(d.get("mrr")),
        "detalle": True,
    }


def fetch_motivos(dl: Downloader, grandes: dict, previo: dict | None, convocatorias: dict,
                  max_peticiones: int = BDNS_MAX_PETICIONES) -> dict:
    """Concesiones de los mayores beneficiarios de cada año, agrupadas por convocatoria.

    Solo se vuelve a consultar un beneficiario si su total ha cambiado desde la última vez.
    `convocatorias` (número → detalle) se completa aquí con las que falten.
    """
    previo = previo or {}
    peticiones = 0
    motivos = {}
    for a in sorted(grandes, reverse=True):  # primero los años recientes
        antes = previo.get(a, {})
        actual = {}
        for nif, _, total in [b for b in grandes[a]["lista"] if b[0]][:BDNS_TOP_MOTIVOS]:
            p = antes.get(nif)
            if p and abs(p["total"] - total) < 0.5:
                actual[nif] = p
                continue
            if peticiones >= max_peticiones:
                if p:
                    actual[nif] = p  # desactualizado: se rehará en otra ejecución
                continue
            filas, _ = _bdns_todo(dl, "concesiones/busqueda", "id", nifCif=nif, fechaDesde=f"01/01/{a}", fechaHasta=f"31/12/{a}")
            peticiones += 1 + len(filas) // BDNS_PAGINA
            grupos, titulos = agrupar_concesiones(filas)
            actual[nif] = {"total": total, "c": grupos}
            suma, acumulado = sum(g[2] for g in grupos), 0.0
            for num, _, eur, _ in grupos:  # de mayor a menor importe
                if not num:
                    continue
                importante = acumulado < BDNS_COBERTURA_DETALLE * suma
                acumulado += eur
                tiene = convocatorias.get(num, {}).get("detalle", False)  # None: la BDNS no la devolvió
                if tiene is not False or (not importante or peticiones >= max_peticiones * 2):
                    convocatorias.setdefault(num, parse_convocatoria(None, titulos.get(num)))
                    continue
                r = dl._request("GET", BDNS_API + "convocatorias", params={"vpd": "GE", "numConv": num})
                peticiones += 1
                d = r.json() if r.status_code == 200 and r.content else None
                convocatorias[num] = parse_convocatoria(d, titulos.get(num)) if d else {
                    **parse_convocatoria(None, titulos.get(num)), "detalle": None}  # la BDNS no la devuelve
        motivos[a] = actual
        log.info("  Motivos %s: %d beneficiarios (%d consultas acumuladas)", a, len(actual), peticiones)
    for a, v in previo.items():
        motivos.setdefault(a, v)
    return motivos


def fetch_subvenciones(dl: Downloader, previo: dict | None = None, anio_actual: int | None = None,
                       max_peticiones: int = BDNS_MAX_PETICIONES) -> dict:
    """Grandes beneficiarios (lista completa por año) y subvenciones a partidos políticos.

    La BDNS retira las concesiones a los cuatro años; los años que ya no ofrece se
    conservan de la descarga anterior (`previo`, en el formato de unir_subvenciones).
    """
    if dl.offline_dir is not None:
        raise SourceError("La BDNS se consulta en su API; no hay modo offline")
    anios = sorted(int(a["id"]) for a in _bdns_get(dl, "grandesbeneficiarios/anios"))
    if not anios:
        raise SourceError("La BDNS no devolvió años de grandes beneficiarios")
    grandes, partidos = {}, {}
    for a in anios:
        filas, total = _bdns_todo(dl, "grandesbeneficiarios/busqueda", "idPersona", anios=a)
        if total and len(filas) < total:
            raise SourceError(f"Grandes beneficiarios {a}: {len(filas)} de {total} filas")
        grandes[str(a)] = {"total_fuente": total, "lista": parse_grandes_beneficiarios(filas)}
        filas, total = _bdns_todo(dl, "partidospoliticos/busqueda", "id", fechaDesde=f"01/01/{a}", fechaHasta=f"31/12/{a}")
        if total and len(filas) < total:
            raise SourceError(f"Partidos {a}: {len(filas)} de {total} concesiones")
        partidos[str(a)] = parse_partidos(filas)
        log.info("  BDNS %d: %d grandes beneficiarios, %d concesiones a partidos", a, len(grandes[str(a)]["lista"]), len(filas))
    if previo:
        for a, v in previo.get("grandes", {}).items():
            grandes.setdefault(a, v)
        for a, v in previo.get("partidos", {}).items():
            partidos.setdefault(a, v)
    actual = anio_actual or max(anios)
    convocatorias = dict((previo or {}).get("convocatorias", {}))
    motivos = fetch_motivos(dl, {a: grandes[a] for a in map(str, anios)}, (previo or {}).get("motivos"),
                            convocatorias, max_peticiones)
    usadas = {g[0] for m in motivos.values() for b in m.values() for g in b["c"]}
    return {
        "fuente": BDNS_WEB + "grandesbeneficiarios",
        "fuente_partidos": BDNS_WEB + "partidospoliticos",
        "api": BDNS_API,
        "origen": BDNS_ORIGEN,
        "aviso_legal": BDNS_WEB + "avisolegal",
        "disociacion": "Dinero Público no publica el nombre ni el NIF de las personas físicas: figuran como «"
                       + PERSONA_FISICA + "» y solo cuentan en los totales.",
        "umbral": BDNS_UMBRAL,
        "unidad": "euros; en grandes beneficiarios, ayuda equivalente total del año",
        "en_curso": [a for a in sorted(grandes) if int(a) >= actual],
        "tipos": NIF_TIPOS,
        "grandes": dict(sorted(grandes.items(), reverse=True)),
        "partidos": dict(sorted(partidos.items(), reverse=True)),
        "motivos": dict(sorted(motivos.items(), reverse=True)),
        "convocatorias": {k: convocatorias[k] for k in sorted(usadas) if k in convocatorias},
    }


def nombre_lista_subvenciones(anio: str) -> str:
    return f"subvenciones-{anio}.json"


def nombre_motivos_subvenciones(anio: str) -> str:
    return f"subvenciones-motivos-{anio}.json"


def resumen_motivos(motivos: dict, convocatorias: dict, total_anio: float) -> dict:
    """Para qué se dieron las ayudas de los beneficiarios consultados: sumas por finalidad, etc."""
    sumas = {k: {} for k in ("por_finalidad", "por_instrumento", "por_administracion", "por_procedimiento")}
    conv: dict[str, list] = {}
    mrr = importe = 0.0
    for b in motivos.values():
        for num, instr, eur, _ in b["c"]:
            c = convocatorias.get(num) or {}
            importe += eur
            sin = SIN_CLASIFICAR if c.get("detalle") is False else "Sin información"
            for k, v in (("por_finalidad", c.get("finalidad") or sin), ("por_instrumento", instr),
                         ("por_administracion", (c.get("organo") or [""])[0] or "Sin información"),
                         ("por_procedimiento", procedimiento(c.get("tipo")) if c.get("tipo") else sin)):
                sumas[k][v] = sumas[k].get(v, 0) + eur
            if c.get("mrr"):
                mrr += eur
            x = conv.setdefault(num, [num, 0.0, set()])
            x[1] += eur
    for nif, b in motivos.items():
        for num, *_ in b["c"]:
            conv[num][2].add(nif)
    top = sorted(conv.values(), key=lambda x: -x[1])[:30]
    return {
        "beneficiarios": len(motivos),
        # Puestos de la lista del año cuyo desglose se consulta (la web solo ofrece el desglose para ellos).
        "puestos": BDNS_TOP_MOTIVOS,
        "importe": r2(importe),
        "cobertura": round(importe / total_anio, 4) if total_anio else None,
        **{k: {n: r2(v) for n, v in sorted(s.items(), key=lambda kv: -kv[1])} for k, s in sumas.items()},
        "mrr": r2(mrr),
        "convocatorias": [[n, (convocatorias.get(n) or {}).get("titulo", ""), r2(e), len(s)] for n, e, s in top],
    }


def partir_subvenciones(obj: dict) -> dict[str, dict]:
    """El JSON completo → fichero principal (resúmenes), una lista completa por año y,
    por año, las concesiones de los mayores beneficiarios agrupadas por convocatoria."""
    principal = {k: v for k, v in obj.items() if k not in ("grandes", "motivos", "convocatorias")}
    principal["grandes"] = {}
    ficheros = {}
    convs = obj.get("convocatorias", {})
    for a, g in obj["grandes"].items():
        nombre = nombre_lista_subvenciones(a)
        res = resumen_beneficiarios(g["lista"])
        principal["grandes"][a] = {"total_fuente": g["total_fuente"], "lista": nombre, **res}
        ficheros[nombre] = {"anio": int(a), "origen": obj["origen"], "unidad": obj["unidad"],
                            "campos": ["nif", "nombre", "euros"], "beneficiarios": g["lista"]}
        m = obj.get("motivos", {}).get(a)
        if m:
            nm = nombre_motivos_subvenciones(a)
            principal["grandes"][a]["motivos"] = {"fichero": nm, **resumen_motivos(m, convs, res["total"])}
            usadas = sorted({c[0] for b in m.values() for c in b["c"]})
            ficheros[nm] = {"anio": int(a), "origen": obj["origen"],
                            "campos": ["convocatoria", "instrumento", "euros", "concesiones"],
                            "beneficiarios": m, "convocatorias": {k: convs[k] for k in usadas if k in convs}}
    return {"subvenciones.json": principal, **ficheros}


def unir_subvenciones(principal: dict | None, leer) -> dict | None:
    """Inversa de partir_subvenciones, a partir de lo publicado (leer(nombre) → dict | None)."""
    if not principal:
        return None
    obj = {k: v for k, v in principal.items() if k != "grandes"}
    obj["grandes"], motivos, convs = {}, {}, {}
    for a, g in principal.get("grandes", {}).items():
        lista = leer(g.get("lista") or nombre_lista_subvenciones(a))
        if lista:
            obj["grandes"][a] = {"total_fuente": g.get("total_fuente"), "lista": lista["beneficiarios"]}
        m = leer((g.get("motivos") or {}).get("fichero") or nombre_motivos_subvenciones(a))
        if m:
            motivos[a] = m["beneficiarios"]
            convs.update(m.get("convocatorias", {}))
    if motivos:
        obj["motivos"] = motivos
        obj["convocatorias"] = dict(sorted(convs.items()))
    return obj
