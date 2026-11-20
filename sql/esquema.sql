-- Esquema de la plataforma de datos de Dinero Público (PostgreSQL 16 o posterior).
--
-- Es la definición única de las tablas del modelo (docs/modelo-de-datos.md):
-- `python -m dinero_datos curar` escribe un Parquet por tabla en curated/ con
-- exactamente estas columnas (menos carga_id, que pone el paso de carga), y los
-- tests comprueban que coinciden.
--
-- Reglas:
--   · Importes en euros, numeric(16,2). Las fuentes que publican millones se convierten.
--   · Territorios por código NUTS (ES = España, ES61 = Andalucía…).
--   · Personas físicas: nif NULL y nombre «Persona física (nombre no publicado)».
--   · Una columna por línea dentro de cada CREATE TABLE (lo lee dinero_datos/curado.py).

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE SCHEMA IF NOT EXISTS dinero;
SET search_path = dinero, public;

-- --------------------------------------------------------------------------
-- Trazabilidad
-- --------------------------------------------------------------------------
CREATE TABLE fuente (
    id text PRIMARY KEY,                -- bdns, placsp, sepg, sgcief, sgfal, igae_cn, igae_cofog, ine
    organismo text NOT NULL,
    nombre text NOT NULL,
    url text,
    aviso_legal text,
    periodicidad text
);

CREATE TABLE carga (
    id bigserial PRIMARY KEY,
    fuente_id text NOT NULL REFERENCES fuente (id),
    inicio timestamptz NOT NULL,
    fin timestamptz,
    estado text NOT NULL,               -- en_curso, correcta, fallida
    sha256_original text,
    filas bigint,
    version_herramienta text,
    error text
);

-- --------------------------------------------------------------------------
-- Catálogos
-- --------------------------------------------------------------------------
CREATE TABLE territorio (
    codigo text PRIMARY KEY,            -- NUTS: ES, ES11…ES70
    nombre text NOT NULL,               -- nombre corto, igual en todas las fuentes
    nivel text NOT NULL,                -- pais, comunidad
    codigo_sgcief text,                 -- código de Hacienda (01…17), sin Ceuta ni Melilla
    foral boolean NOT NULL
);

CREATE TABLE codigo_lista (
    lista text NOT NULL,                -- tipo_nif, contrato_tipo, contrato_procedimiento, contrato_sistema
    codigo text NOT NULL,
    nombre text NOT NULL,
    PRIMARY KEY (lista, codigo)
);

CREATE TABLE politica (
    codigo text PRIMARY KEY,            -- clasificación por programas: 11, 12…
    nombre text NOT NULL,
    area text
);

CREATE TABLE programa (
    codigo text PRIMARY KEY,
    nombre text NOT NULL,
    politica text NOT NULL REFERENCES politica (codigo)
);

CREATE TABLE economica (
    codigo text PRIMARY KEY,            -- 1 cifra capítulo, 2 artículo, 3 concepto, 4 subconcepto
    nombre text NOT NULL,
    capitulo smallint NOT NULL
);

CREATE TABLE cofog_division (
    codigo text PRIMARY KEY,            -- 01…10
    nombre text NOT NULL
);

CREATE TABLE entidad (
    nif text PRIMARY KEY,
    tipo_nif text NOT NULL,             -- primera letra (A, B, P, Q, S…) u «otro»; codigo_lista tipo_nif
    nombre text NOT NULL,               -- el más reciente
    es_publica boolean NOT NULL
);

CREATE TABLE entidad_nombre (
    nif text NOT NULL REFERENCES entidad (nif),
    nombre text NOT NULL,
    fuente_id text NOT NULL,
    primer_anio smallint NOT NULL,
    ultimo_anio smallint NOT NULL,
    PRIMARY KEY (nif, nombre, fuente_id)
);

CREATE TABLE organo (
    id text PRIMARY KEY,                -- hash de fuente, nombre, NIF y superior
    fuente_id text NOT NULL,
    nombre text NOT NULL,
    nif text,
    administracion text,                -- Estado, Comunidades autónomas, Entidades locales… (contratos) o ESTADO, AUTONOMICA, LOCAL… (BDNS)
    superior text
);

-- --------------------------------------------------------------------------
-- Subvenciones (BDNS)
-- --------------------------------------------------------------------------
CREATE TABLE subvencion_anual (
    anio smallint NOT NULL,
    puesto integer NOT NULL,
    nif text,
    nombre text NOT NULL,
    importe_equivalente numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, puesto)
);

