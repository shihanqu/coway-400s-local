"""Per-installation keys and API token; never install a system certificate."""

from pathlib import Path
import os
import secrets
import ssl
import subprocess
import warnings


def token(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = data_dir / "api-token"
    if not path.exists():
        try:
            with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as out:
                out.write(secrets.token_urlsafe(32) + "\n")
        except FileExistsError:
            pass
    value = path.read_text().strip()
    if len(value) < 32:
        raise ValueError("The stored API token is invalid.")
    return value


def tls_context(data_dir: Path) -> ssl.SSLContext:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    certificate, key = data_dir / "server.crt", data_dir / "server.key"
    if certificate.exists() != key.exists():
        raise ValueError("Incomplete certificate/key pair in the data directory; preserve it and use a fresh directory.")
    if not certificate.exists():
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha1", "-nodes",
                "-days", "3650", "-subj", "/CN=Coway_iTrust",
                "-keyout", str(key), "-out", str(certificate),
            ], check=True, capture_output=True)
        except FileNotFoundError as error:
            raise ValueError("OpenSSL is required for this older Wi-Fi module. Use Docker or install OpenSSL.") from error
        except subprocess.CalledProcessError as error:
            raise ValueError("OpenSSL could not create the legacy-compatible local certificate.") from error
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1
    context.set_ciphers("AES256-SHA:AES128-SHA:@SECLEVEL=0")
    context.load_cert_chain(certificate, key)
    return context
