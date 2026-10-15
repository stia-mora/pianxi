import socket

import pytest

from backend import collector


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(collector.config, "ALLOW_FAKE_IP", False)
    monkeypatch.setattr(
        collector.socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))
        ],
    )


def test_douyin_zjcdn_media_url_is_allowed(public_dns):
    # This host was returned by Douyin for a video that failed collection.
    url = "https://v5-dy-ov-experiment.zjcdn.com/video/test.mp4"
    assert collector.public_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://zjcdn.com.evil.example/video.mp4",
        "https://evilzjcdn.com/video.mp4",
        "https://evil.example/video.mp4",
        "https://user:password@v5-dy-o.zjcdn.com/video.mp4",
        "file:///video.mp4",
    ],
)
def test_media_allowlist_still_rejects_other_hosts(url, public_dns):
    with pytest.raises(ValueError):
        collector.public_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "::1", "198.18.0.105"])
def test_zjcdn_must_resolve_to_public_address(address, monkeypatch, public_dns):
    monkeypatch.setattr(
        collector.socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )
    with pytest.raises(ValueError, match="内网"):
        collector.public_url("https://v5-dy-o.zjcdn.com/video.mp4")


@pytest.mark.parametrize("address", ["198.18.0.105", "198.19.255.254"])
def test_configured_fake_ip_proxy_can_download_platform_media(address, monkeypatch):
    monkeypatch.setattr(collector.config, "ALLOW_FAKE_IP", True)
    monkeypatch.setattr(
        collector.socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )
    url = "https://v5-dy-ov-experiment.zjcdn.com/video.mp4"
    assert collector.public_url(url) == url
    with pytest.raises(ValueError):
        collector.public_url("https://evil.example/video.mp4")


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "169.254.169.254", "::1"])
def test_fake_ip_mode_does_not_allow_private_addresses(address, monkeypatch):
    monkeypatch.setattr(collector.config, "ALLOW_FAKE_IP", True)
    monkeypatch.setattr(
        collector.socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )
    with pytest.raises(ValueError):
        collector.public_url("https://v5-dy-o.zjcdn.com/video.mp4")


def test_douyin_page_retries_transient_failure(monkeypatch, tmp_path):
    shared = "https://v.douyin.com/test/"
    resolved = "https://www.douyin.com/video/12345"
    calls = []
    monkeypatch.setattr(collector, "resolve_short_url", lambda url: resolved)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    def collect_page(url, folder):
        calls.append(url)
        if len(calls) == 1:
            raise ValueError("抖音未返回公开视频详情")
        return {"video_id": "12345"}

    monkeypatch.setattr(collector, "collect_douyin", collect_page)
    result = collector.collect(shared, tmp_path)
    assert calls == [resolved, resolved]
    assert result["video_id"] == "12345"
    assert result["source_url"] == shared
    assert result["resolved_url"] == resolved
    assert result["warnings"] == []


def test_short_url_fallback_uses_resolved_video_url(monkeypatch, tmp_path):
    shared = "https://v.douyin.com/test/"
    resolved = "https://www.douyin.com/video/12345"
    page_calls, download_calls = [], []
    monkeypatch.setattr(collector, "resolve_short_url", lambda url: resolved)
    monkeypatch.setattr(collector, "cookie_path", lambda url: None)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    def unavailable(url, folder):
        page_calls.append(url)
        raise ValueError("抖音未返回公开视频详情")

    class Downloader:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            download_calls.append((url, download))
            return {"id": "12345", "title": "测试视频"}

    monkeypatch.setattr(collector, "collect_douyin", unavailable)
    monkeypatch.setattr(collector.yt_dlp, "YoutubeDL", Downloader)
    result = collector.collect(shared, tmp_path)
    assert page_calls == [resolved, resolved]
    assert download_calls == [(resolved, True)]
    assert result["source_url"] == shared
    assert result["resolved_url"] == resolved
    assert result["warnings"]


def test_douyin_verification_error_is_preserved(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(collector, "resolve_short_url", lambda url: url)

    def needs_verification(url, folder):
        calls.append(url)
        raise collector.PlatformVerificationRequired("抖音要求浏览器验证")

    monkeypatch.setattr(collector, "collect_douyin", needs_verification)
    with pytest.raises(collector.PlatformVerificationRequired, match="浏览器验证"):
        collector.collect("https://www.douyin.com/video/12345", tmp_path)
    assert len(calls) == 1
