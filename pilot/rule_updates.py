from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .rules import init_delivery_package, init_package, load_delivery_instruction, load_rules


MANIFEST_SCHEMA = 1
MAX_MANIFEST_BYTES = 256 * 1024
MAX_RULE_BYTES = 16 * 1024 * 1024
USER_AGENT = "TYMM-Soru-Kontrol-Rules-Updater/1"

CONSOLE_ASCII = str.maketrans({
    "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
    "â": "a", "Â": "A", "î": "i", "Î": "I",
})


class RuleUpdateError(RuntimeError):
    """Raised when a requested V7 update is invalid or cannot be applied."""


def console_ascii(value: object) -> str:
    """Keep CMD/Windows PowerShell output independent from the active code page."""
    return str(value).translate(CONSOLE_ASCII)


@dataclass(frozen=True)
class UpdateResult:
    status: str
    version: str | None
    message: str
    updated: bool = False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_allowed_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    # Plain HTTP is intentionally limited to local development/test servers.
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _download(url: str, timeout: int, max_bytes: int) -> bytes:
    if not _is_allowed_url(url):
        raise RuleUpdateError("Güncelleme adresi HTTPS olmalı (yerel testte yalnız localhost HTTP kullanılabilir).")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/octet-stream"})
    try:
        with urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise RuleUpdateError(f"Güncelleme dosyası izin verilen boyutu aşıyor: {url}")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuleUpdateError(f"Güncelleme dosyası izin verilen boyutu aşıyor: {url}")
                chunks.append(chunk)
            return b"".join(chunks)
    except RuleUpdateError:
        raise
    except Exception as exc:  # urllib exception types vary by Windows/Python version.
        raise RuleUpdateError(f"Güncelleme indirilemedi: {url} ({exc})") from exc


