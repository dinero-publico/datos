"""Herramienta de datos de Dinero Público.

Pasos:
  descargar   Descarga los originales de cada fuente (copia en raw/) y los transforma a JSON.
  transformar Vuelve a transformar los originales guardados en raw/, sin usar la red.
  analizar    Añade los datos derivados (prórrogas, años de cada ejercicio) y comprueba
              la coherencia de cada fuente (informe.json).
  publicar    Escribe el catálogo (catalogo.json e index.html) de lo publicado.
  curar       Reparte lo publicado en tablas Parquet para análisis (curated/).
  avisar      Avisa al cargador de la plataforma (DINERO_CARGADOR) del hash de cada fuente.
  todo        descargar + analizar + publicar (lo que hace el workflow cada día).

Ejemplos:
  python -m dinero_datos todo
  python -m dinero_datos descargar --only entregas
  python -m dinero_datos transformar && python -m dinero_datos analizar

Los JSON se escriben en publicado/v1/ y los Parquet en curated/. Las carpetas se pueden
cambiar con DINERO_RAW, DINERO_PUBLICADO y DINERO_CURATED (así se usan en el contenedor).
Cada fuente se procesa por separado: si una falla, se conserva su último JSON válido y el error queda anotado en meta.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import logging
import os
import sys
from pathlib import Path

from . import analisis
from . import contratos
from . import fuentes as f

ROOT = Path(__file__).resolve().parents[1]
# Carpetas configurables con variables de entorno (en el contenedor apuntan a sus volúmenes).
PUBLICADO = Path(os.environ.get("DINERO_PUBLICADO") or ROOT / "publicado")
CURATED = Path(os.environ.get("DINERO_CURATED") or ROOT / "curated")
SALIDA = PUBLICADO / "v1"  # versión del formato: cambia si cambia la estructura de los JSON
URL_PUBLICA = "https://dinero-publico.github.io/datos/v1/"

log = logging.getLogger("dinero_datos")

FUENTES = {
    "estado": ("estado.json", "Ejecución mensual del Estado en contabilidad nacional (IGAE)"),
    "pge": ("pge.json", "Presupuestos Generales del Estado consolidados por política y programa (SEPG)"),
    "entregas": ("entregas.json", "Entregas a cuenta del sistema de financiación autonómica (SGFAL)"),
    "ccaa": ("ccaa.json", "Presupuestos iniciales de las comunidades por política, capítulo y clasificación económica (SGCIEF)"),
    "cofog": ("cofog.json", "Gasto ejecutado por función (COFOG) de cada administración y comunidad (IGAE)"),
    "poblacion": ("poblacion.json", "Población residente a 1 de enero por comunidad (INE)"),
    "subvenciones": ("subvenciones.json", "Grandes beneficiarios de subvenciones y ayudas (100.000 € o más en el año) y subvenciones a partidos políticos (BDNS, IGAE)"),
    "contratos": ("contratos.json", "Adjudicaciones de contratos públicos de la Plataforma de Contratación del Sector Público: resúmenes por año"),
}
# Fuentes que no se procesan salvo que se pidan con --only: la Plataforma de Contratación
# limita mucho la velocidad de descarga y sus ficheros ocupan varios GB, así que se
# actualiza desde un ordenador local (ver README).
SOLO_A_PETICION = {"contratos"}
# Fuentes que se publican en varios ficheros: el principal más «<nombre>-<parte>.json».
LISTAS = {"subvenciones": lambda parte: (
    f"Concesiones de los mayores beneficiarios de {parte.split('-')[-1]}, agrupadas por convocatoria, con su finalidad (BDNS, IGAE)"
    if parte.startswith("motivos-") else f"Lista completa de grandes beneficiarios de {parte} (BDNS, IGAE)"),
    "contratos": lambda parte: (
        f"Lo adjudicado a cada adjudicatario (NIF) en {parte.split('-')[-1]}: número de adjudicaciones e importe sin IVA"
        if parte.startswith("adjudicatarios-") else f"Cada adjudicación de contratos de {parte} (año-mes de adjudicación; Plataforma de Contratación del Sector Público)"),
}


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def leer(nombre: str) -> dict | None:
    p = SALIDA / nombre
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def escribir(nombre: str, obj) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, dict) and nombre.startswith(("subvenciones-", "contratos-")):
        # Ficheros largos: un elemento por línea (diffs legibles y ficheros pequeños).
        d = lambda x: json.dumps(x, ensure_ascii=False)
        partes = []
        for k, v in obj.items():
            if isinstance(v, list) and len(v) > 50:
                partes.append(f"{d(k)}: [\n" + ",\n".join(d(x) for x in v) + "\n]")
            elif isinstance(v, dict) and len(v) > 50:
                partes.append(f"{d(k)}: {{\n" + ",\n".join(f"{d(i)}: {d(x)}" for i, x in v.items()) + "\n}")
            else:
                partes.append(f"{d(k)}: {d(v)}")
        texto = "{" + ",\n".join(partes) + "}"
    else:
        texto = json.dumps(obj, ensure_ascii=False, indent=1)
    (SALIDA / nombre).write_text(texto + "\n", encoding="utf-8")


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Descarga y transformación
# --------------------------------------------------------------------------- #
def descargar(only: list[str] | None, offline: Path | None, year: int, delay: float, max_peticiones: int = f.BDNS_MAX_PETICIONES) -> int:
    dl = f.Downloader(offline, delay=0 if offline else delay)
    anios = list(range(year, year - f.YEARS_BACK - 1, -1))  # el año en curso y los diez anteriores

    def previo(nombre):
        d = leer(nombre)
        return analisis.sin_derivadas(nombre, d) if d else None

    trabajos = {
        "estado": lambda: f.fetch_estado(dl, anios),
        "pge": lambda: f.fetch_pge(dl),
        "entregas": lambda: f.fetch_entregas(dl),
        "ccaa": lambda: f.fetch_ccaa(dl, anios, previo("ccaa.json"), reuse_before=year - 1),
        "cofog": lambda: f.fetch_cofog(dl, desde=year - f.YEARS_BACK - 2),
        "poblacion": lambda: f.fetch_poblacion(dl, desde=year - f.YEARS_BACK - 2),
        "subvenciones": lambda: f.fetch_subvenciones(dl, f.unir_subvenciones(leer("subvenciones.json"), leer), year, max_peticiones),
        "contratos": lambda: contratos.fetch_contratos(offline=offline is not None),
    }
    meta = leer("meta.json") or {}
    meta.setdefault("fuentes", {})
    fatal = False
    for clave, trabajo in trabajos.items():
        if (only and clave not in only) or (not only and clave in SOLO_A_PETICION):
            continue
        nombre = FUENTES[clave][0]
        log.info("▶ %s", clave)
        info = meta["fuentes"].get(clave, {})
        try:
            obj = trabajo()
            h = digest(obj)
            salidas = (f.partir_subvenciones(obj) if clave == "subvenciones" else obj if clave == "contratos" else {nombre: obj})
            if h != info.get("hash") or any(not (SALIDA / n).exists() for n in salidas):
                # Se conservan los datos derivados del análisis anterior hasta que se vuelva a analizar.
                for n, o in salidas.items():
                    escribir(n, analisis.enriquecer(n, o))
                info["descargado"] = ahora()
                info["hash"] = h
                log.info("  ✔ actualizado %s", nombre)
            else:
                log.info("  = sin cambios")
            info.pop("error", None)
            info.pop("error_fecha", None)
            info["fichero"] = nombre
        except Exception as e:  # una fuente rota no debe tumbar las demás
            log.error("  ✘ %s: %s", clave, e)
            info["error"] = f"{type(e).__name__}: {e}"
            info["error_fecha"] = ahora()
            if not (SALIDA / nombre).exists():
                fatal = True
        meta["fuentes"][clave] = info
    escribir("meta.json", meta)
    return 1 if fatal else 0


# --------------------------------------------------------------------------- #
# Análisis
# --------------------------------------------------------------------------- #
def analizar() -> int:
    datos = {}
    for nombre, _ in FUENTES.values():
        d = leer(nombre)
        if d is None:
            continue
        nuevo = analisis.enriquecer(nombre, d)
        if nuevo != d:
            escribir(nombre, nuevo)
            log.info("  ✔ datos derivados actualizados en %s", nombre)
        datos[nombre] = nuevo
    inf = analisis.informe(datos)
    anterior = leer("informe.json")
    # Solo se reescribe si cambian los resultados, para no generar commits vacíos cada día.
    if not anterior or anterior.get("pruebas") != inf["pruebas"]:
        escribir("informe.json", inf)
    r = inf["resumen"]
    log.info("Comprobaciones: %d de %d correctas", r["correctas"], r["pruebas"])
    for p in inf["pruebas"]:
        if not p["ok"]:
            log.warning("  ✘ %s · %s: %s", p["fuente"], p["prueba"], "; ".join(p["fallos"][:3]))
    return 0


# --------------------------------------------------------------------------- #
# Publicación: catálogo legible por máquinas y por personas
# --------------------------------------------------------------------------- #
def publicar() -> int:
    meta = (leer("meta.json") or {}).get("fuentes", {})
    inf = leer("informe.json") or {}
    ficheros = {}
    for clave, (nombre, desc) in FUENTES.items():
        p = SALIDA / nombre
        if not p.exists():
            continue
        m = meta.get(clave, {})
        partes = [(clave, p, desc)]
        if clave in LISTAS:
            stem = Path(nombre).stem
            for q in sorted(SALIDA.glob(f"{stem}-*.json"), reverse=True):
                parte = q.stem[len(stem) + 1:]
                partes.append((f"{clave}-{parte}", q, LISTAS[clave](parte)))
        for k, q, d in partes:
            ficheros[k] = {
                "fichero": q.name, "url": URL_PUBLICA + q.name, "descripcion": d, "bytes": q.stat().st_size,
                "sha256": hashlib.sha256(q.read_bytes()).hexdigest(), "actualizado": m.get("descargado"),
                "ultimo_error": m.get("error_fecha") if m.get("error") else None,
            }
    cat = {"version": 1, "proyecto": "https://dinero-publico.github.io/", "ficheros": ficheros,
           "informe": URL_PUBLICA + "informe.json", "meta": URL_PUBLICA + "meta.json"}
    if cat != leer("catalogo.json"):
        escribir("catalogo.json", cat)
    filas = "".join(
        f"<tr><td><a href=\"v1/{html.escape(x['fichero'])}\">{html.escape(x['fichero'])}</a></td><td>{html.escape(x['descripcion'])}</td>"
        f"<td>{(x['actualizado'] or '—')[:10]}</td><td>{x['bytes'] // 1024} kB</td></tr>"
        for x in ficheros.values())
    r = inf.get("resumen", {})
    (PUBLICADO / "index.html").write_text(PLANTILLA.format(filas=filas,
        informe=f"{r.get('correctas', '—')} de {r.get('pruebas', '—')} comprobaciones de coherencia correctas"), encoding="utf-8")
    log.info("Catálogo: %d ficheros", len(ficheros))
    return 0


# --------------------------------------------------------------------------- #
# Aviso a la plataforma: el cargador compara los hashes y carga solo lo que cambió
# --------------------------------------------------------------------------- #
def avisar(url: str | None) -> int:
    if not url:
        log.error("Falta la URL del cargador (--cargador o DINERO_CARGADOR)")
        return 2
    meta = (leer("meta.json") or {}).get("fuentes", {})
    cuerpo = {"fuentes": {k: {"hash": v.get("hash"), "fichero": v.get("fichero"), "descargado": v.get("descargado")}
                          for k, v in meta.items() if v.get("hash")}}
    import requests
    r = requests.post(url.rstrip("/") + "/cargas", json=cuerpo, timeout=30)
    log.info("Cargador: %s %s", r.status_code, r.text[:200])
    return 0 if r.ok else 1


PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Datos · Dinero Público</title>
<meta name="description" content="Datos abiertos de Dinero Público: presupuestos y gasto público de España normalizados a JSON a partir de Hacienda e INE.">
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--a:#2f6db5;color-scheme:light dark;font-family:system-ui,sans-serif}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--a:#6aa1e0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);line-height:1.5}}main{{max-width:960px;margin:0 auto;padding:24px 16px}}
a{{color:var(--a)}}h1{{font-family:Georgia,serif;font-weight:400}}.muted{{color:var(--muted)}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.92rem}}td,th{{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:500}}code{{font-size:.9em}}
</style></head><body><main>
<h1>Datos de Dinero Público</h1>
<p>Presupuestos, gasto público y subvenciones de España, descargados cada día de las fuentes oficiales (Ministerio de Hacienda, IGAE e INE), comprobados y normalizados a JSON. Son los datos que usa <a href="https://dinero-publico.github.io/">dinero-publico.github.io</a>.</p>
<p class="muted">{informe} · <a href="v1/informe.json">informe</a> · <a href="v1/catalogo.json">catálogo</a> · <a href="v1/meta.json">estado de las descargas</a> · <a href="https://github.com/dinero-publico/datos">código de la herramienta</a></p>
<div class="scroll"><table><thead><tr><th>Fichero</th><th>Contenido</th><th>Actualizado</th><th>Tamaño</th></tr></thead><tbody>{filas}</tbody></table></div>
<p class="muted">Formato estable bajo <code>/datos/v1/</code>. Los datos proceden del Ministerio de Hacienda y del INE y se reutilizan según sus condiciones. Subvenciones: origen de los datos, Intervención General de la Administración del Estado (BDNS); Dinero Público no publica los nombres de las personas físicas. Detalle de cada fuente en <a href="https://dinero-publico.github.io/fuentes.html">Fuentes y metodología</a>.</p>
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dinero_datos", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paso", choices=["descargar", "transformar", "analizar", "publicar", "curar", "avisar", "todo"])
    ap.add_argument("--only", choices=list(FUENTES), action="append", help="procesar solo estas fuentes (descargar/transformar/todo)")
    ap.add_argument("--year", type=int, default=dt.date.today().year, help="año de referencia (por defecto, el actual)")
    ap.add_argument("--delay", type=float, default=1.0, help="segundos de espera entre peticiones")
    ap.add_argument("--max-peticiones", type=int, default=f.BDNS_MAX_PETICIONES,
                    help="consultas a la BDNS por ejecución para los motivos de las subvenciones")
    ap.add_argument("--cargador", default=os.environ.get("DINERO_CARGADOR"),
                    help="URL del cargador para «avisar» (por defecto, DINERO_CARGADOR)")
    ap.add_argument("--raw", type=Path, default=f.RAW_DIR, help="carpeta de originales para «transformar» (por defecto raw/)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.paso == "descargar":
        return descargar(a.only, None, a.year, a.delay, a.max_peticiones)
    if a.paso == "transformar":
        return descargar(a.only, a.raw, a.year, a.delay)
    if a.paso == "analizar":
        return analizar()
    if a.paso == "publicar":
        return publicar()
    if a.paso == "avisar":
        return avisar(a.cargador)
    if a.paso == "curar":
        from . import curado
        curado.exportar(SALIDA, CURATED)
        return 0
    rc = descargar(a.only, None, a.year, a.delay, a.max_peticiones)
    analizar()
    publicar()
    return rc


if __name__ == "__main__":
    sys.exit(main())
