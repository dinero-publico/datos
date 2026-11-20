"""Contratos: lectura de los ATOM de la Plataforma de Contratación, consolidación y resúmenes."""
import datetime as dt
import io
import zipfile

from dinero_datos import contratos as c
from dinero_datos.fuentes import PERSONA_FISICA

CAB = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
 xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"
 xmlns:at="http://purl.org/atompub/tombstones/1.0">
"""


def entrada(ident, updated, ganadores, *, cadena=("Sevilla", "Andalucía", "ENTIDADES LOCALES", "Sector Público"),
            resultado="9", fecha="2026-03-10", lotes=None, sistema="0"):
    padres = "".join(f"<cac-place-ext:ParentLocatedParty><cac:PartyName><cbc:Name>{n}</cbc:Name></cac:PartyName>" for n in cadena)
    padres += "</cac-place-ext:ParentLocatedParty>" * len(cadena)
    res = ""
    for nif, nombre, imp, lote in ganadores:
        res += f"""<cac:TenderResult><cbc:ResultCode>{resultado}</cbc:ResultCode><cbc:AwardDate>{fecha}</cbc:AwardDate>
          <cbc:ReceivedTenderQuantity>1</cbc:ReceivedTenderQuantity><cbc:SMEAwardedIndicator>true</cbc:SMEAwardedIndicator>
          <cac:WinningParty><cac:PartyIdentification><cbc:ID schemeName="NIF">{nif}</cbc:ID></cac:PartyIdentification>
          <cac:PartyName><cbc:Name>{nombre}</cbc:Name></cac:PartyName></cac:WinningParty>
          <cac:AwardedTenderedProject>{f'<cbc:ProcurementProjectLotID>{lote}</cbc:ProcurementProjectLotID>' if lote else ''}
          <cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID="EUR">{imp}</cbc:TaxExclusiveAmount>
          <cbc:PayableAmount currencyID="EUR">{imp * 1.21}</cbc:PayableAmount></cac:LegalMonetaryTotal></cac:AwardedTenderedProject>
        </cac:TenderResult>"""
    lots = "".join(f"<cac:ProcurementProjectLot><cbc:ID>{k}</cbc:ID><cac:ProcurementProject><cbc:Name>{v}</cbc:Name></cac:ProcurementProject></cac:ProcurementProjectLot>"
                   for k, v in (lotes or {}).items())
    return f"""<entry><id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/{ident}</id>
      <link href="https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&amp;idEvl=abc{ident}"/>
      <title>Contrato {ident}</title><updated>{updated}</updated>
      <cac-place-ext:ContractFolderStatus><cbc:ContractFolderID>EXP-{ident}</cbc:ContractFolderID>
        <cbc-place-ext:ContractFolderStatusCode>RES</cbc-place-ext:ContractFolderStatusCode>
        <cac-place-ext:LocatedContractingParty><cac:Party>
          <cac:PartyIdentification><cbc:ID schemeName="NIF">P4100000A</cbc:ID></cac:PartyIdentification>
          <cac:PartyName><cbc:Name>Ayuntamiento de Ejemplo</cbc:Name></cac:PartyName></cac:Party>{padres}
        </cac-place-ext:LocatedContractingParty>
        <cac:ProcurementProject><cbc:Name>Obra de ejemplo {ident}</cbc:Name><cbc:TypeCode>3</cbc:TypeCode>
          <cac:RequiredCommodityClassification><cbc:ItemClassificationCode>45233120</cbc:ItemClassificationCode></cac:RequiredCommodityClassification>
          <cac:RealizedLocation><cbc:CountrySubentityCode>ES618</cbc:CountrySubentityCode></cac:RealizedLocation>
        </cac:ProcurementProject>{lots}{res}
        <cac:TenderingTerms><cbc:FundingProgramCode>EU</cbc:FundingProgramCode></cac:TenderingTerms>
        <cac:TenderingProcess><cbc:ProcedureCode>1</cbc:ProcedureCode><cbc:ContractingSystemCode>{sistema}</cbc:ContractingSystemCode></cac:TenderingProcess>
      </cac-place-ext:ContractFolderStatus></entry>"""


def zip_mes(carpeta, mes, *cuerpos):
    p = carpeta / c.PLACSP_FICHERO.format(mes=mes)
    with zipfile.ZipFile(p, "w") as z:
        for i, cuerpo in enumerate(cuerpos):
            z.writestr(f"f{i}.atom", CAB + cuerpo + "</feed>")
    return p


def test_leer_entrada_lotes_y_personas_fisicas():
    xml = CAB + entrada("1", "2026-03-11T10:00:00+01:00",
                        [("B12345674", "Obras, S.L.", 1000.0, "1"), ("12345678Z", "Juan Pérez", 500.0, "2")],
                        lotes={"1": "Lote de asfaltado", "2": "Lote de aceras"}) + "</feed>"
    evs = list(c.leer_atom(io.BytesIO(xml.encode())))
    assert len(evs) == 1 and evs[0][0] == "entrada"
    d = evs[0][1]
    assert d["id"] == "1" and d["organo"] == ["Ayuntamiento de Ejemplo", "P4100000A", "Entidades locales"]
    a, b = d["adjudicaciones"]
    assert (a["nif"], a["titulo"], a["sin_iva"], a["tipo"], a["procedimiento"]) == ("B12345674", "Lote de asfaltado", 1000.0, "3", "1")
    # Las personas físicas se disocian: sin nombre ni NIF.
    assert (b["nif"], b["nombre"], b["titulo"]) == ("", PERSONA_FISICA, "Lote de aceras")


def test_resultados_no_adjudicados_no_cuentan():
    xml = CAB + entrada("2", "2026-03-11T10:00:00+01:00", [("B12345674", "X", 1.0, "")], resultado="3") + "</feed>"
    (_, d), = c.leer_atom(io.BytesIO(xml.encode()))
    assert d["adjudicaciones"] == []


def test_administracion():
    assert c.administracion(["Subsecretaría", "Ministerio de Hacienda", "Sector Público"]) == "Estado"
    assert c.administracion(["SOCIEDADES, FUNDACIONES y CONSORCIOS ESTATALES", "OTRAS ENTIDADES DEL SECTOR PÚBLICO", "Sector Público"]) == "Estado"
    assert c.administracion(["UNIVERSIDADES", "OTRAS ENTIDADES DEL SECTOR PÚBLICO", "Sector Público"]) == "Universidades"
    assert c.administracion(["Conselleria", "COMUNIDADES Y CIUDADES AUTÓNOMAS", "Sector Público"]) == "Comunidades autónomas"
    assert c.administracion(["MUTUAS", "OTRAS ENTIDADES DEL SECTOR PÚBLICO", "Sector Público"]) == "Otras entidades"


def test_consolidar_ultima_version_y_anuladas(tmp_path):
    zip_mes(tmp_path, "202603", entrada("10", "2026-03-11T10:00:00+01:00", [("B12345674", "Obras, S.L.", 1000.0, "")]),
            entrada("11", "2026-03-12T10:00:00+01:00", [("A11111118", "Grande, S.A.", 9000.0, "")]))
    # En abril cambia el importe de la 10 y se anula la 11.
    zip_mes(tmp_path, "202604", entrada("10", "2026-04-02T10:00:00+02:00", [("B12345674", "Obras, S.L.", 1200.0, "")])
            + '<at:deleted-entry ref="https://x/11" when="2026-04-03T10:00:00+02:00"/>')
    ult, leidos = c.consolidar(tmp_path, "202603")
    assert leidos == ["202603", "202604"] and set(ult) == {"10"}
    assert ult["10"]["adjudicaciones"][0]["sin_iva"] == 1200.0
    hoy = dt.date(2026, 4, 30)
    assert c.desde_continuo(leidos, "202603", hoy) == "202603"
    sal = c.construir(ult, leidos, "202603", hoy)
    r = sal["contratos.json"]["anios"]["2026"]
    assert r["adjudicaciones"] == 1 and r["importe"] == 1200.0
    assert r["por_comunidad"] == {"Andalucía": [1, 1200.0]} and r["fondos_ue"] == [1, 1200.0]
    assert sal["contratos-adjudicatarios-2026.json"]["adjudicatarios"] == {"B12345674": [1, 1200.0]}
    assert r["ficheros"] == ["contratos-2026-04.json"] or r["ficheros"] == ["contratos-2026-03.json"]
    f = sal[r["ficheros"][0]]
    fila = dict(zip(c.CAMPOS, f["adjudicaciones"][0]))
    assert fila["enlace"] == "abc10" and fila["expediente"] == "EXP-10"
    assert f["adjudicatarios"][fila["adjudicatario"]] == ["B12345674", "Obras, S.L."]


def test_acuerdo_marco_no_suma_y_lote_repetido_cuenta_una_vez(tmp_path):
    # Acuerdo marco con cuatro adjudicatarios del mismo lote, cada uno con el valor máximo del acuerdo.
    am = entrada("20", "2026-03-11T10:00:00+01:00", [(n, "X", 3_400_000.0, "1") for n in ("A11111118", "A22222228", "A33333338", "A44444448")], sistema="1")
    # Contrato normal con dos resultados repetidos para el mismo lote e importe.
    rep = entrada("21", "2026-03-11T10:00:00+01:00", [("B12345674", "Obras, S.L.", 500.0, "1"), ("B76543214", "Otra, S.L.", 500.0, "1")])
    basado = entrada("22", "2026-03-11T10:00:00+01:00", [("A11111118", "X", 100.0, "")], sistema="3")
    zip_mes(tmp_path, "202603", am + rep + basado)
    ult, leidos = c.consolidar(tmp_path, "202603")
    r = c.construir(ult, leidos, "202603", dt.date(2026, 3, 31))["contratos.json"]["anios"]["2026"]
    assert r["valor_maximo"] == [4, 3_400_000.0]  # el valor máximo, una sola vez
    assert r["adjudicaciones"] == 3 and r["importe"] == 600.0  # 500 (una vez) + 100 del basado
    assert r["por_sistema"] == {"Contrato": [2, 500.0], "Basado en acuerdo marco": [1, 100.0]}


def test_desde_continuo_con_huecos():
    hoy = dt.date(2026, 5, 15)
    assert c.desde_continuo(["202605", "202604", "202602"], "202601", hoy) == "202604"
