"""Download media resolved by a user-operated wx_channel companion."""

from urllib.parse import urlparse, parse_qs
import json
import httpx
from . import config, store
from .wechat_crypto import decode_file


def is_share_url(url):
    try:
        p = urlparse(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or p.fragment:
            return False
        if p.hostname == "weixin.qq.com" and not p.query and p.path.startswith("/sph/"):
            token = p.path[5:].strip("/")
        elif p.hostname == "channels.weixin.qq.com" and p.path.rstrip("/") == "/finder-preview/pages/sph":
            token = parse_qs(p.query).get("id", [""])[0]
        else:
            return False
        return bool(token) and token.isascii() and all(c.isalnum() or c in "_-" for c in token)
    except ValueError:
        return False


def bridge_url(value):
    value = value.strip().rstrip("/")
    if not value:
        return ""
    try:
        p = urlparse(value)
        port = p.port
    except ValueError:
        raise ValueError("视频号采集器地址格式无效") from None
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment or p.path:
        raise ValueError("填写 wx_channel 服务根地址，例如 http://127.0.0.1:2025")
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
        raise ValueError("远程视频号采集器需使用 HTTPS，本机可使用 HTTP")
    return value


def _request(path, payload=None):
    base = bridge_url(store.setting("wechat_bridge_url"))
    if not base:
        raise ValueError("请管理员先在系统设置连接 wx_channel，并在微信中打开视频号页面")
    token = store.setting("wechat_bridge_token")
    headers = {"X-Local-Auth": token} if token else {}
    try:
        with httpx.Client(timeout=httpx.Timeout(100, connect=10), follow_redirects=False) as client:
            method = "POST" if payload is not None else "GET"
            response = client.request(method, base + path, json=payload, headers=headers)
        if response.status_code in (401, 403):
            raise ValueError("视频号采集器鉴权失败，请检查连接令牌")
        if response.status_code == 404:
            raise ValueError("视频号采集器缺少解析 API，请更新 wx_channel")
        if response.status_code != 200:
            raise ValueError("视频号采集器请求失败，请确认微信页面在线后重试")
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != 0 or not isinstance(body.get("data"), dict):
            raise ValueError("视频号采集器返回格式不兼容")
        return body["data"]
    except httpx.HTTPError:
        raise ValueError("无法连接视频号采集器，请检查地址、网络及 wx_channel 是否运行") from None
    except (TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("视频号采集器返回格式不兼容") from None


def test_connection():
    data = _request("/api/v1/status")
    ready = any(
        isinstance(item, dict) and item.get("key") == "wxchannels:sph" and item.get("available") is True
        for item in (data.get("statuses") or [])
    )
    if not ready:
        return {"ok": False, "message": "采集器已连接，尚无可用的微信分享页。请在微信打开视频号并保持页面在线"}
    return {"ok": True, "message": "视频号采集器及微信分享页已就绪"}


def collect(url, folder):
    from . import collector

    data = _request("/api/v1/search/share/resolve", {"urls": [url]})
    resolved = data.get("resolved")
    if not isinstance(resolved, list) or len(resolved) != 1 or not isinstance(resolved[0], dict):
        failures = data.get("failed") or []
        code = failures[0].get("errorCode") if isinstance(failures, list) and failures and isinstance(failures[0], dict) else None
        if code == "no_ready_client":
            raise ValueError("微信视频号页面未就绪，请打开已登录的视频号页面并保持在线")
        if code == "timeout":
            raise ValueError("微信视频号解析超时，请刷新微信页面后重试")
        raise ValueError("微信未返回可下载的视频，请在微信确认分享链接有效且视频可播放")
    item = resolved[0]
    if item.get("inputUrl") != url or not isinstance(item.get("id"), str) or not item["id"]:
        raise ValueError("视频号采集器返回了不匹配的视频详情")
    media_url = item.get("url")
    if not isinstance(media_url, str) or len(media_url) > 16000:
        raise ValueError("视频号媒体地址无效")
    key = item.get("key", "")
    if not isinstance(key, str):
        raise ValueError("视频号解码 Key 必须为字符串，请更新采集器")
    duration = collector.number(item.get("durationMs"))
    duration = duration / 1000 if duration is not None else None
    size = collector.number(item.get("size"))
    if duration and duration > config.MAX_VIDEO_SECONDS:
        raise ValueError("当前支持不超过 15 分钟的视频")
    if size and size > config.MAX_BYTES:
        raise ValueError("视频超过 500MB 限制")
    # Resolve/download credentials and decode keys never enter job/report JSON.
    encrypted = folder / "wechat-download.bin"
    target = folder / "video.mp4"
    headers = {"Referer": "https://channels.weixin.qq.com/", "Origin": "https://channels.weixin.qq.com"}
    warnings = []
    try:
        collector.download_file(media_url, encrypted, headers=headers, platforms="wechat")
        decode_file(encrypted, key)
        encrypted.replace(target)
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"视频号媒体下载返回 HTTP {exc.response.status_code}，地址可能已过期，请重新采集") from None
    except httpx.HTTPError:
        raise ValueError("视频号媒体下载连接失败，请检查服务器网络后重试") from None
    finally:
        encrypted.unlink(missing_ok=True)
    cover = item.get("coverUrl")
    if isinstance(cover, str) and cover:
        try:
            collector.download_file(cover, folder / "cover.jpg", 15 * 1024 * 1024, headers=headers, platforms="wechat")
        except Exception:
            warnings.append("原封面下载失败，将使用视频首帧")
    result = collector.clean_info({
        "id": item["id"], "title": str(item.get("title") or "微信视频号视频")[:4000],
        "uploader": str(item.get("authorName") or "微信未提供作者")[:200], "duration": duration,
    }, url)
    result["comments_note"] = "视频号连接目前仅提供视频和基础信息，尚未采集评论与互动指标"
    result["warnings"] = warnings
    result["collection_method"] = "wx_channel_share_api"
    return result
