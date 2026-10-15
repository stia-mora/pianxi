"""Export/import only platform settings and cookies; never users or sessions."""

import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import collector, config, store


SETTING_KEYS = {
    "team_name", "provider", "base_url", "model", "api_key",
    "asr_provider", "asr_base_url", "asr_model", "asr_api_key",
    "wechat_bridge_url", "wechat_bridge_token",
}
COOKIE_PLATFORMS = ("抖音", "YouTube", "哔哩哔哩")


def export_bundle(target):
    if target.exists():
        raise ValueError("Output already exists; choose a new filename")
    settings = {k: v for k, v in store.settings().items() if k in SETTING_KEYS}
    # Cloud-only servers have neither the Windows conda paths nor local weights.
    if not all(settings.get(k) for k in ("base_url", "model", "api_key", "asr_api_key")):
        raise ValueError("Cloud deployment requires saved vision and ASR API settings")
    settings.update(provider="api", asr_provider="cloud")
    files = {
        "settings.json": json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8")
    }
    for platform in COOKIE_PLATFORMS:
        path = collector.cookie_file(platform)
        if path.is_file():
            jar = http.cookiejar.MozillaCookieJar(str(path))
            jar.load(ignore_discard=True, ignore_expires=True)
            files["cookies/" + path.name] = path.read_bytes()
    manifest = {
        "format": "pianxi-deployment-secrets-v1",
        "mode": "cloud",
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "excluded": ["users", "sessions", "jobs", "videos", "model_weights", "host_credentials"],
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    files["PRIVATE-README.txt"] = (
        "PRIVATE: Contains live API keys and platform login cookies. Do not commit or publish.\n"
        "Import: python scripts/deployment_bundle.py import /path/to/this.zip\n"
        "Requires installed platform dependencies. See docs/SERVER_DEPLOYMENT.md.\n"
        "Creates no users, copies no sessions, videos, reports or local model weights.\n"
        "Cloud ASR is selected for this server; cookie validity is not guaranteed.\n"
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items():
                    archive.writestr(name, data)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print(f"Exported private bundle: {target.resolve()}")
    print(f"Contains {len(settings)} settings and {len(files) - 3} cookie files; no values printed.")


def import_bundle(source, overwrite=False):
    allowed_cookies = {"cookies/" + collector.cookie_file(p).name for p in COOKIE_PLATFORMS}
    allowed = allowed_cookies | {"settings.json", "manifest.json", "PRIVATE-README.txt"}
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or set(names) - allowed:
            raise ValueError("Unexpected or duplicate archive entries")
        if not {"settings.json", "manifest.json"}.issubset(names):
            raise ValueError("Missing deployment settings or manifest")
        if sum(item.file_size for item in infos) > 2 * 1024 * 1024:
            raise ValueError("Bundle exceeds 2 MB limit")
        content = {name: archive.read(name) for name in names}
    manifest = json.loads(content["manifest.json"])
    if manifest.get("format") != "pianxi-deployment-secrets-v1":
        raise ValueError("Unsupported bundle format")
    expected = {name for name in names if name == "settings.json" or name in allowed_cookies}
    if set(manifest.get("sha256", {})) != expected:
        raise ValueError("Manifest entries do not match bundle")
    for name, digest in manifest["sha256"].items():
        if hashlib.sha256(content[name]).hexdigest() != digest:
            raise ValueError("Bundle checksum mismatch")
    settings = json.loads(content["settings.json"])
    if not isinstance(settings, dict) or set(settings) - SETTING_KEYS:
        raise ValueError("Unexpected settings fields")
    if not all(isinstance(value, str) for value in settings.values()):
        raise ValueError("Settings must be strings")
    if settings.get("provider") != "api" or settings.get("asr_provider") != "cloud":
        raise ValueError("Expected cloud deployment settings")
    # Use the application's URL/model validation without saving secrets yet.
    from backend.main import SettingsInput
    SettingsInput(**settings)
    from urllib.parse import urlparse
    for name in ("base_url", "asr_base_url"):
        parsed = urlparse(settings.get(name, ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Cloud API endpoints must be HTTPS root URLs")
    store.init()
    existing = store.settings()
    config.COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    cookie_names = sorted(set(names) & allowed_cookies)
    if not overwrite and (
        any(key in existing for key in settings)
        or any((config.COOKIE_DIR / Path(name).name).exists() for name in cookie_names)
    ):
        raise ValueError("Existing configuration preserved; use --overwrite intentionally")
    # The archive is never extracted to caller-controlled paths.
    for name in cookie_names:
        target = config.COOKIE_DIR / Path(name).name
        pending = target.with_suffix(".pending")
        try:
            with pending.open("wb") as stream:
                if os.name != "nt":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(content[name])
            jar = http.cookiejar.MozillaCookieJar(str(pending))
            jar.load(ignore_discard=True, ignore_expires=True)
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    store.save_settings(settings)
    print(f"Imported {len(settings)} settings and {len(cookie_names)} cookie files. Values hidden.")
    print("No users, sessions, jobs or media were imported.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("archive", type=Path)
    restore = sub.add_parser("import")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "export":
            export_bundle(args.archive)
        else:
            import_bundle(args.archive, args.overwrite)
    except (ValueError, OSError, zipfile.BadZipFile, http.cookiejar.LoadError):
        # Never echo file contents, endpoint credentials or API keys on failures.
        parser.exit(1, "Bundle operation failed. Check format, configured cloud keys, paths and existing settings.\n")


if __name__ == "__main__":
    main()
