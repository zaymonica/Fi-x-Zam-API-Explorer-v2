"""Downloader modul — ubah stream URL jadi bytes video playable (streaming).

Mendukung:
- MP4 tunggal (Melolo)        -> yield chunk langsung.
- HLS nested (GoodShort/CashDrama/ReelShort):
    * follow master -> media playlist (rekursif).
    * EXT-X-KEY AES-128 (SimpleAES) -> ambil kunci (opsional tempel drm_token sbg `token=`),
      decrypt tiap segmen AES-128-CBC, yield plaintext.
    * Segmen polos -> yield langsung.
Semua fetch async (httpx). Auth header opsional utk m3u8/segmen proxy.
"""
import os
import re
import shutil
import asyncio
import random
import subprocess
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# Anti-bot: rotasi User-Agent (mobile + desktop, beragam OS/browser)
UA_POOL = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
UA = UA_POOL[0]


def random_ua() -> str:
    """Anti-bot: pilih UA acak dari pool."""
    return random.choice(UA_POOL)


def _resolve(url: str, ref: str) -> str:
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        p = urlparse(ref)
        return f"{p.scheme}://{p.netloc}{url}"
    return ref.rsplit("/", 1)[0] + "/" + url


async def _get_bytes(client: httpx.AsyncClient, url: str, headers: dict) -> bytes:
    r = await client.get(url, headers=headers)
    r.raise_for_status()
    return r.content


async def _get_text(client: httpx.AsyncClient, url: str, headers: dict) -> str:
    r = await client.get(url, headers=headers)
    r.raise_for_status()
    return r.text


async def iter_hls(client, m3u8_url, headers=None, drm_token=None, max_segments=None, ua=None):
    """Async generator: yield bytes video dari playlist HLS (nested + AES aware)."""
    headers = headers or {"User-Agent": ua or random_ua(), "Accept": "*/*"}
    url = m3u8_url
    media_text = None

    # follow nested playlist sampai ketemu media playlist (ada EXTINF)
    for _ in range(6):
        txt = await _get_text(client, url, headers)
        if "#EXTINF" in txt:
            media_text = txt
            break
        lines = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
        if not lines:
            return
        url = _resolve(lines[0], url)

    if media_text is None:
        return

    # AES-128 key?
    key = None
    iv = b"\x00" * 16
    km = re.search(r'EXT-X-KEY:METHOD=AES-128,URI="([^"]+)"(?:,IV=0x([0-9a-fA-F]+))?', media_text)
    if km:
        key_url = _resolve(km.group(1), url)
        if drm_token:
            sep = "&" if "?" in key_url else "?"
            key_url = f"{key_url}{sep}token={drm_token}"
        raw = await _get_bytes(client, key_url, headers)
        key = raw[:16]
        if km.group(2):
            iv = bytes.fromhex(km.group(2))

    segs = [l.strip() for l in media_text.splitlines()
            if l.strip() and not l.startswith("#")]
    if max_segments:
        segs = segs[:max_segments]

    count = 0
    for s in segs:
        su = _resolve(s, url)
        ct = await _get_bytes(client, su, headers)
        if key is not None:
            dec = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
            ct = dec.update(ct) + dec.finalize()
        count += 1
        yield ct


async def iter_mp4(client, mp4_url, headers=None, ua=None):
    """Async generator: yield chunk MP4 tunggal."""
    headers = headers or {"User-Agent": ua or random_ua(), "Accept": "*/*"}
    async with client.stream("GET", mp4_url, headers=headers) as r:
        r.raise_for_status()
        async for chunk in r.aiter_bytes(65536):
            yield chunk


# ---------------- remux .ts -> .mp4 (ffmpeg) ----------------
FFMPEG = shutil.which("ffmpeg") or "/home/ubuntu/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg"


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg")) or os.path.exists(FFMPEG)


def probe_video_codec(path: str) -> str:
    """Return codec_name video track (contoh: hevc/h264) via ffprobe."""
    ffprobe = os.path.join(os.path.dirname(FFMPEG), "ffprobe")
    if not os.path.exists(ffprobe):
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return (out.stdout or "").strip()
    except Exception:
        return ""


async def transcode_to_h264(inp: str, out_path: str) -> str:
    """Transcode video HEVC/codec-lain -> H.264 (+ AAC) agar playable di semua browser."""
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-y", "-loglevel", "error", "-i", inp,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-f", "mp4", out_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError(f"transcode failed: {err.decode()[:200]}")
    return out_path


async def remux_ts_to_mp4(seg_iter, out_path: str) -> str:
    """Kumpulkan bytes .ts dari generator -> file -> remux ke .mp4 (copy codec).

    Mengembalikan path .mp4. Butuh ffmpeg di PATH / lokasi bundel.
    """
    import tempfile
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp_ts = out_path + ".tmp.ts"
    total = 0
    with open(tmp_ts, "wb") as f:
        async for chunk in seg_iter:
            f.write(chunk)
            total += len(chunk)
    if total == 0:
        raise ValueError("no data to remux")
    if not ffmpeg_available():
        # fallback: kembalikan .ts apa adanya (rename)
        os.replace(tmp_ts, out_path)
        return out_path
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-y", "-loglevel", "error", "-i", tmp_ts,
        "-c", "copy", "-movflags", "+faststart", "-f", "mp4", out_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        # gagal remux -> fallback .ts
        os.replace(tmp_ts, out_path)
        return out_path
    os.remove(tmp_ts)
    return out_path
