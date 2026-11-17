# Dinero Público · datos

Herramienta que **descarga, analiza y transforma** los datos oficiales del gasto público en España (Ministerio de Hacienda e INE) y los publica como JSON abiertos en:

**https://dinero-publico.github.io/datos/**

Es la fuente de datos de la web [dinero-publico.github.io](https://dinero-publico.github.io/), que está en otro repositorio ([dinero-publico.github.io](https://github.com/dinero-publico/dinero-publico.github.io)) y solo lee estos ficheros. Así la obtención de datos y la web van por separado: la web no descarga nada y se puede cambiar sin tocar los datos, y al revés.

```
Hacienda / INE ──► descargar ──► transformar ──► analizar ──► publicar ──► /datos/v1/*.json ──► web
                   (raw/)        (JSON)          (derivados    (catálogo)
                                                  + informe)
```

## Pasos

| Paso | Qué hace |
|---|---|
| `descargar` | Descarga los originales de cada fuente (copia en `raw/`) y los transforma a JSON normalizado. |
| `transformar` | Vuelve a transformar los originales de `raw/` sin usar la red (útil al cambiar un parser). |
| `analizar` | Añade datos derivados y comprueba la coherencia de cada fuente. Deja el resultado en `informe.json`. |
| `publicar` | Escribe `catalogo.json` (ficheros, tamaño, sha256, fecha) y la página `index.html`. |
| `todo` | `descargar` + `analizar` + `publicar`: lo que hace el workflow cada día. |

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m dinero_datos todo                        # todo el proceso
python -m dinero_datos descargar --only entregas   # solo una fuente
python -m dinero_datos transformar                 # reprocesar raw/ sin red
python -m dinero_datos analizar                    # derivados + informe
python -m pytest -q                                # tests con Excel oficiales reales
```

Cada fuente se procesa por separado: si una falla, se conserva su último JSON válido y el error queda en `meta.json`.

### Análisis

- **Años de los Presupuestos del Estado** (`pge.json` → `ejercicios`): la SEPG etiqueta cada prórroga con el año del que procede («2025-P» es el presupuesto de 2025 prorrogado para 2026). El análisis da el año en que rige cada columna, si es prórroga y de qué presupuesto aprobado procede.
- **Presupuestos autonómicos prorrogados** (`ccaa.json` → `prorrogados`): Hacienda no los señala. Se marca como prorrogado el presupuesto que repite el total exacto o al menos cinco políticas al céntimo del año anterior (con presupuesto nuevo casi nunca coinciden más de dos o tres). Indica también desde qué año no hay presupuesto propio.
- **Comprobaciones** (`informe.json`): sumas de políticas, programas, capítulos, clasificación económica, conceptos de las entregas y divisiones COFOG frente a sus totales; comunidades y años presentes; población de España frente a la suma de territorios. Las diferencias que explica la propia fuente se anotan como avisos.

## Datos publicados (`publicado/v1/`)

| Fichero | Contenido | Fuente |
|---|---|---|
| `estado.json` | Ejecución mensual del Estado en contabilidad nacional (SEC 2010), diez años | IGAE |
| `pge.json` | PGE consolidados por política y programa, con `ejercicios` | SEPG |
| `entregas.json` | Entregas a cuenta del sistema de financiación por comunidad y concepto | S. G. de Financiación Autonómica y Local |
| `ccaa.json` | Presupuestos iniciales de cada comunidad por política, capítulo y clasificación económica, con `prorrogados` | SGCIEF |
| `cofog.json` | Gasto ejecutado por función (COFOG) de cada administración y comunidad | IGAE |
| `poblacion.json` | Población a 1 de enero por comunidad | INE |
| `meta.json` | Fecha en que cambió cada fuente y último error | — |
| `informe.json` | Resultado de las comprobaciones | — |
| `catalogo.json` | Lista de ficheros con tamaño, sha256 y fecha | — |

Importes en millones de euros corrientes. `v1` es la versión del formato: si cambia la estructura de los JSON de forma incompatible, se publicará en `v2` y `v1` se mantendrá un tiempo.

El historial de git de `publicado/` es también el historial de los datos. El histórico anterior a la separación está en el repositorio de la web (carpeta `data/`).

## Puesta en marcha y actualización

El workflow `.github/workflows/datos.yml` se ejecuta cada día a las 07:17 UTC: tests, descarga, análisis, commit de `publicado/` si hay cambios y publicación en GitHub Pages (Settings → Pages → Source: GitHub Actions).

> **Entregas a cuenta:** `www.hacienda.gob.es` no responde a los servidores de GitHub, así que esa fuente hay que actualizarla desde un ordenador en España:
> ```bash
> python -m dinero_datos descargar --only entregas && python -m dinero_datos analizar && python -m dinero_datos publicar
> git add publicado && git commit -m "Entregas a cuenta actualizadas" && git push
> ```
> Alternativa: un [runner autoalojado](https://docs.github.com/es/actions/hosting-your-own-runners) (`runs-on: self-hosted`).

## Licencia

Código: MIT (ver `LICENSE`). Datos: Ministerio de Hacienda e INE, según sus condiciones de reutilización ([aviso legal de Hacienda](https://www.hacienda.gob.es/es-ES/Paginas/Avisolegal.aspx), [INE](https://www.ine.es/aviso_legal)).
