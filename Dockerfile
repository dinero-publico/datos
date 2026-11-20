# Imagen de la herramienta de datos (issue #4): la misma CLI de siempre, en un contenedor.
#
#   docker build -t dinero-datos .
#   docker run --rm -v "$PWD/raw:/datos/raw" -v "$PWD/publicado:/datos/publicado" \
#     -v "$PWD/curated:/datos/curated" dinero-datos descargar --only pge
#
# Las carpetas de trabajo van en /datos y se montan como volúmenes (en k3s, PVC).
FROM python:3.12-slim AS imagen

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DINERO_RAW=/datos/raw \
    DINERO_PUBLICADO=/datos/publicado \
    DINERO_CURATED=/datos/curated \
    PYTHONPATH=/app \
    PYTHONSAFEPATH=1

# git y ssh para la ingesta en cronos (contenedor/ingesta.sh hace push de publicado/).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-plataforma.txt ./
RUN pip install -r requirements.txt -r requirements-plataforma.txt

COPY dinero_datos/ dinero_datos/
COPY tests/ tests/
COPY --chmod=755 contenedor/ingesta.sh /app/ingesta.sh

# Usuario sin privilegios; uid fijo para que los permisos de los volúmenes sean previsibles.
RUN useradd --uid 10001 --create-home dinero \
    && mkdir -p /datos/raw /datos/publicado /datos/curated \
    && chown -R dinero /datos
USER 10001

ARG VERSION=desarrollo
ENV DINERO_VERSION=$VERSION
LABEL org.opencontainers.image.source="https://github.com/dinero-publico/datos" \
      org.opencontainers.image.description="Herramienta de datos de Dinero Público" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["python", "-m", "dinero_datos"]
CMD ["--help"]

# Tests dentro de la propia imagen: docker buildx build --target pruebas .
FROM imagen AS pruebas
RUN python -m pytest -q -p no:cacheprovider /app/tests

# La imagen que se publica (último stage, el que se construye por defecto).
FROM imagen
