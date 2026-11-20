"""Token de instalación de una GitHub App, para que la ingesta de cronos haga push.

Una GitHub App se autentica con un JWT firmado (RS256) con su clave privada, y con él pide
a GitHub un token de instalación que dura una hora y solo sirve para los repositorios donde
está instalada. La firma la hace el binario openssl, así no hacen falta librerías nuevas.

    python -m dinero_datos.github_app      (lee GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID
                                            y GITHUB_APP_PRIVATE_KEY_FILE; imprime el token)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

API = "https://api.github.com"


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def jwt(app_id: str, clave_pem: str, ahora: int | None = None) -> str:
    """JWT de la App: válido 9 minutos (GitHub admite hasta 10), con 60 s de margen de reloj."""
    ahora = int(time.time()) if ahora is None else ahora
    cabecera = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    cuerpo = _b64url(json.dumps({"iat": ahora - 60, "exp": ahora + 540, "iss": str(app_id)},
                                separators=(",", ":")).encode())
    firmado = f"{cabecera}.{cuerpo}".encode()
    firma = subprocess.run(["openssl", "dgst", "-sha256", "-sign", clave_pem], input=firmado,
                           capture_output=True, check=True).stdout
    return f"{cabecera}.{cuerpo}.{_b64url(firma)}"


def token_instalacion(app_id: str, instalacion: str, clave_pem: str) -> str:
    import requests
    r = requests.post(f"{API}/app/installations/{instalacion}/access_tokens",
                      headers={"Authorization": f"Bearer {jwt(app_id, clave_pem)}",
                               "Accept": "application/vnd.github+json"}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


if __name__ == "__main__":
    try:
        print(token_instalacion(os.environ["GITHUB_APP_ID"], os.environ["GITHUB_APP_INSTALLATION_ID"],
                                os.environ["GITHUB_APP_PRIVATE_KEY_FILE"]))
    except Exception as e:  # sin traza: podría incluir cabeceras
        print(f"No se pudo obtener el token de la GitHub App: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
