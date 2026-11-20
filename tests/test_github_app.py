"""El JWT de la GitHub App se firma bien con openssl (sin tocar la red)."""
import base64
import json
import shutil
import subprocess

import pytest

from dinero_datos import github_app

pytestmark = pytest.mark.skipif(not shutil.which("openssl"), reason="hace falta openssl")


def _decod(parte: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))


def test_jwt_firmado_y_verificable(tmp_path):
    clave, publica = tmp_path / "app.pem", tmp_path / "app.pub"
    subprocess.run(["openssl", "genrsa", "-out", clave, "2048"], check=True, capture_output=True)
    subprocess.run(["openssl", "rsa", "-in", clave, "-pubout", "-out", publica], check=True, capture_output=True)

    token = github_app.jwt("123456", str(clave), ahora=1_800_000_000)
    cab, cuerpo, firma = token.split(".")
    assert _decod(cab) == {"alg": "RS256", "typ": "JWT"}
    assert _decod(cuerpo) == {"iat": 1_799_999_940, "exp": 1_800_000_540, "iss": "123456"}

    (tmp_path / "firma").write_bytes(base64.urlsafe_b64decode(firma + "=" * (-len(firma) % 4)))
    r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", publica, "-signature", tmp_path / "firma"],
                       input=f"{cab}.{cuerpo}".encode(), capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr
