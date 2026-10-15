import json
import zipfile

import pytest

from backend import config, store
from scripts import deployment_bundle as bundle


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA", tmp_path / "data/media")
    monkeypatch.setattr(config, "DB", tmp_path / "data/platform.sqlite3")
    monkeypatch.setattr(config, "COOKIE_DIR", tmp_path / "cookies")
    config.COOKIE_DIR.mkdir()
    store.init()
    store.save_settings({
        "provider": "api", "base_url": "https://vision.example/v1",
        "model": "vision", "api_key": "test-vision-key",
        "asr_provider": "auto", "asr_base_url": "https://speech.example/v1",
        "asr_model": "speech", "asr_api_key": "test-speech-key",
        "local_model": "F:/private/model", "unrelated_secret": "not-exported",
    })
    (config.COOKIE_DIR / "douyin_cookies.txt").write_text(
        "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\ttest-cookie\n",
        encoding="utf-8",
    )
    return tmp_path


def test_bundle_round_trip_only_settings_and_cookies(deployment, monkeypatch):
    archive = deployment / "private.zip"
    bundle.export_bundle(archive)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {"settings.json", "cookies/douyin_cookies.txt", "manifest.json", "PRIVATE-README.txt"}
        settings = json.loads(z.read("settings.json"))
        assert settings["provider"] == "api" and settings["asr_provider"] == "cloud"
        assert "local_model" not in settings and "unrelated_secret" not in settings
    monkeypatch.setattr(config, "DB", deployment / "new.sqlite3")
    monkeypatch.setattr(config, "COOKIE_DIR", deployment / "server-cookies")
    bundle.import_bundle(archive)
    assert store.setting("api_key") == "test-vision-key"
    assert store.setting("asr_provider") == "cloud"
    assert "test-cookie" in (config.COOKIE_DIR / "douyin_cookies.txt").read_text()
    with store.connect() as con:
        assert con.execute("select count(*) from users").fetchone()[0] == 0
        assert con.execute("select count(*) from sessions").fetchone()[0] == 0
    with pytest.raises(ValueError, match="Existing"):
        bundle.import_bundle(archive)
    bundle.import_bundle(archive, overwrite=True)


def test_bundle_rejects_path_traversal(deployment):
    archive = deployment / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Unexpected"):
        bundle.import_bundle(archive)
    assert not (deployment.parent / "escape.txt").exists()


def test_bundle_checksums_reject_modified_secret(deployment):
    original, modified = deployment / "private.zip", deployment / "modified.zip"
    bundle.export_bundle(original)
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(modified, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, b"{}" if name == "settings.json" else src.read(name))
    with pytest.raises(ValueError, match="checksum"):
        bundle.import_bundle(modified)
