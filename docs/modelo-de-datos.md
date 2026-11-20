# Modelo de datos de Dinero Público

Modelo sobre el que se cargan todas las fuentes en la plataforma (issue #4). La base principal es **documental (MongoDB)**, con un **grafo (Neo4j)** para las relaciones. Los JSON de `/datos/v1/` siguen siendo el formato publicado y el contrato entre la ingesta (Python) y los servicios (Quarkus).

## Ideas que lo guían

1. **Cuatro capas, cada una se rehace desde la anterior.**

   | Capa | Qué hay | Dónde |
   |---|---|---|
   | `raw` | Originales oficiales tal cual (privados) | PVC en cronos, con copia fuera de casa |
   | `publicado/v1` | JSON normalizados y comprobados (`informe.json`) | GitHub Pages; es el contrato con la plataforma |
   | servicio | Documentos en MongoDB y grafo en Neo4j | Clúster; Neo4j se rehace desde MongoDB |
   | análisis | Parquet por tabla (`curar`) | Descarga para DuckDB, pandas, R… |

   Nada se edita a mano en una capa intermedia.
2. **El dato oficial, sin retocar, con la forma de la fuente.** Un presupuesto es un documento con sus políticas y programas anidados; un contrato lleva dentro sus lotes y adjudicaciones. Lo calculado (administración, «es valor máximo», resúmenes por NIF) va en campos propios.
3. **El NIF une las fuentes.** La colección `entidades` tiene un documento por NIF con sus nombres en cada fuente y un resumen por año. En el grafo, el NIF es el nodo `Entidad`.
4. **Sin datos personales.** Las personas físicas se disocian en la ingesta, antes de `publicado/v1`: `nif` vacío y nombre «Persona física (nombre no publicado)». No llegan con nombre ni a MongoDB, ni a Neo4j, ni a la API.
5. **Euros exactos y territorios sin ambigüedad.** Los importes van en euros como `Decimal128`, para que las sumas cuadren al céntimo (los JSON de presupuestos están en millones y se convierten). Los territorios usan códigos NUTS (`ES`, `ES61`…).
6. **Trazabilidad.** La colección `cargas` registra cada carga: fuente, hash, fechas, documentos, versión y error. Cada documento lleva `carga` con el id de la última que lo tocó. Los change streams de `cargas` son también los eventos entre servicios.

## Colecciones (MongoDB, base `dinero`)

Cada colección tiene un validador `$jsonSchema` y sus índices.

| Colección | `_id` | Contenido | Sale de |
|---|---|---|---|
| `contratos` | id de licitación de la Plataforma | `organo {id, nombre, nif, administracion}`, objeto, expediente, tipo, procedimiento, sistema, CPV, `territorio` (NUTS), `fondosUe`, enlace y `adjudicaciones: [{lote, adjudicatario {nif, nombre}, fecha, sinIva, conIva, ofertas, pyme, valorMaximo, compartido}]` | `contratos-AAAA-MM.json` |
| `subvenciones` | `AAAA:nif` (`AAAA:#puesto` si es persona física) | `anio`, `beneficiario {nif, nombre, tipo}`, `importeEquivalente`, `puesto` y `concesiones: [{convocatoria, instrumento, importe, n}]` (solo los 1.000 mayores) | `subvenciones-AAAA.json`, `subvenciones-motivos-AAAA.json` |
| `convocatorias` | código BDNS | título, finalidad, `organo`, procedimiento, MRR y si se consultó su ficha | `subvenciones-motivos-AAAA.json` |
| `partidos` | `AAAA:nif` | importe, concesiones y los órganos que conceden | `subvenciones.json` |
| `entidades` | NIF | `tipo`, `esPublica`, `nombres: [{nombre, fuente, desde, hasta}]` y `resumen: {"2025": {subvenciones, contratosGanados {n, importe}, contratosAdjudicados {n, importe}}}` | Calculada por el cargador con `$merge` |
| `organos` | hash de fuente, nombre, NIF y superior (`curado.id_organo`) | nombre, NIF, administración, superior y fuente | Contratos y BDNS |
| `presupuestos` | `estado:2025-P`, `ccaa:2025:ES61` | ejercicio en que rige, si es prórroga y de qué base, y `politicas: [{codigo, nombre, area, credito, programas \| capitulos}]` más la clasificación económica en las comunidades | `pge.json`, `ccaa.json` |
| `series` (*time series*) | — | `fecha`, `meta {serie, territorio, concepto, bloque, nivel}`, `valor` y `provisional`. Una serie por partida de la ejecución mensual, por población, por concepto de las entregas y por división COFOG | `estado.json`, `poblacion.json`, `entregas.json`, `cofog.json` |
| `catalogos` | `lista:codigo` | territorios (NUTS, código SGCIEF, foral), tipos de NIF, tipos de contrato, procedimientos, sistemas, divisiones COFOG y clasificación económica | Código y JSON |
| `cargas` | ObjectId | fuente, hash, inicio, fin, estado, documentos, versión y error | El cargador |

Para buscar y filtrar:
- índices de texto (idioma `spanish`, sin distinguir tildes) sobre `contratos.objeto`, `convocatorias.titulo` y `entidades.nombres.nombre`;
- índices compuestos para las facetas: `contratos` por fecha de adjudicación, administración, tipo y procedimiento; `subvenciones` por año e importe; NIF de adjudicatario y de beneficiario.

## Grafo (Neo4j)

```
(:Organo)-[:ADJUDICA]->(:Contrato)<-[:GANA {lote, importe, fecha}]-(:Entidad {nif})
(:Organo)-[:CONVOCA]->(:Convocatoria)-[:CONCEDE {anio, importe}]->(:Entidad)
(:Organo)-[:ES]->(:Entidad)            cuando el órgano tiene NIF
(:Contrato)-[:EN]->(:Territorio {nuts})
```

Lo alimenta el servicio `grafo` desde los change streams de `contratos`, `subvenciones` y `convocatorias`. Responde preguntas que en documentos o tablas son costosas:
- quién gana contratos y recibe subvenciones del mismo órgano;
- qué órganos concentran sus adjudicaciones en pocas empresas;
- redes de contratos con una sola oferta;
- el camino más corto entre dos NIF.

## Formas de explotar los datos

| Para quién | Cómo |
|---|---|
| Público general | La web: resúmenes estáticos y buscador, primero contra la API y, si no responde, contra los JSON |
| Desarrolladores | API REST con OpenAPI (búsqueda facetada, ficha por NIF, agregados) y descargas NDJSON |
| Analistas | Parquet + DuckDB o pandas, sin servidor; o los JSON v1 |
| Exploración sin programar | Metabase sobre MongoDB (red local) |
| Relaciones | Neo4j Browser con Cypher (red local) y los endpoints `/v1/grafo/...` |

## Comprobaciones tras cada carga

- Los totales por año en MongoDB coinciden con los de `contratos.json` y `subvenciones.json` (contratos de 2025: 74.703 M€, más 9.451 M€ de valor máximo).
- Ningún documento tiene el nombre de una persona física.
- Cada adjudicación apunta a un órgano existente.
- Cargar dos veces la misma fuente no cambia el número de documentos.
