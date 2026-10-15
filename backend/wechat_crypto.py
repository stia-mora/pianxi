"""WeChat Channels ISAAC64 header decoding, ported from nobiyou/wx_channel.

Copyright (c) 2025 nobiyou. MIT; see third_party/wx_channel-LICENSE.
Only uses the decode key returned by the user's authenticated page session.
"""

MASK = (1 << 64) - 1
PREFIX_BYTES = 131072


def _mix(v):
    a, b, c, d, e, f, g, h = v
    a = (a - e) & MASK
    f ^= h >> 9
    h = (h + a) & MASK
    b = (b - f) & MASK
    g ^= (a << 9) & MASK
    a = (a + b) & MASK
    c = (c - g) & MASK
    h ^= b >> 23
    b = (b + c) & MASK
    d = (d - h) & MASK
    a ^= (c << 15) & MASK
    c = (c + d) & MASK
    e = (e - a) & MASK
    b ^= d >> 14
    d = (d + e) & MASK
    f = (f - b) & MASK
    c ^= (e << 20) & MASK
    e = (e + f) & MASK
    g = (g - c) & MASK
    d ^= f >> 17
    f = (f + g) & MASK
    h = (h - d) & MASK
    e ^= (g << 14) & MASK
    g = (g + h) & MASK
    return [a, b, c, d, e, f, g, h]


def keystream(key, length=PREFIX_BYTES):
    # Never accept JSON numbers here: JS loses precision above 2**53.
    if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or len(key) > 20:
        raise ValueError("视频号解码 Key 必须为十进制字符串")
    seed = int(key)
    if seed > MASK or not 0 <= length <= PREFIX_BYTES:
        raise ValueError("视频号解码参数无效")
    results = [seed] + [0] * 255
    memory = [0] * 256
    v = [0x9E3779B97F4A7C13] * 8
    for _ in range(4):
        v = _mix(v)
    for source in (results, memory):
        for offset in range(0, 256, 8):
            v = _mix([(v[k] + source[offset + k]) & MASK for k in range(8)])
            memory[offset:offset + 8] = v
    aa = bb = cc = 0
    output = bytearray()
    while len(output) < length:
        cc = (cc + 1) & MASK
        bb = (bb + cc) & MASK
        for j in range(256):
            x = memory[j]
            if j % 4 == 0:
                aa = ~(aa ^ (aa << 21)) & MASK
            elif j % 4 == 1:
                aa ^= aa >> 5
            elif j % 4 == 2:
                aa = (aa ^ (aa << 12)) & MASK
            else:
                aa ^= aa >> 33
            aa = (aa + memory[(j + 128) % 256]) & MASK
            y = (memory[(x >> 3) % 256] + aa + bb) & MASK
            memory[j] = y
            bb = (memory[(y >> 11) % 256] + x) & MASK
            results[j] = bb
        for value in reversed(results):
            output.extend(value.to_bytes(8, "big"))
    return bytes(output[:length])


def decode_file(path, key):
    with path.open("r+b") as stream:
        original = stream.read(PREFIX_BYTES)
        decoded = original
        if key:
            mask = keystream(key, len(original))
            decoded = bytes(a ^ b for a, b in zip(original, mask))
        # Do not publish encrypted data or HTML error pages as a video.
        if len(decoded) < 12 or decoded[4:8] not in (b"ftyp", b"styp", b"moov", b"mdat", b"free"):
            raise ValueError("视频号文件校验失败，请重新获取媒体地址和正确的解码 Key")
        if key:
            stream.seek(0)
            stream.write(decoded)
