import hashlib
import json
import shutil
import socket
import subprocess

import httpx
import pytest

from backend import collector, config, store, wechat
from backend.wechat_crypto import keystream, decode_file, PREFIX_BYTES


SHARE = "https://weixin.qq.com/sph/Abc_123-xyz"


@pytest.mark.parametrize("url", [SHARE, "https://channels.weixin.qq.com/finder-preview/pages/sph?id=Abc_123-xyz"])
def test_wechat_share_links(url):
    assert collector.normalize_url(f"分享这个视频 [{url}]({url})") == url
    assert collector.platform(url) == "微信视频号"


@pytest.mark.parametrize("url", [
    "https://weixin.qq.com.evil.test/sph/Abc", "https://weixin.qq.com/sph/A/extra",
    "https://mp.weixin.qq.com/s/article", "https://weixin.qq.com/sph/A?redirect=http://127.0.0.1",
    "http://weixin.qq.com/sph/A", "https://channels.weixin.qq.com/finder-preview/pages/sph?id=bad.value",
])
def test_invalid_wechat_links(url):
    with pytest.raises(ValueError):
        collector.normalize_url(url)


# Full 128KB hashes computed with an independent uint64 C implementation of
# wx_channel/pkg/util/isaac64.go at 1d494115df37320c6bf524baf1977dc669797d5c.
@pytest.mark.parametrize("key,digest", [
    ("0", "e1662af3b7e59867c919ad19055fc8cecea2b154d37e1459b2f96d1da14cef1f"),
    ("1", "39d98f5b25cc52f0996f7ef9e1022156cb029901be6a11ebbdd7469c6ffd5839"),
    ("9007199254740993", "520917d54d3d8d27ec1fcd34479f0942376bbd4979039bf9315b22c9987149f1"),
    ("18446744073709551615", "5afbffd76305e81467f97c6370fa07916e9b197611bf5c357a854eb92a6354a1"),
])
def test_isaac64_reference_vectors(key, digest):
    assert hashlib.sha256(keystream(key)).hexdigest() == digest


@pytest.mark.parametrize("key", [123, "-1", "1.5", "18446744073709551616", "１", "9" * 100])
def test_invalid_decode_key(key):
    with pytest.raises(ValueError):
        keystream(key)


def test_decode_preserves_unencrypted_tail(tmp_path):
    plain = b"\x00\x00\x00\x18ftypisom" + b"x" * (PREFIX_BYTES + 400)
    prefix = bytes(a ^ b for a, b in zip(plain, keystream("1")))
    path = tmp_path / "video.bin"
    path.write_bytes(prefix + plain[PREFIX_BYTES:])
    decode_file(path, "1")
    assert path.read_bytes() == plain
    with pytest.raises(ValueError):
        decode_file(path, "1")
    assert path.read_bytes() == plain  # Invalid key must not modify the file.


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA", tmp_path / "data/media")
    monkeypatch.setattr(config, "DB", tmp_path / "data/platform.sqlite3")
    monkeypatch.setattr(config, "ALLOW_FAKE_IP", False)
    store.init()
    store.save_settings({"wechat_bridge_url": "https://bridge.example", "wechat_bridge_token": "private-bridge-token"})
    monkeypatch.setattr(collector.socket, "getaddrinfo", lambda host, port: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))
    ])
    return tmp_path


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_download_decodes_media_and_hides_keys(bridge, monkeypatch):
    plain = b"\0\0\0\x18ftypisom" + b"media" * 40000
    key = "9007199254740993"
    encrypted = bytes(a ^ b for a, b in zip(plain, keystream(key))) + plain[PREFIX_BYTES:]
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "bridge.example":
            assert request.url.path == "/api/v1/search/share/resolve"
            assert json.loads(request.content) == {"urls": [SHARE]}
            assert request.headers["X-Local-Auth"] == "private-bridge-token"
            return httpx.Response(200, json={"code": 0, "data": {"resolved": [{
                "inputUrl": SHARE, "id": "feed-1", "title": "视频号样本", "authorName": "作者",
                "url": "https://finder.video.qq.com/video?token=private-media-token", "key": key,
                "durationMs": 25000,
            }]}})
        assert request.url.host == "finder.video.qq.com"
        assert "x-local-auth" not in request.headers
        assert "authorization" not in request.headers
        assert request.headers["referer"] == "https://channels.weixin.qq.com/"
        return httpx.Response(200, content=encrypted)

    mock_http(monkeypatch, handler)
    result = collector.collect(SHARE, bridge)
    assert (bridge / "video.mp4").read_bytes() == plain
    assert not (bridge / "wechat-download.bin").exists()
    assert len(seen) == 2 and result["duration"] == 25
    assert result["platform"] == "微信视频号"
    assert all(v is None for v in result["metrics"].values())
    assert all(secret not in json.dumps(result) for secret in (key, "private-media-token", "private-bridge-token"))


