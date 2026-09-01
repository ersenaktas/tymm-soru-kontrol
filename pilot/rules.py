from __future__ import annotations
import base64, hashlib, json, os
from pathlib import Path

MAGIC = b"NLM-PILOT-RULES-1\0"
DELIVERY_MAGIC = b"NLM-PILOT-DELIVERY-1\0"

def _key() -> bytes:
    # This is deliberately obfuscation, documented as such in README.
    material = b"notebooklm-soru-kontrol-pilot-v1"
    return hashlib.sha256(material).digest()

def _crypt(data: bytes) -> bytes:
    key = _key()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def init_package(path: Path, text: str) -> None:
    payload = MAGIC + json.dumps({"rules": text}, ensure_ascii=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base64.b64encode(_crypt(payload)).decode("ascii"), encoding="ascii")

def load_rules(path: Path) -> str:
    raw = base64.b64decode(path.read_text(encoding="ascii"))
    decoded = _crypt(raw)
    if not decoded.startswith(MAGIC):
        raise ValueError("Kural paketi doğrulanamadı")
    return json.loads(decoded[len(MAGIC):])["rules"]


def init_delivery_package(path: Path, text: str) -> None:
    """Write the short runtime delivery instruction as an obfuscated package."""
    payload = DELIVERY_MAGIC + json.dumps({"instruction": text}, ensure_ascii=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base64.b64encode(_crypt(payload)).decode("ascii"), encoding="ascii")


def load_delivery_instruction(path: Path) -> str | None:
    """Return the runtime-only delivery instruction, if the package exists."""
    if not path.is_file():
        return None
    raw = base64.b64decode(path.read_text(encoding="ascii"))
    decoded = _crypt(raw)
    if not decoded.startswith(DELIVERY_MAGIC):
        raise ValueError("Teslim istemi paketi doğrulanamadı")
    return json.loads(decoded[len(DELIVERY_MAGIC):])["instruction"]

if __name__ == "__main__":
    raise SystemExit("Varsayılan yönerge dağıtım kaynak kodunda tutulmaz; init_package(path, text) kullanın.")