CREATE TABLE convocatoria (
    codigo text PRIMARY KEY,            -- código BDNS
    titulo text,
    finalidad text,
    organo_id text REFERENCES organo (id),
    procedimiento text,
    mrr boolean,
    detalle boolean NOT NULL,           -- se consultó su ficha en la BDNS
    carga_id bigint REFERENCES carga (id)
);

CREATE TABLE subvencion_concesion (
    anio smallint NOT NULL,
    nif text NOT NULL,
    convocatoria text NOT NULL REFERENCES convocatoria (codigo),
    instrumento text NOT NULL,
    importe numeric(16,2) NOT NULL,
    concesiones integer NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, nif, convocatoria, instrumento)
);

CREATE TABLE subvencion_partido (
    anio smallint NOT NULL,
    nif text NOT NULL,
    nombre text NOT NULL,
    importe numeric(16,2) NOT NULL,
    concesiones integer NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, nif)
);

CREATE TABLE subvencion_partido_organo (
    anio smallint NOT NULL,
    organo_id text NOT NULL REFERENCES organo (id),
    importe numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, organo_id)
);

-- --------------------------------------------------------------------------
-- Contratos (Plataforma de Contratación del Sector Público)
-- --------------------------------------------------------------------------
CREATE TABLE licitacion (
    id bigint PRIMARY KEY,              -- id de la Plataforma
    fuente_id text NOT NULL,
    enlace text,
    organo_id text NOT NULL REFERENCES organo (id),
    expediente text,
    objeto text,
    tipo text,                          -- codigo_lista contrato_tipo
    procedimiento text,                 -- codigo_lista contrato_procedimiento
    sistema text,                       -- codigo_lista contrato_sistema
    cpv text,
    territorio text,                    -- NUTS de ejecución (puede ser provincia: ES618)
    fondos_ue boolean,
    carga_id bigint REFERENCES carga (id)
);

CREATE TABLE adjudicacion (
    licitacion_id bigint NOT NULL REFERENCES licitacion (id),
    lote text NOT NULL,
    nif text,
    nombre text NOT NULL,
    objeto text,                        -- el de la fila (puede ser el del lote)
    fecha date,
    importe_sin_iva numeric(16,2),
    importe_con_iva numeric(16,2),
    ofertas integer,
    pyme boolean,
    es_valor_maximo boolean NOT NULL,   -- acuerdo marco o SDA: tope, no gasto; no suma
    importe_compartido boolean NOT NULL, -- el mismo importe ya contado para otro adjudicatario del lote
    carga_id bigint REFERENCES carga (id)
);

-- --------------------------------------------------------------------------
-- Presupuestos y gasto
-- --------------------------------------------------------------------------
CREATE TABLE presupuesto_estado (
    columna text NOT NULL,              -- etiqueta de la SEPG: 2023, 2023-P…
    ejercicio smallint NOT NULL,        -- año en que rige
    prorrogado boolean NOT NULL,
    base smallint,                      -- presupuesto aprobado del que procede la prórroga
    programa text NOT NULL REFERENCES programa (codigo),
    credito_inicial numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (columna, programa)
);

CREATE TABLE presupuesto_ccaa (
    anio smallint NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    politica text NOT NULL,
    capitulo smallint NOT NULL,
    credito_inicial numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, territorio, politica, capitulo)
);

CREATE TABLE presupuesto_ccaa_economica (
    anio smallint NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    economica text NOT NULL,
    credito_inicial numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, territorio, economica)
);

CREATE TABLE presupuesto_ccaa_prorroga (  -- deducido por el análisis, no lo publica Hacienda
    anio smallint NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    base smallint NOT NULL,
    politicas_iguales integer NOT NULL,
    politicas integer NOT NULL,
    mismo_total boolean NOT NULL,
    PRIMARY KEY (anio, territorio)
);

CREATE TABLE entrega_a_cuenta (
    anio smallint NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    concepto text NOT NULL,             -- irpf, iva, impuestos_especiales, fondo_suficiencia, fondo_garantia…
    importe numeric(16,2) NOT NULL,
    norma text,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, territorio, concepto)
);

CREATE TABLE gasto_cofog (
    anio smallint NOT NULL,
    subsector text NOT NULL,            -- central, regional, local, seguridad_social
    territorio text NOT NULL REFERENCES territorio (codigo),
    division text NOT NULL REFERENCES cofog_division (codigo),
    importe numeric(16,2) NOT NULL,
    provisional boolean NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, subsector, territorio, division)
);

CREATE TABLE gasto_cofog_total (
    anio smallint NOT NULL,
    subsector text NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    total numeric(16,2) NOT NULL,
    transferencias_aapp numeric(16,2),  -- transferencias a otras administraciones (solo España)
    provisional boolean NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, subsector, territorio)
);

