#!/bin/sh
# Ingesta en cronos: descarga unas fuentes, analiza, publica y hace push de publicado/.
#
#   ingesta.sh entregas            (una o varias fuentes; «todas» para el proceso completo)
#
# Clona el repo de datos en /trabajo (es público, sin credenciales), así publicado/ siempre
# parte de lo último de main. Para el push pide un token de la GitHub App de la organización
# justo antes (dura una hora y la descarga de contratos puede tardar más).
# Los originales se guardan en $DINERO_RAW (PVC). Si el push choca con otro commit (el
# workflow diario de GitHub), descarta el suyo, rehace los ficheros desde raw/ sin red y
# reintenta. Al final copia publicado/ a /datos/publicado y avisa al cargador si hay URL.
set -eu

REPO="${DINERO_REPO:-https://github.com/dinero-publico/datos.git}"
TRABAJO="${TRABAJO:-/trabajo}/datos"
export GIT_AUTHOR_NAME="cronos" GIT_AUTHOR_EMAIL="cronos@dinero-publico.invalid"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

ONLY=""
for f in "$@"; do [ "$f" = "todas" ] || ONLY="$ONLY --only $f"; done

push() {  # con el token de la App en una cabecera, para que no quede en URLs ni en logs
    token=$(python -m dinero_datos.github_app) || { echo "Sin token de la GitHub App." >&2; exit 1; }
    auth=$(printf "x-access-token:%s" "$token" | base64 -w0)
    git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth" push --quiet origin HEAD:main
}

generar() {  # $1: descargar | transformar
    python -m dinero_datos "$1" $ONLY
    python -m dinero_datos analizar
    python -m dinero_datos publicar
}

rm -rf "$TRABAJO"
git clone --quiet --depth 1 "$REPO" "$TRABAJO"
export DINERO_PUBLICADO="$TRABAJO/publicado"
cd "$TRABAJO"

generar descargar
for intento in 1 2 3; do
    git add publicado
    if git diff --cached --quiet; then
        echo "Sin datos nuevos."
        break
    fi
    git commit --quiet -m "Datos actualizados $(date -u +%Y-%m-%d) desde cronos: $*"
    if push; then
        echo "Publicado (intento $intento)."
        break
    fi
    echo "El push chocó con otro commit; se rehace sobre main desde raw/ (intento $intento)."
    git fetch --quiet --depth 1 origin main
    git reset --quiet --hard FETCH_HEAD
    generar transformar
    [ "$intento" -lt 3 ] || { echo "No se pudo publicar tras 3 intentos." >&2; exit 1; }
done

if [ -d /datos/publicado ]; then
    rm -rf /datos/publicado/.nuevo && cp -r publicado /datos/publicado/.nuevo
    find /datos/publicado -mindepth 1 -maxdepth 1 ! -name .nuevo -exec rm -rf {} +
    mv /datos/publicado/.nuevo/* /datos/publicado/ && rmdir /datos/publicado/.nuevo
fi
if [ -n "${DINERO_CARGADOR:-}" ]; then
    python -m dinero_datos avisar || echo "Aviso al cargador fallido; lo recogerá en su revisión periódica." >&2
fi
