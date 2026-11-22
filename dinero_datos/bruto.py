"""Registros brutos de cada fuente para la plataforma (capa «bruto», ver proto/ en plataforma).

Un mensaje por elemento de la fuente, con los valores tal como vienen: sin convertir importes
ni interpretar códigos. Las personas físicas se disocian aquí, antes de salir de la ingesta.

    emitir_poblacion(carga, dl)     INE, Estadística Continua de Población (API JSON)
    emitir_contratos(carga, desde)  Plataforma de Contratación (ZIP mensuales con ATOM/CODICE)
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from xml.etree.ElementTree import iterparse

from . import contratos as con
from . import fuentes as f

log = logging.getLogger("dinero_datos")


# --------------------------------------------------------------------------- #
# Población (INE)
# --------------------------------------------------------------------------- #
def emitir_poblacion(carga, dl: f.Downloader) -> None:
    """Cada dato de las series «total, todas las edades» de cada territorio (tabla 56940)."""
    from dinero_publico.bruto.v1 import poblacion_pb2

    def pedir(ruta: str):
        url = f"{f.INE_API}{ruta}"
        r = dl._request("GET", url)
        if r.status_code != 200:
            raise f.SourceError(f"{url} respondió {r.status_code}")
        return url, r.content, r.json()

    _, _, tabla = pedir(f"DATOS_TABLA/{f.INE_TABLA_POBLACION}?nult=1")
    series = f.series_poblacion(tabla)
    if "España" not in series:
        raise f.SourceError("El INE no devolvió la serie de España")
    for _, cod in sorted(series.items()):
        peticion = f"DATOS_SERIE/{cod}?nult=120"
        url, crudo, serie = pedir(peticion)
        anio = max((x.get("Anyo", 0) for x in serie.get("Data", [])), default=0)
        proc = carga.original(crudo, url=url, extension="json", anio=anio)
        nombre = serie.get("Nombre", "")
        territorio = nombre.split(".")[0].strip()
        for i, x in enumerate(serie.get("Data", [])):
            if x.get("Valor") is None:
                continue
            clave = f"{serie.get('COD', cod)}:{x['Fecha']}"
            carga.emitir(poblacion_pb2.DatoPoblacion(
                cabecera=carga.cabecera(clave, proc, api={"peticion": peticion, "posicion": i}),
                serie_codigo=serie.get("COD", cod), serie_nombre=nombre, territorio=territorio,
                fecha_ms=int(x["Fecha"]), anio=int(x.get("Anyo", 0)), periodo_id=int(x.get("FK_Periodo", 0)),
                tipo_dato_id=int(x.get("FK_TipoDato", 0)), unidad_id=int(serie.get("FK_Unidad", 0)),
                escala_id=int(serie.get("FK_Escala", 0)), valor=float(x["Valor"]), secreto=bool(x.get("Secreto"))))


# --------------------------------------------------------------------------- #
# Contratos (Plataforma de Contratación)
# --------------------------------------------------------------------------- #
NS = con.NS


def _t(el, ruta: str) -> str:
    if el is None:
        return ""
    x = el.find(ruta, NS)
    return (x.text or "").strip() if x is not None else ""


def _importe(el, ruta: str):
    from dinero_publico.bruto.v1 import cabecera_pb2
    x = el.find(ruta, NS) if el is not None else None
    if x is None:
        return None
    return cabecera_pb2.Importe(valor=(x.text or "").strip(), moneda=x.get("currencyID", ""))


def _ids(party, esquema: str) -> str:
    if party is None:
        return ""
    for pid in party.findall("cac:PartyIdentification/cbc:ID", NS):
        if pid.get("schemeName") == esquema:
            return (pid.text or "").strip()
    return ""


def licitacion(e, cabecera) -> "object | None":
    """Una <entry> ATOM → Licitacion bruta (None si no es una licitación)."""
    from dinero_publico.bruto.v1 import contratos_pb2 as pb
    cfs = e.find("pe:ContractFolderStatus", NS)
    if cfs is None:
        return None
    lcp = cfs.find("pe:LocatedContractingParty", NS)
    party = lcp.find("cac:Party", NS) if lcp is not None else None
    superiores, p = [], lcp
    while p is not None:
        p = p.find("pe:ParentLocatedParty", NS)
        if p is not None:
            superiores.append(_t(p, "cac:PartyName/cbc:Name"))
    pp = cfs.find("cac:ProcurementProject", NS)
    link = e.find("a:link", NS)
    lic = pb.Licitacion(
        cabecera=cabecera, id=_t(e, "a:id").rsplit("/", 1)[-1], enlace=link.get("href", "") if link is not None else "",
        actualizado=_t(e, "a:updated"), estado_codigo=_t(cfs, "pb:ContractFolderStatusCode"),
        expediente=_t(cfs, "cbc:ContractFolderID"), programa_financiacion=_t(cfs, "cac:TenderingTerms/cbc:FundingProgramCode"),
        organo=pb.Organo(nombre=_t(party, "cac:PartyName/cbc:Name"), nif=_ids(party, "NIF"), dir3=_ids(party, "DIR3"),
                         tipo_codigo=_t(lcp, "cbc:ContractingPartyTypeCode"), superiores=superiores),
        proyecto=pb.Proyecto(
            nombre=_t(pp, "cbc:Name") or _t(e, "a:title"), tipo_codigo=_t(pp, "cbc:TypeCode"),
            subtipo_codigo=_t(pp, "cbc:SubTypeCode"),
            cpv=[(c.text or "").strip() for c in (pp.findall("cac:RequiredCommodityClassification/cbc:ItemClassificationCode", NS) if pp is not None else [])],
            nuts=_t(pp, "cac:RealizedLocation/cbc:CountrySubentityCode"), lugar=_t(pp, "cac:RealizedLocation/cbc:CountrySubentity"),
            valor_estimado=_importe(pp, "cac:BudgetAmount/cbc:EstimatedOverallContractAmount"),
            presupuesto_sin_iva=_importe(pp, "cac:BudgetAmount/cbc:TaxExclusiveAmount"),
            presupuesto_con_iva=_importe(pp, "cac:BudgetAmount/cbc:TotalAmount")),
        proceso=pb.Proceso(procedimiento_codigo=_t(cfs, "cac:TenderingProcess/cbc:ProcedureCode"),
                           sistema_codigo=_t(cfs, "cac:TenderingProcess/cbc:ContractingSystemCode"),
                           urgencia_codigo=_t(cfs, "cac:TenderingProcess/cbc:UrgencyCode")))
    for lote in cfs.findall("cac:ProcurementProjectLot", NS):
        lpp = lote.find("cac:ProcurementProject", NS)
        lic.lotes.append(pb.Lote(
            id=_t(lote, "cbc:ID"), nombre=_t(lpp, "cbc:Name"),
            cpv=[(c.text or "").strip() for c in (lpp.findall("cac:RequiredCommodityClassification/cbc:ItemClassificationCode", NS) if lpp is not None else [])],
            presupuesto_sin_iva=_importe(lpp, "cac:BudgetAmount/cbc:TaxExclusiveAmount"),
            presupuesto_con_iva=_importe(lpp, "cac:BudgetAmount/cbc:TotalAmount")))
    for tr in cfs.findall("cac:TenderResult", NS):
        r = pb.Resultado(
            codigo=_t(tr, "cbc:ResultCode"), lote=_t(tr, "cac:AwardedTenderedProject/cbc:ProcurementProjectLotID"),
            fecha_adjudicacion=_t(tr, "cbc:AwardDate"), fecha_formalizacion=_t(tr, "cac:Contract/cbc:IssueDate"),
            ofertas_recibidas=_t(tr, "cbc:ReceivedTenderQuantity"), pyme=_t(tr, "cbc:SMEAwardedIndicator"),
            importe_sin_iva=_importe(tr, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"),
            importe_con_iva=_importe(tr, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"))
        for g in tr.findall("cac:WinningParty", NS):
            nif = _t(g, "cac:PartyIdentification/cbc:ID")
            if f.tipo_nif(nif.upper().replace(" ", "").replace("-", "")) == "fisica" and nif:
                r.adjudicatarios.append(pb.Adjudicatario(persona_fisica=True))
            else:
                r.adjudicatarios.append(pb.Adjudicatario(nif=nif, nombre=_t(g, "cac:PartyName/cbc:Name")))
        lic.resultados.append(r)
    return lic


def leer_mes_bruto(zip_path: Path, procedencia, carga) -> tuple[dict, dict]:
    """ZIP de un mes → ({id: Licitacion de la última versión del mes}, {id: fecha de anulación})."""
    from dinero_publico.bruto.v1 import contratos_pb2 as pb
    ultimas, anuladas = {}, {}
    with zipfile.ZipFile(zip_path) as z:
        for nombre in sorted(n for n in z.namelist() if n.endswith(".atom")):
            with z.open(nombre) as fich:
                for _, el in iterparse(fich, events=("end",)):
                    if el.tag == con.A + "entry":
                        ident = (el.findtext(con.A + "id") or "").rsplit("/", 1)[-1]
                        actualizado = el.findtext(con.A + "updated") or ""
                        if ident and (ident not in ultimas or actualizado > ultimas[ident].actualizado):
                            cab = carga.cabecera(ident, procedencia, entrada_atom=ident, fichero_en_zip=nombre)
                            lic = licitacion(el, cab)
                            if lic is not None:
                                ultimas[ident] = lic
                        el.clear()
                    elif el.tag == con.AT + "deleted-entry":
                        ident = el.get("ref", "").rsplit("/", 1)[-1]
                        anuladas[ident] = max(el.get("when", ""), anuladas.get(ident, ""))
                        el.clear()
    for ident, cuando in anuladas.items():
        lic = ultimas.get(ident)
        if lic is None or cuando >= lic.actualizado:
            ultimas[ident] = pb.Licitacion(cabecera=carga.cabecera(ident, procedencia, entrada_atom=ident),
                                           id=ident, anulada=True, anulada_en=cuando)
    return ultimas, anuladas


def emitir_contratos(carga, desde: str = con.DESDE, carpeta: Path | None = None, descargar: bool = True) -> None:
    """Los ZIP mensuales, del más antiguo al más reciente: así, en el topic compactado queda la
    última versión de cada licitación. Cada mes emite la última versión de sus entradas."""
    carpeta = carpeta or con.RAW_CONTRATOS
    if descargar:
        con.descargar(desde, carpeta=carpeta)
    for mes in con.meses(desde):
        z = carpeta / con.PLACSP_FICHERO.format(mes=mes)
        if not z.exists():
            log.warning("  falta el ZIP de %s", mes)
            continue
        url = con.PLACSP_BASE + con.PLACSP_FICHERO.format(mes=mes)
        proc = carga.original(z, url=url, extension="zip", anio=mes[:4])
        ultimas, anuladas = leer_mes_bruto(z, proc, carga)
        for lic in ultimas.values():
            carga.emitir(lic)
        log.info("  contratos %s: %d licitaciones (%d anuladas)", mes, len(ultimas), len(anuladas))