CREATE TABLE ejecucion_estado (
    anio smallint NOT NULL,
    mes smallint NOT NULL,
    orden smallint NOT NULL,            -- posición en la tabla de la IGAE (da la jerarquía con nivel)
    bloque text NOT NULL,               -- recursos, empleos…
    nivel smallint NOT NULL,
    codigo text,                        -- código SEC 2010 (P.11…), vacío en los agregados
    concepto text NOT NULL,
    importe_acumulado numeric(16,2),
    provisional boolean NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, mes, orden)
);

CREATE TABLE pib (
    anio smallint PRIMARY KEY,
    importe numeric(16,2) NOT NULL,
    carga_id bigint REFERENCES carga (id)
);

CREATE TABLE poblacion (
    anio smallint NOT NULL,
    territorio text NOT NULL REFERENCES territorio (codigo),
    habitantes integer NOT NULL,
    provisional boolean NOT NULL,
    carga_id bigint REFERENCES carga (id),
    PRIMARY KEY (anio, territorio)
);

-- --------------------------------------------------------------------------
-- Índices para la búsqueda y los cruces
-- --------------------------------------------------------------------------
CREATE INDEX ON subvencion_anual (nif);
CREATE INDEX ON subvencion_concesion (convocatoria);
CREATE INDEX ON adjudicacion (nif);
CREATE INDEX ON adjudicacion (licitacion_id);
CREATE INDEX ON adjudicacion (fecha);
CREATE INDEX ON licitacion (organo_id);
CREATE INDEX entidad_nombre_trgm ON entidad USING gin (nombre gin_trgm_ops);
CREATE INDEX licitacion_objeto_trgm ON licitacion USING gin (objeto gin_trgm_ops);
CREATE INDEX convocatoria_titulo_trgm ON convocatoria USING gin (titulo gin_trgm_ops);

-- --------------------------------------------------------------------------
-- Vistas
-- --------------------------------------------------------------------------

-- Todo lo de un NIF por año: lo que hoy cruza el navegador.
CREATE VIEW entidad_resumen AS
WITH sub AS (
    SELECT nif, anio, sum(importe_equivalente) AS subvenciones
    FROM subvencion_anual WHERE nif IS NOT NULL GROUP BY nif, anio
), gana AS (
    SELECT nif, extract(year FROM fecha)::smallint AS anio,
           count(*) AS contratos_ganados,
           sum(importe_sin_iva) FILTER (WHERE NOT es_valor_maximo AND NOT importe_compartido) AS contratos_ganados_importe
    FROM adjudicacion WHERE nif IS NOT NULL AND fecha IS NOT NULL GROUP BY nif, extract(year FROM fecha)
), adjudica AS (
    SELECT o.nif, extract(year FROM a.fecha)::smallint AS anio,
           count(*) AS contratos_adjudicados,
           sum(a.importe_sin_iva) FILTER (WHERE NOT a.es_valor_maximo AND NOT a.importe_compartido) AS contratos_adjudicados_importe
    FROM adjudicacion a JOIN licitacion l ON l.id = a.licitacion_id JOIN organo o ON o.id = l.organo_id
    WHERE o.nif IS NOT NULL AND a.fecha IS NOT NULL GROUP BY o.nif, extract(year FROM a.fecha)
)
SELECT coalesce(s.nif, g.nif, d.nif) AS nif,
       coalesce(s.anio, g.anio, d.anio) AS anio,
       s.subvenciones, g.contratos_ganados, g.contratos_ganados_importe,
       d.contratos_adjudicados, d.contratos_adjudicados_importe
FROM sub s
FULL JOIN gana g ON g.nif = s.nif AND g.anio = s.anio
FULL JOIN adjudica d ON d.nif = coalesce(s.nif, g.nif) AND d.anio = coalesce(s.anio, g.anio);

-- Cualquier importe por territorio y año dividido por la población (la del último año si falta).
CREATE VIEW poblacion_aplicable AS
SELECT a.anio, t.codigo AS territorio,
       (SELECT p.habitantes FROM poblacion p WHERE p.territorio = t.codigo AND p.anio <= a.anio ORDER BY p.anio DESC LIMIT 1) AS habitantes,
       NOT EXISTS (SELECT 1 FROM poblacion p WHERE p.territorio = t.codigo AND p.anio = a.anio) AS poblacion_de_otro_anio
FROM territorio t CROSS JOIN (SELECT generate_series(2000, extract(year FROM now())::int)::smallint AS anio) a;
