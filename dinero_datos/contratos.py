"""Contratos públicos: adjudicaciones de la Plataforma de Contratación del Sector Público.

Fuente: datos abiertos de la Plataforma de Contratación del Sector Público (PLACSP,
Ministerio de Hacienda). Cada mes se publica un ZIP con los ficheros ATOM (formato
CODICE) de todas las licitaciones alojadas en la Plataforma que cambiaron ese mes:
una misma licitación aparece en cada mes en que cambió y vale su última versión.

  https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/LicitacionesContratante.aspx

Cubre los perfiles del contratante alojados en la Plataforma (Administración General
del Estado, buena parte de las entidades locales y algunas comunidades). No incluye las
plataformas autonómicas agregadas ni los contratos menores, que se publican aparte.

El servidor limita la velocidad de cada conexión (unos 20 kB/s), así que los meses se
descargan en paralelo, se guardan en raw/contratos/ y solo se vuelven a pedir el mes en
curso y el anterior. La primera descarga tarda horas; las siguientes, una o dos.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree.ElementTree import iterparse

import requests

from .fuentes import PERSONA_FISICA, RAW_DIR, SourceError, NIF_TIPOS, clean, r2, tipo_nif

log = logging.getLogger("dinero_datos")

PLACSP_BASE = "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
PLACSP_FICHERO = "licitacionesPerfilesContratanteCompleto3_{mes}.zip"
PLACSP_PAGINA = "https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/LicitacionesContratante.aspx"
PLACSP_ORIGEN = "Plataforma de Contratación del Sector Público (Ministerio de Hacienda)"
DESDE = "202501"  # primer mes que se descarga
CONEXIONES = 6
RAW_CONTRATOS = RAW_DIR / "contratos"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 dinero-publico-datos")
TOP = 100  # mayores adjudicatarios por año en el resumen

# Listas de códigos CODICE (contrataciondelestado.es/codice/cl/...)
TIPOS = {
    "1": "Suministros", "2": "Servicios", "3": "Obras", "21": "Gestión de servicios públicos",
    "22": "Concesión de servicios", "31": "Concesión de obras públicas", "32": "Concesión de obras",
    "40": "Colaboración público-privada", "7": "Administrativo especial", "8": "Privado",
    "50": "Patrimonial", "999": "Otros",
}
# SyndicationTenderingProcessCode 2.07
PROCEDIMIENTOS = {
    "1": "Abierto", "2": "Restringido", "3": "Negociado sin publicidad", "4": "Negociado con publicidad",
    "5": "Diálogo competitivo", "6": "Contrato menor", "7": "Derivado de acuerdo marco",
    "8": "Concurso de proyectos", "9": "Abierto simplificado", "10": "Asociación para la innovación",
    "11": "Derivado de asociación para la innovación", "12": "Basado en sistema dinámico de adquisición",
    "13": "Licitación con negociación", "100": "Normas internas", "999": "Otros",
}
# TenderResultCode 2.09: 1 y 2 adjudicado (provisional y definitivo), 8 adjudicado, 9 formalizado.
# Los desiertos, desistimientos y renuncias no cuentan.
RESULTADOS_ADJUDICADOS = {"1", "2", "8", "9"}
ADMINISTRACION_ORDEN = ["Estado", "Comunidades autónomas", "Entidades locales", "Universidades", "Otras entidades"]

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "pe": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "pb": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
    "at": "http://purl.org/atompub/tombstones/1.0",
}
A, CBC, CAC, PE, PB, AT = ("{%s}" % NS[k] for k in ("a", "cbc", "cac", "pe", "pb", "at"))


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
def meses(desde: str = DESDE, hoy: dt.date | None = None) -> list[str]:
    hoy = hoy or dt.date.today()
    y, m = int(desde[:4]), int(desde[4:])
    out = []
    while (y, m) <= (hoy.year, hoy.month):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _fin_de_mes(mes: str) -> dt.datetime:
    y, m = int(mes[:4]), int(mes[4:])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return dt.datetime(y, m, 1)


def hay_que_descargar(mes: str, carpeta: Path = RAW_CONTRATOS) -> bool:
    """Los meses cerrados no cambian: solo se vuelve a pedir un mes si su copia es de
    antes de que terminara (más dos días de margen, lo que tarda la Plataforma en cerrarlo)."""
    p = carpeta / PLACSP_FICHERO.format(mes=mes)
    if not p.exists():
        return True
    return dt.datetime.fromtimestamp(p.stat().st_mtime) < _fin_de_mes(mes) + dt.timedelta(days=2)


def _bajar(mes: str, carpeta: Path) -> tuple[str, int]:
    nombre = PLACSP_FICHERO.format(mes=mes)
    url = PLACSP_BASE + nombre
    parte = carpeta / (nombre + ".part")
    ultimo: Exception | None = None
    for intento in range(1, 4):
        try:
            with requests.get(url, headers={"User-Agent": UA}, timeout=120, stream=True) as r:
                if r.status_code == 404:
                    return mes, 0
                if r.status_code != 200:
                    raise SourceError(f"{url} respondió {r.status_code}")
                n = 0
                with open(parte, "wb") as f:
                    for c in r.iter_content(1 << 16):
                        f.write(c)
                        n += len(c)
            with zipfile.ZipFile(parte) as z:  # comprueba que está completo
                if z.testzip() is not None:
                    raise SourceError(f"{nombre}: ZIP dañado")
            parte.replace(carpeta / nombre)
            return mes, n
        except (requests.RequestException, zipfile.BadZipFile, SourceError) as e:
            ultimo = e
            log.warning("  %s: intento %d fallido (%s)", nombre, intento, e)
            time.sleep(30 * intento)
    raise SourceError(f"No se pudo descargar {url}: {ultimo}")


def descargar(desde: str = DESDE, conexiones: int = CONEXIONES, carpeta: Path = RAW_CONTRATOS) -> list[str]:
    """Descarga los meses que faltan (del más reciente al más antiguo). Devuelve los errores."""
    carpeta.mkdir(parents=True, exist_ok=True)
    pendientes = [m for m in reversed(meses(desde)) if hay_que_descargar(m, carpeta)]
    log.info("  Contratos: %d meses por descargar con %d conexiones", len(pendientes), conexiones)
    errores = []
    with ThreadPoolExecutor(conexiones) as ex:
        futuros = {ex.submit(_bajar, m, carpeta): m for m in pendientes}
        for fu in as_completed(futuros):
            try:
                mes, n = fu.result()
                log.info("  ✔ contratos %s: %.1f MB", mes, n / 1e6)
            except Exception as e:
                errores.append(f"{futuros[fu]}: {e}")
                log.error("  ✘ contratos %s: %s", futuros[fu], e)
    return errores


# --------------------------------------------------------------------------- #
# Lectura de los ATOM (CODICE)
# --------------------------------------------------------------------------- #
NUTS2 = {
    "ES11": "Galicia", "ES12": "Asturias", "ES13": "Cantabria", "ES21": "País Vasco", "ES22": "Navarra",
    "ES23": "La Rioja", "ES24": "Aragón", "ES30": "Madrid", "ES41": "Castilla y León",
    "ES42": "Castilla-La Mancha", "ES43": "Extremadura", "ES51": "Cataluña", "ES52": "C. Valenciana",
    "ES53": "Illes Balears", "ES61": "Andalucía", "ES62": "Murcia", "ES63": "Ceuta", "ES64": "Melilla",
    "ES70": "Canarias",
}
_SIN_TILDES = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")


def _num(t: str | None) -> float | None:
    try:
        return float(t) if t not in (None, "") else None
    except ValueError:
        return None


def _txt(e, ruta: str) -> str:
    x = e.find(ruta, NS) if e is not None else None
    return clean(x.text) if x is not None and x.text else ""


def administracion(cadena: list[str]) -> str:
    """Cadena de ParentLocatedParty (de abajo arriba, termina en «Sector Público») → administración.

    Bajo «Sector Público» cuelgan ENTIDADES LOCALES, COMUNIDADES Y CIUDADES AUTÓNOMAS,
    OTRAS ENTIDADES DEL SECTOR PÚBLICO (sociedades, fundaciones y consorcios de cada
    administración, universidades, mutuas…) y, directamente, los ministerios y demás
    órganos del Estado. Las sociedades, fundaciones y consorcios cuentan con su administración.
    """
    k = [n.upper().translate(_SIN_TILDES) for n in cadena]
    if k and k[-1] == "SECTOR PUBLICO":
        k = k[:-1]
    if not k:
        return "Otras entidades"
    n1, n2 = k[-1], (k[-2] if len(k) > 1 else "")
    if n1 == "ENTIDADES LOCALES":
        return "Entidades locales"
    if n1.startswith("COMUNIDADES Y CIUDADES"):
        return "Comunidades autónomas"
    if n1.startswith("OTRAS ENTIDADES"):
        if "ESTATAL" in n2:
            return "Estado"
        if "ENTIDADES LOCALES" in n2:
            return "Entidades locales"
        if "COMUNIDADES" in n2:
            return "Comunidades autónomas"
        if "UNIVERSIDAD" in n2:
            return "Universidades"
        return "Otras entidades"
    return "Estado"


def leer_entrada(e) -> dict | None:
    """Un <entry> → {id, updated, adjudicaciones: [...], organo: [...]} (None si no es una licitación)."""
    cfs = e.find("pe:ContractFolderStatus", NS)
    if cfs is None:
        return None
    ident = _txt(e, "a:id").rsplit("/", 1)[-1]
    link = e.find("a:link", NS)
    lcp = cfs.find("pe:LocatedContractingParty", NS)
    party = lcp.find("cac:Party", NS) if lcp is not None else None
    nif_org = ""
    if party is not None:
        for pid in party.findall("cac:PartyIdentification/cbc:ID", NS):
            if pid.get("schemeName") == "NIF":
                nif_org = clean(pid.text).upper()
    cadena, p = [], lcp
    while p is not None:
        p = p.find("pe:ParentLocatedParty", NS)
        if p is not None:
            cadena.append(_txt(p, "cac:PartyName/cbc:Name"))
    organo = [_txt(party, "cac:PartyName/cbc:Name"), nif_org, administracion(cadena)]
    pp = cfs.find("cac:ProcurementProject", NS)
    titulo = _txt(pp, "cbc:Name") or _txt(e, "a:title")
    tipo = _txt(pp, "cbc:TypeCode")
    cpv = _txt(pp, "cac:RequiredCommodityClassification/cbc:ItemClassificationCode")
    nuts = _txt(pp, "cac:RealizedLocation/cbc:CountrySubentityCode")
    lotes = {_txt(l, "cbc:ID"): _txt(l, "cac:ProcurementProject/cbc:Name")
             for l in cfs.findall("cac:ProcurementProjectLot", NS)}
    proc = _txt(cfs, "cac:TenderingProcess/cbc:ProcedureCode")
    sistema = _txt(cfs, "cac:TenderingProcess/cbc:ContractingSystemCode") or "0"
    ue = _txt(cfs, "cac:TenderingTerms/cbc:FundingProgramCode")
    adj, vistos = [], set()
    for tr in cfs.findall("cac:TenderResult", NS):
        if _txt(tr, "cbc:ResultCode") not in RESULTADOS_ADJUDICADOS:
            continue
        fecha = _txt(tr, "cbc:AwardDate")[:10]
        ganadores = tr.findall("cac:WinningParty", NS)
        if not fecha or not ganadores:
            continue
        tot = tr.find("cac:AwardedTenderedProject/cac:LegalMonetaryTotal", NS)
        sin_iva = _num(_txt(tot, "cbc:TaxExclusiveAmount"))
        con_iva = _num(_txt(tot, "cbc:PayableAmount"))
        lote = _txt(tr, "cac:AwardedTenderedProject/cbc:ProcurementProjectLotID")
        ofertas = _num(_txt(tr, "cbc:ReceivedTenderQuantity"))
        pyme = _txt(tr, "cbc:SMEAwardedIndicator")
        # Varios adjudicatarios de un mismo lote (sobre todo en acuerdos marco): la Plataforma repite en
        # cada uno el importe del conjunto, así que solo cuenta una vez; los demás quedan «compartidos».
        repetido = bool(sin_iva) and (lote, sin_iva) in vistos
        vistos.add((lote, sin_iva))
        for i, g in enumerate(ganadores):
            nif = _txt(g, "cac:PartyIdentification/cbc:ID").upper().replace(" ", "").replace("-", "")
            nombre = _txt(g, "cac:PartyName/cbc:Name")
            if tipo_nif(nif) == "fisica" and nif:
                nif, nombre = "", PERSONA_FISICA
            adj.append({
                "expediente": _txt(cfs, "cbc:ContractFolderID"),
                "titulo": (lotes.get(lote) if lote and lotes.get(lote) else titulo),
                "lote": lote, "nif": nif, "nombre": nombre,
                "sin_iva": None if i or repetido else sin_iva, "con_iva": None if i or repetido else con_iva,
                "comparte": len(ganadores) > 1 or repetido,
                "fecha": fecha, "tipo": tipo, "procedimiento": proc, "sistema": sistema,
                "ofertas": int(ofertas) if ofertas is not None else None,
                "pyme": {"true": True, "false": False}.get(pyme), "cpv": cpv[:8], "nuts": nuts, "ue": ue,
            })
    return {"id": ident, "updated": _txt(e, "a:updated"), "url": link.get("href") if link is not None else "",
            "organo": organo, "adjudicaciones": adj}


def leer_atom(f):
    """Recorre un fichero ATOM sin cargarlo entero: genera ("entrada", dict) y ("borrada", id, cuando)."""
    for ev, el in iterparse(f, events=("end",)):
        if el.tag == A + "entry":
            d = leer_entrada(el)
            if d:
                yield ("entrada", d)
            el.clear()
        elif el.tag == AT + "deleted-entry":
            yield ("borrada", el.get("ref", "").rsplit("/", 1)[-1], el.get("when", ""))
            el.clear()


def leer_mes(ruta: Path) -> tuple[dict, dict]:
    """ZIP de un mes → ({id: última versión de la entrada en ese mes}, {id: fecha de borrado})."""
    entradas, borradas = {}, {}
    with zipfile.ZipFile(ruta) as z:
        for n in z.namelist():
            if not n.endswith(".atom"):
                continue
            with z.open(n) as f:
                for ev in leer_atom(f):
                    if ev[0] == "entrada":
                        d = ev[1]
                        if d["id"] not in entradas or d["updated"] > entradas[d["id"]]["updated"]:
                            entradas[d["id"]] = d
                    else:
                        borradas[ev[1]] = max(ev[2], borradas.get(ev[1], ""))
    return entradas, borradas


# --------------------------------------------------------------------------- #
# Consolidación y ficheros publicados
# --------------------------------------------------------------------------- #
VERSION_CACHE = 2
# Una fila por adjudicación. «adjudicatario» y «organo» son posiciones en las listas del mismo fichero.
CAMPOS = ["id", "enlace", "organo", "expediente", "lote", "titulo", "adjudicatario", "sin_iva", "con_iva",
          "fecha", "tipo", "procedimiento", "sistema", "ofertas", "pyme", "cpv", "nuts", "ue", "comparte"]
ENLACE = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl="
# ContractingSystemTypeCode 2.08. Establecer un acuerdo marco o un sistema dinámico de adquisición fija
# un valor máximo para varios años y empresas, no un gasto: no se suma al importe adjudicado. Los
# contratos basados en ellos (3 y 4) sí son gasto.
SISTEMAS = {"0": "Contrato", "1": "Acuerdo marco", "2": "Sistema dinámico de adquisición",
            "3": "Basado en acuerdo marco", "4": "Basado en sistema dinámico de adquisición"}
SISTEMAS_VALOR_MAXIMO = {"1", "2"}


def _mes_en_cache(zip_path: Path) -> tuple[dict, dict]:
    """leer_mes con una copia ya procesada al lado (raw/contratos/AAAAMM.json.gz)."""
    import gzip
    import json
    cache = zip_path.with_suffix(".json.gz")
    if cache.exists() and cache.stat().st_mtime >= zip_path.stat().st_mtime:
        d = json.loads(gzip.decompress(cache.read_bytes()))
        if d.get("v") == VERSION_CACHE:
            return d["entradas"], d["borradas"]
    entradas, borradas = leer_mes(zip_path)
    cache.write_bytes(gzip.compress(json.dumps({"v": VERSION_CACHE, "entradas": entradas, "borradas": borradas},
                                               ensure_ascii=False).encode(), 6))
    return entradas, borradas


def consolidar(carpeta: Path = RAW_CONTRATOS, desde: str = DESDE) -> tuple[dict, list[str]]:
    """Última versión de cada licitación en todos los meses descargados, sin las anuladas."""
    ultimas, borradas, leidos = {}, {}, []
    for mes in meses(desde):
        z = carpeta / PLACSP_FICHERO.format(mes=mes)
        if not z.exists():
            continue
        try:
            entradas, borr = _mes_en_cache(z)
        except zipfile.BadZipFile:
            log.warning("  contratos %s: ZIP dañado, se omite", mes)
            continue
        for i, d in entradas.items():
            if i not in ultimas or d["updated"] > ultimas[i]["updated"]:
                ultimas[i] = d
        for i, w in borr.items():
            borradas[i] = max(w, borradas.get(i, ""))
        leidos.append(mes)
        log.info("  contratos %s: %d licitaciones (%d acumuladas)", mes, len(entradas), len(ultimas))
    for i, w in borradas.items():
        if i in ultimas and w >= ultimas[i]["updated"]:
            del ultimas[i]
    return ultimas, leidos


def desde_continuo(leidos: list[str], desde: str = DESDE, hoy: dt.date | None = None) -> str:
    """Primer mes del tramo sin huecos que llega hasta hoy: las adjudicaciones anteriores
    no se publican porque su cobertura estaría incompleta (los meses se descargan del más
    reciente al más antiguo)."""
    hechos, primero = set(leidos), None
    for m in reversed(meses(desde, hoy)):
        if m not in hechos:
            break
        primero = m
    return primero or max(leidos)


def comunidad(nuts: str) -> str:
    return NUTS2.get((nuts or "")[:4], "Varias o sin especificar")


def _suma(d: dict, k: str, eur: float | None) -> None:
    x = d.setdefault(k, [0, 0.0])
    x[0] += 1
    x[1] += eur or 0


def _ordenar(d: dict) -> dict:
    return {k: [v[0], r2(v[1])] for k, v in sorted(d.items(), key=lambda kv: -kv[1][1])}


def construir(ultimas: dict, leidos: list[str], desde: str = DESDE, hoy: dt.date | None = None) -> dict[str, dict]:
    """Licitaciones consolidadas → contratos.json (resúmenes), contratos-AAAA-MM.json (cada adjudicación,
    por mes de adjudicación) y contratos-adjudicatarios-AAAA.json (totales por NIF, para cruzar con otras fuentes)."""
    hoy = hoy or dt.date.today()
    inicio = f"{desde[:4]}-{desde[4:]}-01"
    por_anio: dict[str, list] = {}
    for ident in sorted(ultimas, key=int):
        d = ultimas[ident]
        url = d.get("url") or ""
        enlace = url.split("idEvl=", 1)[1] if "idEvl=" in url else ""
        for a in d["adjudicaciones"]:
            if inicio <= a["fecha"] <= hoy.isoformat():
                por_anio.setdefault(a["fecha"][:4], []).append((int(ident), enlace, tuple(d["organo"]), a))
    ficheros, resumen = {}, {}
    C = {k: i for i, k in enumerate(CAMPOS)}
    for anio, items in sorted(por_anio.items(), reverse=True):
        items.sort(key=lambda x: (-(x[3]["sin_iva"] or 0), x[0]))
        organos, idx_o, adjud, idx_a, filas = [], {}, [], {}, []
        for ident, enlace, org, a in items:
            if org not in idx_o:
                idx_o[org] = len(organos)
                organos.append(list(org))
            q = (a["nif"], a["nombre"])
            if q not in idx_a:
                idx_a[q] = len(adjud)
                adjud.append(list(q))
            filas.append([ident, enlace, idx_o[org], a["expediente"], a["lote"], a["titulo"], idx_a[q],
                          r2(a["sin_iva"]), r2(a["con_iva"]), a["fecha"], a["tipo"], a["procedimiento"],
                          a.get("sistema", "0"), a["ofertas"], None if a["pyme"] is None else int(a["pyme"]),
                          a["cpv"], a["nuts"], a["ue"], int(bool(a.get("comparte")))])
        # Un fichero por mes de adjudicación: cada uno pesa unos 5 MB y, al actualizar, solo cambian los
        # meses recientes (el historial de git del repositorio de datos crece poco).
        meses_a = {}
        for f in filas:
            meses_a.setdefault(f[C["fecha"]][:7], []).append(f)
        nombres_mes = []
        for mes, fm in sorted(meses_a.items()):
            o_usados = sorted({f[C["organo"]] for f in fm})
            a_usados = sorted({f[C["adjudicatario"]] for f in fm})
            ro, ra = {o: i for i, o in enumerate(o_usados)}, {x: i for i, x in enumerate(a_usados)}
            fm2 = []
            for f in fm:
                g = list(f)
                g[C["organo"]], g[C["adjudicatario"]] = ro[f[C["organo"]]], ra[f[C["adjudicatario"]]]
                fm2.append(g)
            nombre = f"contratos-{mes}.json"
            nombres_mes.append(nombre)
            ficheros[nombre] = {"mes": mes, "origen": PLACSP_ORIGEN, "unidad": "euros", "enlace": ENLACE,
                                "campos": CAMPOS, "campos_organo": ["nombre", "nif", "administracion"],
                                "campos_adjudicatario": ["nif", "nombre"],
                                "organos": [organos[o] for o in o_usados], "adjudicatarios": [adjud[x] for x in a_usados],
                                "adjudicaciones": fm2}
        por_nif: dict[str, list] = {}
        for f in filas:
            nif = adjud[f[C["adjudicatario"]]][0]
            if nif and f[C["sistema"]] not in SISTEMAS_VALOR_MAXIMO:
                x = por_nif.setdefault(nif, [0, 0.0])
                x[0] += 1
                x[1] += f[C["sin_iva"]] or 0
        nombre_adj = f"contratos-adjudicatarios-{anio}.json"
        ficheros[nombre_adj] = {"anio": int(anio), "origen": PLACSP_ORIGEN, "campos": ["adjudicaciones", "euros_sin_iva"],
                                "nota": "Sin el valor máximo de los acuerdos marco y sistemas dinámicos de adquisición.",
                                "adjudicatarios": {k: [v[0], r2(v[1])] for k, v in sorted(por_nif.items(), key=lambda kv: -kv[1][1])}}
        resumen[anio] = {"ficheros": nombres_mes, "fichero_adjudicatarios": nombre_adj, **resumir(filas, organos, adjud)}
    principal = {
        "fuente": PLACSP_PAGINA, "origen": PLACSP_ORIGEN,
        "cobertura": {"desde": inicio, "meses": leidos,
                      "hasta": max((d["updated"] for d in ultimas.values()), default="")[:10]},
        "ambito": "Licitaciones de los perfiles del contratante alojados en la Plataforma de Contratación del "
                  "Sector Público. No incluye las plataformas autonómicas agregadas (Cataluña, Madrid, Andalucía, "
                  "País Vasco, Galicia, Navarra, La Rioja…) ni los contratos menores.",
        "disociacion": "Dinero Público no publica el nombre ni el NIF de los adjudicatarios que son personas físicas: "
                       "figuran como «" + PERSONA_FISICA + "» y solo cuentan en los totales.",
        "unidad": "euros; importe de adjudicación sin IVA salvo que se indique",
        "valor_maximo": "Los acuerdos marco y sistemas dinámicos de adquisición no suman al importe adjudicado: "
                        "su importe es un máximo para varios años y empresas. Van aparte en «valor_maximo».",
        "en_curso": [a for a in resumen if int(a) >= hoy.year],
        "tipos": TIPOS, "procedimientos": PROCEDIMIENTOS, "sistemas": SISTEMAS, "nif_tipos": NIF_TIPOS,
        "comunidades": NUTS2, "administraciones": ADMINISTRACION_ORDEN,
        "anios": resumen,
    }
    return {"contratos.json": principal, **ficheros}


def resumir(filas: list[list], organos: list[list], adjud: list[list]) -> dict:
    """Totales del año. Solo cuentan los contratos (no el valor máximo de acuerdos marco y SDA)."""
    C = {k: i for i, k in enumerate(CAMPOS)}
    tipo, proc, adm, com, mes, sis, top_a, top_o = {}, {}, {}, {}, {}, {}, {}, {}
    una, pyme, ue, vmax = [0, 0.0], [0, 0.0], [0, 0.0], [0, 0.0]
    n = total = con_iva = 0
    for f in filas:
        eur = f[C["sin_iva"]] or 0
        if f[C["sistema"]] in SISTEMAS_VALOR_MAXIMO:
            vmax[0] += 1
            vmax[1] += eur
            continue
        n += 1
        total += eur
        con_iva += f[C["con_iva"]] or 0
        t, pr = f[C["tipo"]], f[C["procedimiento"]]
        _suma(tipo, TIPOS.get(t, "Otros") if t else "Sin información", eur)
        _suma(proc, PROCEDIMIENTOS.get(pr, "Otros") if pr else "Sin información", eur)
        _suma(adm, organos[f[C["organo"]]][2], eur)
        _suma(com, comunidad(f[C["nuts"]]), eur)
        _suma(mes, f[C["fecha"]][:7], eur)
        _suma(sis, SISTEMAS.get(f[C["sistema"]], "Contrato"), eur)
        _suma(top_o, f[C["organo"]], eur)
        if adjud[f[C["adjudicatario"]]][0]:
            _suma(top_a, f[C["adjudicatario"]], eur)
        ue_ = f[C["ue"]]
        for cond, acc in ((f[C["ofertas"]] == 1, una), (f[C["pyme"]] == 1, pyme), (bool(ue_) and ue_ != "NO-EU", ue)):
            if cond:
                acc[0] += 1
                acc[1] += eur
    mayores = sorted(top_a.items(), key=lambda kv: -kv[1][1])[:TOP]
    mayores_o = sorted(top_o.items(), key=lambda kv: -kv[1][1])[:TOP]
    return {
        "adjudicaciones": n, "importe": r2(total), "con_iva": r2(con_iva),
        "adjudicatarios": len(top_a), "organos": len(top_o),
        "valor_maximo": [vmax[0], r2(vmax[1])],
        "una_oferta": [una[0], r2(una[1])], "pyme": [pyme[0], r2(pyme[1])], "fondos_ue": [ue[0], r2(ue[1])],
        "por_tipo": _ordenar(tipo), "por_procedimiento": _ordenar(proc), "por_sistema": _ordenar(sis),
        "por_administracion": _ordenar(adm), "por_comunidad": _ordenar(com),
        "por_mes": {k: [v[0], r2(v[1])] for k, v in sorted(mes.items())},
        "mayores": [[adjud[i][0], adjud[i][1], r2(v[1]), v[0]] for i, v in mayores],
        "mayores_organos": [[organos[i][0], organos[i][2], r2(v[1]), v[0]] for i, v in mayores_o],
    }


def fetch_contratos(offline: bool = False, desde: str = DESDE, conexiones: int = CONEXIONES) -> dict:
    """Descarga los meses que faltan (salvo offline), consolida y devuelve {fichero: obj}."""
    errores = [] if offline else descargar(desde, conexiones)
    ultimas, leidos = consolidar(RAW_CONTRATOS, desde)
    if not leidos:
        raise SourceError("No hay ningún mes de contratos descargado" + (f": {errores[0]}" if errores else ""))
    salida = construir(ultimas, leidos, desde_continuo(leidos, desde))
    if errores:
        salida["contratos.json"]["errores_descarga"] = errores
    return salida