@pytest.mark.parametrize("code,message", [("no_ready_client", "页面未就绪"), ("timeout", "解析超时"), ("other", "未返回")])
def test_bridge_resolution_errors(bridge, monkeypatch, code, message):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"code": 0, "data": {"failed": [{"errorCode": code, "error": "private-secret"}]}}))
    with pytest.raises(ValueError, match=message) as error:
        wechat.collect(SHARE, bridge)
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize("status,message", [(401, "鉴权"), (404, "缺少解析 API"), (500, "请求失败")])
def test_bridge_http_errors(bridge, monkeypatch, status, message):
    mock_http(monkeypatch, lambda r: httpx.Response(status, text="private-secret"))
    with pytest.raises(ValueError, match=message):
        wechat.collect(SHARE, bridge)


def test_connection_checks_wechat_page_not_only_http(bridge, monkeypatch):
    mock_http(monkeypatch, lambda r: httpx.Response(200, json={"code": 0, "data": {"connected": True, "statuses": [{"key": "wxchannels:sph", "available": False}]}}))
    assert wechat.test_connection()["ok"] is False


def test_wechat_media_redirect_rejects_other_hosts(bridge, monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/leak"})
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError):
        collector.download_file("https://finder.video.qq.com/video", bridge / "video.mp4", platforms="wechat")
    assert len(seen) == 1


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "169.254.169.254"])
def test_wechat_media_blocks_private_ips(bridge, monkeypatch, address):
    monkeypatch.setattr(collector.socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))])
    with pytest.raises(ValueError):
        collector.public_url("https://finder.video.qq.com/video", platforms="wechat")


def test_wechat_real_mp4_processing(bridge, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg integration requires system binary")
    source = bridge / "fixture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-c:v", "libx264", "-y", str(source)], check=True)
    plain = source.read_bytes()
    encrypted = bytes(a ^ b for a, b in zip(plain, keystream("1", len(plain))))
    def handler(request):
        if request.url.host == "bridge.example":
            return httpx.Response(200, json={"code": 0, "data": {"resolved": [{"inputUrl": SHARE, "id": "real-mp4", "url": "https://finder.video.qq.com/test", "key": "1"}]}})
        return httpx.Response(200, content=encrypted)
    mock_http(monkeypatch, handler)
    wechat.collect(SHARE, bridge)
    from backend.media import prepare_media
    result = prepare_media(bridge)
    assert result["width"] == 64 and result["duration"] == 1
    assert (bridge / result["cover_file"]).is_file()


@pytest.mark.parametrize("field,value,message", [
    ("durationMs", 901000, "15 分钟"),
    ("size", config.MAX_BYTES + 1, "500MB"),
    ("inputUrl", "https://weixin.qq.com/sph/other", "不匹配"),
    ("key", 9007199254740993, "必须为字符串"),
])
def test_invalid_media_is_rejected_before_download(bridge, monkeypatch, field, value, message):
    item = {"inputUrl": SHARE, "id": "feed-1", "url": "https://finder.video.qq.com/video", "key": "1"}
    item[field] = value
    def handler(request):
        assert request.url.host == "bridge.example"
        return httpx.Response(200, json={"code": 0, "data": {"resolved": [item]}})
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match=message):
        wechat.collect(SHARE, bridge)
    assert not (bridge / "video.mp4").exists()


def test_bad_decoding_keeps_previous_video_and_cleans_download(bridge, monkeypatch):
    (bridge / "video.mp4").write_bytes(b"last valid video")
    def handler(request):
        if request.url.host == "bridge.example":
            return httpx.Response(200, json={"code": 0, "data": {"resolved": [{"inputUrl": SHARE, "id": "feed-1", "url": "https://finder.video.qq.com/video", "key": "1"}]}})
        return httpx.Response(200, content=b"<html>expired media token</html>")
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match="校验失败"):
        wechat.collect(SHARE, bridge)
    assert (bridge / "video.mp4").read_bytes() == b"last valid video"
    assert not (bridge / "wechat-download.bin").exists()
    assert not (bridge / "wechat-download.bin.part").exists()
