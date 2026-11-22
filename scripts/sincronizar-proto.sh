#!/bin/sh
# Copia el código Python generado de los esquemas Protobuf (repo plataforma, proto/gen/python).
# Los .proto viven en la plataforma; aquí solo va su código generado, sin tocar.
set -eu
ORIGEN="${1:-../plataforma/proto/gen/python}"
DESTINO="$(dirname "$0")/../dinero_publico"
[ -d "$ORIGEN/dinero_publico" ] || { echo "No encuentro $ORIGEN/dinero_publico" >&2; exit 1; }
rm -rf "$DESTINO"
cp -R "$ORIGEN/dinero_publico" "$DESTINO"
printf '# Código generado por buf desde dinero-publico/plataforma/proto. No editar: scripts/sincronizar-proto.sh\n' > "$DESTINO/LEEME"
find "$DESTINO" -name '*.py' | sort