def _decode_rules_text(raw: bytes) -> str:
    """Decode a public V7 Markdown source without ever writing it to disk."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuleUpdateError("V7 dosyası geçerli UTF-8 metin değil.") from exc
    if not text.strip():
        raise RuleUpdateError("İndirilen V7 dosyası boş.")
    return text


def _hex_digest(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise RuleUpdateError(f"Manifest alanı geçersiz: {field}")
    return text


def _validate_manifest(raw: bytes, manifest_url: str) -> dict[str, object]:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise RuleUpdateError("Manifest izin verilen boyutu aşıyor.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuleUpdateError("Manifest geçerli UTF-8 JSON değil.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA:
        raise RuleUpdateError("Manifest şeması desteklenmiyor.")
    version = str(data.get("version") or "").strip()
    if not version or len(version) > 100:
        raise RuleUpdateError("Manifest sürümü geçersiz.")
    rules_url = urljoin(manifest_url, str(data.get("rules_url") or ""))
    delivery_url = urljoin(manifest_url, str(data.get("delivery_url") or ""))
    if not _is_allowed_url(rules_url) or not _is_allowed_url(delivery_url):
        raise RuleUpdateError("Manifest kural dosyaları güvenli bir HTTPS adresi göstermiyor.")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "version": version,
        "rules_url": rules_url,
        "delivery_url": delivery_url,
        "rules_sha256": _hex_digest(data.get("rules_sha256"), "rules_sha256"),
        "delivery_sha256": _hex_digest(data.get("delivery_sha256"), "delivery_sha256"),
        "mandatory": bool(data.get("mandatory", False)),
    }


def _local_version(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _local_matches(rules_path: Path, delivery_path: Path, version_path: Path, manifest: dict[str, object]) -> bool:
    local = _local_version(version_path)
    return (
        local.get("schema_version") == MANIFEST_SCHEMA
        and local.get("version") == manifest["version"]
        and local.get("rules_sha256") == manifest["rules_sha256"]
        and local.get("delivery_sha256") == manifest["delivery_sha256"]
        and rules_path.is_file()
        and delivery_path.is_file()
        and sha256_file(rules_path) == manifest["rules_sha256"]
        and sha256_file(delivery_path) == manifest["delivery_sha256"]
    )


def _version_payload(manifest: dict[str, object], manifest_url: str) -> dict[str, object]:
    return {
        "schema_version": MANIFEST_SCHEMA,
        "version": manifest["version"],
        "rules_sha256": manifest["rules_sha256"],
        "delivery_sha256": manifest["delivery_sha256"],
        "source": manifest_url,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def check_and_apply(root: Path, manifest_url: str, *, required: bool = False, timeout: int = 20) -> UpdateResult:
    """Check one manifest and atomically apply its validated V7 packages.

    A failed optional update never prevents the local application from starting.
    """
    manifest_url = str(manifest_url or "").strip()
    if not manifest_url:
        return UpdateResult("disabled", None, "V7 merkezi güncellemesi yapılandırılmamış; yerel paket kullanılıyor.")
    if not _is_allowed_url(manifest_url):
        error = RuleUpdateError("Manifest adresi HTTPS olmalı (yerel testte yalnız localhost HTTP kullanılabilir).")
        if required:
            raise error
        return UpdateResult("fallback", None, f"V7 güncellemesi atlandı: {error}")

    effective_required = required
    try:
        manifest = _validate_manifest(_download(manifest_url, timeout, MAX_MANIFEST_BYTES), manifest_url)
        effective_required = required or bool(manifest.get("mandatory", False))
        rules_path = root / "rules" / "rules.bin"
        delivery_path = root / "rules" / "delivery.bin"
        version_path = root / "rules" / "version.json"
        if _local_matches(rules_path, delivery_path, version_path, manifest):
            return UpdateResult("current", str(manifest["version"]), f"V7 zaten güncel: {manifest['version']}")

        rules_data = _download(str(manifest["rules_url"]), timeout, MAX_RULE_BYTES)
        delivery_data = _download(str(manifest["delivery_url"]), timeout, MAX_RULE_BYTES)
        if sha256_bytes(rules_data) != manifest["rules_sha256"]:
            raise RuleUpdateError("İndirilen rules.bin SHA-256 doğrulaması başarısız.")
        if sha256_bytes(delivery_data) != manifest["delivery_sha256"]:
            raise RuleUpdateError("İndirilen delivery.bin SHA-256 doğrulaması başarısız.")

        work_dir = root / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rules-update-", dir=work_dir) as temporary_root:
            temporary = Path(temporary_root)
            temporary_rules = temporary / "rules.bin"
            temporary_delivery = temporary / "delivery.bin"
            temporary_rules.write_bytes(rules_data)
            temporary_delivery.write_bytes(delivery_data)
            # Validate the package envelope before touching the live files.
            if not load_rules(temporary_rules).strip():
                raise RuleUpdateError("Yeni V7 paketi boş.")
            if not load_delivery_instruction(temporary_delivery):
                raise RuleUpdateError("Yeni teslim istemi paketi boş veya geçersiz.")

            old_rules = rules_path.read_bytes() if rules_path.is_file() else None
            old_delivery = delivery_path.read_bytes() if delivery_path.is_file() else None
            old_version = version_path.read_bytes() if version_path.is_file() else None
            try:
                rules_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_rules.replace(rules_path)
                temporary_delivery.replace(delivery_path)
                _write_json_atomic(version_path, _version_payload(manifest, manifest_url))
            except Exception:
                # Restore the previous local package if a replacement or metadata write failed.
                if old_rules is None:
                    rules_path.unlink(missing_ok=True)
                else:
                    rules_path.write_bytes(old_rules)
                if old_delivery is None:
                    delivery_path.unlink(missing_ok=True)
                else:
                    delivery_path.write_bytes(old_delivery)
                if old_version is None:
                    version_path.unlink(missing_ok=True)
                else:
                    version_path.write_bytes(old_version)
                raise
        return UpdateResult("updated", str(manifest["version"]), f"V7 güncellendi: {manifest['version']}", updated=True)
    except Exception as exc:
        if effective_required:
            if isinstance(exc, RuleUpdateError):
                raise
            raise RuleUpdateError(str(exc)) from exc
        return UpdateResult("fallback", None, f"V7 güncellemesi uygulanamadı; yerel paketle devam ediliyor: {exc}")


def _rules_url_version_payload(rules_url: str, rules_hash: str, delivery_path: Path) -> dict[str, object]:
    return {
        "schema_version": MANIFEST_SCHEMA,
        "source_type": "rules_url",
        "source": rules_url,
        "version": rules_hash,
        "rules_sha256": rules_hash,
        "delivery_sha256": sha256_file(delivery_path) if delivery_path.is_file() else "",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _apply_rules_text(root: Path, rules_url: str, rules_text: str, rules_hash: str) -> UpdateResult:
    """Encrypt and atomically install one public Markdown V7 source."""
    rules_path = root / "rules" / "rules.bin"
    delivery_path = root / "rules" / "delivery.bin"
    version_path = root / "rules" / "version.json"
    work_dir = root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rules-url-update-", dir=work_dir) as temporary_root:
        temporary = Path(temporary_root)
        temporary_rules = temporary / "rules.bin"
        init_package(temporary_rules, rules_text)
        if load_rules(temporary_rules) != rules_text:
            raise RuleUpdateError("İndirilen V7 paketi doğrulanamadı.")

        old_rules = rules_path.read_bytes() if rules_path.is_file() else None
        old_version = version_path.read_bytes() if version_path.is_file() else None
        try:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_rules.replace(rules_path)
            _write_json_atomic(version_path, _rules_url_version_payload(rules_url, rules_hash, delivery_path))
        except Exception:
            if old_rules is None:
                rules_path.unlink(missing_ok=True)
            else:
                rules_path.write_bytes(old_rules)
            if old_version is None:
                version_path.unlink(missing_ok=True)
            else:
                version_path.write_bytes(old_version)
            raise
    return UpdateResult("updated", rules_hash, f"V7 güncellendi: {rules_hash[:16]}", updated=True)


def check_and_apply_rules_url(root: Path, rules_url: str, *, required: bool = False, timeout: int = 20) -> UpdateResult:
    """Fetch a public UTF-8 V7 Markdown file and install it as rules.bin.

    This mode is intentionally simpler than the signed/hashed release manifest
    mode. It is useful when the institution accepts a public GitHub source. A
    failed optional fetch falls back to the last local package.
    """
    rules_url = str(rules_url or "").strip()
    if not rules_url:
        return UpdateResult("disabled", None, "V7 merkezi güncellemesi yapılandırılmamış; yerel paket kullanılıyor.")
    if not _is_allowed_url(rules_url):
        error = RuleUpdateError("V7 adresi HTTPS olmalı (yerel testte yalnız localhost HTTP kullanılabilir).")
        if required:
            raise error
        return UpdateResult("fallback", None, f"V7 güncellemesi atlandı: {error}")

    try:
        rules_text = _decode_rules_text(_download(rules_url, timeout, MAX_RULE_BYTES))
        rules_hash = sha256_bytes(rules_text.encode("utf-8"))
        rules_path = root / "rules" / "rules.bin"
        try:
            local_text = load_rules(rules_path)
        except Exception:
            local_text = None
        if local_text is not None and sha256_bytes(local_text.encode("utf-8")) == rules_hash:
            return UpdateResult("current", rules_hash, f"V7 zaten güncel: {rules_hash[:16]}")
        return _apply_rules_text(root, rules_url, rules_text, rules_hash)
    except Exception as exc:
        if required:
            if isinstance(exc, RuleUpdateError):
                raise
            raise RuleUpdateError(str(exc)) from exc
        return UpdateResult("fallback", None, f"V7 güncellemesi uygulanamadı; yerel paketle devam ediliyor: {exc}")


def pack_rules(rules_file: Path, delivery_file: Path, output_directory: Path, version: str) -> Path:
    """Build a release directory without ever copying plaintext V7 into it."""
    version = str(version or "").strip()
    if not version or len(version) > 100:
        raise RuleUpdateError("Sürüm boş olamaz veya 100 karakteri aşamaz.")
    rules_text = rules_file.read_text(encoding="utf-8-sig")
    delivery_text = delivery_file.read_text(encoding="utf-8-sig")
    if not rules_text.strip() or not delivery_text.strip():
        raise RuleUpdateError("V7 veya teslim istemi boş olamaz.")
    output_directory.mkdir(parents=True, exist_ok=True)
    rules_path = output_directory / "rules.bin"
    delivery_path = output_directory / "delivery.bin"
    init_package(rules_path, rules_text)
    init_delivery_package(delivery_path, delivery_text)
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "version": version,
        "rules_url": "rules.bin",
        "delivery_url": "delivery.bin",
        "rules_sha256": sha256_file(rules_path),
        "delivery_sha256": sha256_file(delivery_path),
        "mandatory": False,
    }
    manifest_path = output_directory / "manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TYMM Soru Kontrol V7 kural paketi güncelleyicisi")
    subparsers = parser.add_subparsers(dest="command", required=True)
    update = subparsers.add_parser("update", help="Manifesti kontrol et ve paketi uygula")
    update.add_argument("--root", type=Path, required=True)
    source = update.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest-url")
    source.add_argument("--rules-url")
    update.add_argument("--timeout", type=int, default=20)
    update.add_argument("--required", action="store_true")
    pack = subparsers.add_parser("pack", help="V7 ve teslim isteminden yayın paketi üret")
    pack.add_argument("--rules-file", type=Path, required=True)
    pack.add_argument("--delivery-file", type=Path, required=True)
    pack.add_argument("--output-directory", type=Path, required=True)
    pack.add_argument("--version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "update":
            if args.rules_url:
                result = check_and_apply_rules_url(args.root, args.rules_url, required=args.required, timeout=max(1, args.timeout))
            else:
                result = check_and_apply(args.root, args.manifest_url, required=args.required, timeout=max(1, args.timeout))
            print(console_ascii(result.message))
            return 0
        manifest_path = pack_rules(args.rules_file, args.delivery_file, args.output_directory, args.version)
        print(console_ascii(f"V7 yayın paketi hazır: {manifest_path}"))
        return 0
    except Exception as exc:
        print(console_ascii(f"V7 işlem hatası: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
