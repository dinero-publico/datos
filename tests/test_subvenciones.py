"""Subvenciones (BDNS): disociación de personas físicas, agregados y reparto en ficheros."""
from dinero_datos import analisis
from dinero_datos import fuentes as f


def test_personas_fisicas_por_nif():
    assert f.es_persona_fisica("12345678Z")      # DNI con letra de control válida
    assert f.es_persona_fisica("X1234567L")      # NIE válido
    assert f.es_persona_fisica("M1234567A")      # NIF K/L/M
    assert f.es_persona_fisica("12345678")       # 8 cifras sin letra: por prudencia, sí
    assert not f.es_persona_fisica("12345678X")  # letra de control incorrecta: no es un DNI
    assert not f.es_persona_fisica("B12345678")
    assert not f.es_persona_fisica("96232290583")  # identificador extranjero


def test_separar_beneficiario_disocia_personas():
    assert f.separar_beneficiario("B12345678 EMPRESA,  S.L. ") == ("B12345678", "EMPRESA, S.L.")
    assert f.separar_beneficiario("12345678Z GARCIA PEREZ JUAN") == ("", f.PERSONA_FISICA)
    assert f.tipo_nif("P2812500C") == "P" and f.tipo_nif("") == "fisica" and f.tipo_nif("89ESTRANGER") == "otro"


def _api(nif_nombre, imp, nivel="ESTADO", org="MINISTERIO"):
    return {"beneficiario": nif_nombre, "importe": imp, "nivel1": nivel, "nivel2": "X", "nivel3": org}


def test_partidos_agrega_por_nif():
    p = f.parse_partidos([
        _api("G28570927 PARTIDO POPULAR", 100), _api("G28570927 PARTIDO POPULAR DE CATALUNYA", 30, "AUTONOMICA"),
        _api("G28477727 PSOE", 120, "LOCAL"),
    ])
    assert p["concesiones"] == 3 and p["total"] == 250
    assert p["beneficiarios"][0] == ["G28570927", "PARTIDO POPULAR", 130, 2]
    assert p["por_nivel"] == {"ESTADO": 100, "LOCAL": 120, "AUTONOMICA": 30}
    assert list(p["por_nivel"]) == ["LOCAL", "ESTADO", "AUTONOMICA"]  # de mayor a menor


def _obj():
    lista = f.parse_grandes_beneficiarios([
        {"beneficiario": "B11111111 UNA SL", "ayudaETotal": 200000},
        {"beneficiario": "12345678Z PERSONA", "ayudaETotal": 150000},
        {"beneficiario": "P2812500C AYUNTAMIENTO", "ayudaETotal": 900000},
    ])
    return {"origen": f.BDNS_ORIGEN, "unidad": "euros", "umbral": f.BDNS_UMBRAL,
            "grandes": {"2025": {"total_fuente": 3, "lista": lista}},
            "partidos": {"2025": f.parse_partidos([_api("G1 PARTIDO", 10)])}}


def test_partir_y_unir_subvenciones():
    obj = _obj()
    partes = f.partir_subvenciones(obj)
    g = partes["subvenciones.json"]["grandes"]["2025"]
    assert g["beneficiarios"] == 3 and g["total"] == 1_250_000 and g["minimo"] == 150000
    assert g["por_tipo"]["P"] == [1, 900000] and g["por_tipo"]["fisica"] == [1, 150000]
    assert partes["subvenciones-2025.json"]["beneficiarios"][0][1] == "AYUNTAMIENTO"
    assert "PERSONA" not in str(partes)
    assert f.unir_subvenciones(partes["subvenciones.json"], partes.get) == obj


def test_comprobaciones_subvenciones():
    principal = f.partir_subvenciones(_obj())["subvenciones.json"]
    inf = analisis.Informe()
    analisis.comprobar_subvenciones(principal, inf)
    assert all(p["ok"] for p in inf.pruebas) and len(inf.pruebas) == 3
    principal["grandes"]["2025"]["total_fuente"] = 4
    inf = analisis.Informe()
    analisis.comprobar_subvenciones(principal, inf)
    assert not inf.pruebas[0]["ok"]


def _conc(num, eur, instr="SUBVENCIÓN y ENTREGA DINERARIA SIN CONTRAPRESTACIÓN ", tit="Convocatoria", n1="ESTADO"):
    return {"numeroConvocatoria": num, "ayudaEquivalente": eur, "instrumento": instr, "convocatoria": tit,
            "nivel1": n1, "nivel2": "MINISTERIO", "nivel3": "DG"}


def test_agrupar_concesiones_por_convocatoria():
    grupos, titulos = f.agrupar_concesiones([
        _conc("1", 100), _conc("1", 50), _conc("2", 500, "PRÉSTAMO", "Otra", "AUTONOMICA")])
    assert grupos == [["2", "PRÉSTAMO", 500, 1], ["1", "SUBVENCIÓN y ENTREGA DINERARIA SIN CONTRAPRESTACIÓN", 150, 2]]
    assert titulos["2"] == {"titulo": "Otra", "organo": ["AUTONOMICA", "MINISTERIO", "DG"]}


def test_resumen_motivos():
    convs = {
        "1": {**f.parse_convocatoria({"descripcion": "Plan", "descripcionFinalidad": "Sanidad",
                                      "tipoConvocatoria": "Concesión directa - instrumental", "mrr": True,
                                      "organo": {"nivel1": "ESTADO"}}), },
        "2": f.parse_convocatoria(None, {"titulo": "Pequeña", "organo": ["LOCAL", "", ""]}),
    }
    motivos = {"B1": {"total": 1000, "c": [["1", "SUBVENCIÓN", 900, 1], ["2", "SUBVENCIÓN", 100, 3]]},
               "P1": {"total": 900, "c": [["1", "PRÉSTAMO", 900, 1]]}}
    r = f.resumen_motivos(motivos, convs, 10_000)
    assert r["importe"] == 1900 and r["cobertura"] == 0.19 and r["mrr"] == 1800
    assert r["puestos"] == f.BDNS_TOP_MOTIVOS
    assert r["por_finalidad"] == {"Sanidad": 1800, f.SIN_CLASIFICAR: 100}
    assert r["por_procedimiento"] == {"Concesión directa": 1800, f.SIN_CLASIFICAR: 100}
    assert r["por_administracion"] == {"ESTADO": 1800, "LOCAL": 100}
    assert r["convocatorias"][0] == ["1", "Plan", 1800, 2]


def test_partir_y_unir_con_motivos():
    obj = _obj()
    obj["motivos"] = {"2025": {"P2812500C": {"total": 900000, "c": [["7", "SUBVENCIÓN", 900000, 2]]}}}
    obj["convocatorias"] = {"7": f.parse_convocatoria(None, {"titulo": "X", "organo": ["ESTADO", "", ""]})}
    partes = f.partir_subvenciones(obj)
    m = partes["subvenciones.json"]["grandes"]["2025"]["motivos"]
    assert m["fichero"] == "subvenciones-motivos-2025.json" and m["cobertura"] == 0.72
    assert partes["subvenciones-motivos-2025.json"]["convocatorias"]["7"]["titulo"] == "X"
    assert f.unir_subvenciones(partes["subvenciones.json"], partes.get) == obj
