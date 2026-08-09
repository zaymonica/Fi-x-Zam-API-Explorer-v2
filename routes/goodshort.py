"""
routes/goodshort.py — GoodShort Short Drama API
Ported from Cloudflare Worker (JS) to Python/Flask.
Uses RSA PKCS1v15 SHA-256 signing.
"""
import base64
import json
import time
from datetime import datetime

import requests as http_requests
from flask import Blueprint, request

from utils import json_response

goodshort_bp = Blueprint('goodshort', __name__)

# ─── Constants ────────────────────────────────────────────────────────
BASE_URL      = "https://api-akm.goodreels.com/hwycclientreels"
CERT_MD5      = "919326DD9A742D064502468E1BF11144"
PACKAGE_NAME  = "com.newreading.goodreels"
DEVICE_ID     = "df04c9f1-daac-439d-9a77-502c55391714"
ANDROID_ID    = "ffffffff8ef458768ef4587600000000"
TOKEN         = ("Bearer ZXlKMGVYQWlPaUpLVjFRaUxDSmhiR2NpT2lKSVV6STFOaUo5LmV5"
                 "SnlaV2RwYzNSbGNsUjVjR1VpT2lKUVJWSk5RVTVGVGxRaUxDSjFjMlZ5U1"
                 "dRaU9qSXdPRGcwTmpBNE9IMC5PaW5uOWxWbEc1cXVkWUoxRHZic0ExQ2wz"
                 "Z3hJY3U0TDZYUk5zZUVWUmlF")

FULL_KEY_B64 = (
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDLwHQE9g2+/DJmi"
    "VtNS6v0SmHKAEzGaClFMHMNszfi5GDkrA9SjT1Z87tScD2feSSuuKJIoSYL1o3mq"
    "gmX2pCN/5rPzOifJ6gQjGZjLuvuxmvSRk8jHqsPoqj/QH6qhF5n2Mpr5oirGD9IU"
    "g3RRtdy0RfRuXxHLCnYhKfXKP+TdcK/1Hi/vPONlCpJo7ph62KVeUD+qACYZUNjd"
    "iZxklZZASac24OjBdFZOd/ZtINM4wOaHFpwHmnoq89qM1MP09gJc7tPlPONFoWIAV"
    "pfwjtjRsCbFuGQdBf7FlEsxivef2nHFN8J9Q+aqE1wr+ouNbbUkEebYqbt2ROTPe7"
    "xCJnfAgMBAAECggEBAK3nFR8m45SerGXX1pWigKGA2vYOS3kMbi0frROEY67EPe7u7"
    "CUJZ9Pes4MpSW9TdnuqGtjishZoibTWbFmvsrF/+CJkQieVMVzueHUvFzA1KtHOML"
    "1I77fonVU/Nt1THUCFSD/QA9YEW/7eCe0VCc51qF7YcbpNd2nVz2tVEs5Hrb1Q0W"
    "SdxXaIIyFH4vNS9Xgx4ZY2ULzaJePCbEZcUwFLiJQtIWslGcCDALFyPMN6W9PKMF"
    "o96l0+KruleKfuiTCNzG94Vxe3ClAO64VIa65cSXu6DSUxiD1kedxDPRNEsZU9qfw"
    "Ni2gFJCa97KUMBcL2M4VV8guIh4QXQwGoTAECgYEA896OhcFRQXryCAHR1+pLx3+a"
    "qM7qKf9qJWGh+lw/FWBB7cYQ3p+e9BomoQS5OdQcLGy2cTc38zMVvESNEk+VS81V"
    "nCnVDTKC9vGPvuRItas5RKjNxAQEMJdudGlweEwQqkDlFRktuXwXIRfmzoA2iV+OU"
    "kJW5CDw81+hqMMsRpsCgYEA1eMJiw98fdeya1FJ9PE5x9lZyjyFIQ3ydsRtSetmeDI"
    "ETX2AlkHC0HqySbjsIyXsxmq8AajfHraShf6eZeOBsP+sfOPS6J+jN9reS7gpVbl7"
    "EYL3D6OVMBuwZYv9ILkWj6lpfrFBvK8v32eRXgJjJ9LBkAXROBpCQPMHvPwpTA0Cg"
    "YA989cPIbpLwTkFUbkGeg4AQ2l94vrX6nwDvRbSLGcWPhrhlcSpWbGe35napAGOMFV"
    "r7741asq67MpjxqJz+WW7GRHbl0D5llBw/ZL/8qyKAlKNH7kOR9rsoTu9NSAOX3yI"
    "U+4eewQDsAOMM6893JJ+OZlFSncag0fS/ANshRCVawKBgQCfrNUNCcyorgS29YK+5+"
    "948RyFTFUe7iia3d2xF5nyFXT83LrIceOcfFzpiLJRMxjmr/wXSRj49tfATOu3qPbD"
    "SrxcqEBmBfd11WGrKZtCMixcUGddN4RC3Aj+ZlncuhDLw2/Mc0xeLnMQ12LAygt4SX"
    "DTsmQU/BWGI2kdfyrdaQKBgDdzsoRSOh+tBtSRqEyc4BgtfK/FyU7VQy3fUlaaBJEU"
    "Y6FxE8Icn34VVEeN6YOEmAewEcyMcQQX2ZwQ2wITv4NssL8uDJ0y4K/TlL+2bomXr"
    "i/nobvyaDsMfrX6grlQXe4YzVpzGUFbcW+QValHpacnAjGejZkLM7KD2XaK1Ppf"
)

DEFAULT_HEADERS = {
    "User-Agent":           "okhttp/4.10.0",
    "Accept-Encoding":      "gzip",
    "scwidth":              "540",
    "appversion":           "2822082",
    "language":             "in",
    "mcc":                  "",
    "ramsize":              "8352821248",
    "deviceid":             DEVICE_ID,
    "model":                "SM-S938U",
    "brand":                "Samsung",
    "variablechannelcode":  "GRGGKOTAPPEN00298",
    "apn":                  "2",
    "androidid":            ANDROID_ID,
    "devicetype":           "tablet",
    "pname":                PACKAGE_NAME,
    "timezone":             "+0700",
    "bigdatasession":       "4607ce7e-bcd2-46ba-aee0-9ac76b48ff73",
    "afid":                 "1771944850322-2098166459262346731",
    "gender":               "UNKNOWN",
    "variablebid":          "31001270068",
    "platform":             "ANDROID",
    "authorization":        TOKEN,
    "scdesc":               "540P",
    "currentlanguage":      "in",
    "originalchid":         "GRA00001",
    "scheight":             "960",
    "channelcode":          "GRGGKOTAPPEN00298",
    "hardware":             "Samsung",
    "os":                   "12",
    "romsize":              "134208294912",
    "userid":               "208846088",
    "adjustadid":           "",
    "p":                    "193",
    "lqb":                  "1",
    "currencycode":         "-1",
    "lqa":                  "1771944858638",
}

# ─── RSA Signing ──────────────────────────────────────────────────────
_private_key = None


def _get_private_key():
    global _private_key
    if _private_key:
        return _private_key
    from cryptography.hazmat.primitives.serialization import load_der_private_key
    der = base64.b64decode(FULL_KEY_B64)
    _private_key = load_der_private_key(der, password=None)
    return _private_key


def _sign(request_body: str, timestamp: str) -> str:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    data = f"timestamp={timestamp}{request_body}{DEVICE_ID}{ANDROID_ID}{TOKEN}{CERT_MD5}{PACKAGE_NAME}"
    key = _get_private_key()
    sig = key.sign(data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("utf-8")


# ─── Core Request ─────────────────────────────────────────────────────
def _req(endpoint: str, body):
    ts       = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
    sign     = _sign(body_str, ts)

    now = datetime.now()
    local_time = now.strftime("%Y-%m-%d %H:%M:%S.000 +0700")

    headers = {**DEFAULT_HEADERS, "sign": sign, "localtime": local_time}
    if body_str:
        headers["content-type"] = "application/json; charset=UTF-8"
    else:
        headers["content-length"] = "0"

    resp = http_requests.post(
        f"{BASE_URL}/{endpoint}?timestamp={ts}",
        headers=headers,
        data=body_str.encode("utf-8") if body_str else None,
        timeout=30,
    )
    try:
        data = resp.json()
    except Exception:
        return {"error": "Failed to parse upstream response", "status": resp.status_code}

    # Strip internal fields
    if isinstance(data, dict):
        data.pop("ip", None)
        data.pop("path", None)

    return data


# ── Normalization → Fi x Zam app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. GoodShort
# nests books in several shapes: recommentList[].book, records[].items[],
# searchResult.records[]. These helpers flatten any of them.
def _gs_norm_book(b):
    labels = b.get("labelInfos") or b.get("typeTwoNames") or b.get("tags") or []
    flat = []
    for t in labels:
        if isinstance(t, dict):
            n = t.get("labelName") or t.get("name")
            if n:
                flat.append(n)
        elif t:
            flat.append(str(t))
    return {
        "drama_id": str(b.get("bookId") or ""),
        "drama_name": b.get("bookName") or "",
        "description": b.get("introduction") or "",
        "episode_count": str(b.get("chapterCount") or b.get("totalChapterNum") or 0),
        "watch_value": str(b.get("viewCount") or b.get("followCount") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": b.get("cover") or b.get("bookDetailCover") or b.get("image") or "",
        "tags": flat,
    }


def _gs_collect(node, seen=None):
    """Recursively pull GoodShort books (bookId + bookName) from any shape.
    `recommentList[].book` wraps the book one level down — handled by recursion."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        if node.get("bookId") and node.get("bookName"):
            key = str(node.get("bookId"))
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_gs_collect(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_gs_collect(v, seen))
    return out


def _gs_list_resp(raw_body):
    raw = raw_body.get("data") if isinstance(raw_body, dict) else raw_body
    # some goodshort endpoints already put the payload at top level
    books = [_gs_norm_book(b) for b in _gs_collect(raw if raw is not None else raw_body)]
    return json_response({
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "data": [{"books": books}],
    })


# ─── Routes ───────────────────────────────────────────────────────────
@goodshort_bp.route('/goodshort/home', methods=['GET'])
def goodshort_home():
    return _gs_list_resp(_req("book/recommend", {
        "recentShelfBooks": [], "firstOpen": False, "recommentedBookIds": []
    }))


@goodshort_bp.route('/goodshort/populer', methods=['GET'])
def goodshort_populer():
    page = max(1, int(request.args.get('page', 1)))
    return _gs_list_resp(_req("home/index", {
        "pageNo": page, "pageSize": 12,
        "channelType": 1, "vipBookEnable": False, "channelId": "-1",
    }))


@goodshort_bp.route('/goodshort/new', methods=['GET'])
def goodshort_new():
    page       = max(1, int(request.args.get('page', 1)))
    channel_id = request.args.get('channelId', '563')
    return _gs_list_resp(_req("home/index", {
        "pageNo": page, "pageSize": 12,
        "channelType": 0, "vipBookEnable": False, "channelId": channel_id,
    }))


@goodshort_bp.route('/goodshort/nav', methods=['GET'])
def goodshort_nav():
    return json_response(_req("home/nav/list", None))


@goodshort_bp.route('/goodshort/search', methods=['GET'])
def goodshort_search():
    page    = max(1, int(request.args.get('page', 1)))
    keyword = request.args.get('q', '') or request.args.get('query', '')
    if not keyword:
        return json_response({"error": "Provide ?q=keyword"}, 400)
    return _gs_list_resp(_req("book/search1", {
        "pageNo": str(page), "pageSize": "15", "keyword": keyword,
    }))


@goodshort_bp.route('/goodshort/detail', methods=['GET'])
def goodshort_detail():
    book_id = request.args.get('bookId', '')
    if not book_id:
        return json_response({"error": "Provide bookId"}, 400)
    return json_response(_req("book/quick/open", {"chapterId": -1, "bookId": book_id}))


@goodshort_bp.route('/goodshort/stream', methods=['GET'])
def goodshort_stream():
    """
    Return daftar episode + filePath yang siap diplay (tidak terenkripsi).
    Menggunakan chapter/load → signed URL dari v3-akm.goodreels.com (no AES key needed).
    """
    from urllib.parse import quote

    book_id = request.args.get('bookId', '')
    if not book_id:
        return json_response({"error": "Provide bookId"}, 400)

    # Step 1: Ambil list chapter dengan ID-nya via chapter/download
    dl_data = _req("chapter/download", {"bookId": book_id})
    download_list = (dl_data.get("data") or {}).get("downloadList", [])
    if not download_list:
        return json_response(dl_data)

    # Step 2: Kumpulkan semua chapterIds
    chapter_ids = [ep["id"] for ep in download_list if "id" in ep]

    # Step 3: chapter/load → return signed unencrypted URLs (max 50 at a time)
    all_chapters = {}
    batch_size = 50
    for i in range(0, len(chapter_ids), batch_size):
        batch = chapter_ids[i:i+batch_size]
        load_result = _req("chapter/load", {"bookId": book_id, "chapterIds": batch})
        for ch in (load_result.get("data") or {}).get("list", []):
            all_chapters[ch["id"]] = ch

    # Step 4: Merge & proxy semua filePaths
    host = request.host_url.rstrip('/')
    for episode in download_list:
        ch = all_chapters.get(episode.get("id"))
        if ch and ch.get("multiVideos"):
            # Pakai signed URL dari chapter/load (tanpa enkripsi) untuk free episodes
            for video in ch["multiVideos"]:
                url = video.get("filePath", "")
                if url:
                    video["filePath"] = f"{host}/goodshort/proxy/m3u8?url={quote(url, safe='')}"
            episode["multiVideos"] = ch["multiVideos"]
            episode["cdnList"] = ch.get("cdnList", [])
        else:
            # Fallback: proxy URL dari chapter/download (encrypted, perlu key)
            for video in episode.get("multiVideos", []):
                url = video.get("filePath", "")
                if url and not url.startswith(host):
                    video["filePath"] = (
                        f"{host}/goodshort/proxy/m3u8"
                        f"?url={quote(url, safe='')}"
                        f"&bookId={quote(book_id, safe='')}"
                    )

    dl_data["data"]["downloadList"] = download_list
    return json_response(dl_data)


# ─── Video Proxy ──────────────────────────────────────────────────────
# Dipakai untuk memutar video GoodShort yang pakai AES-128 encryption.
#
# Alur:
#   1. /goodshort/stream?bookId=X  → dapat downloadList + filePath (m3u8)
#   2. Pilih episode & kualitas, ambil filePath
#   3. /goodshort/proxy/m3u8?url=<filePath>&key=<base64_key>
#   4. Setiap .ts segment otomatis lewat /goodshort/proxy/ts?url=...

_PROXY_HEADERS = {
    "User-Agent": "okhttp/4.10.0",
    "Accept": "*/*",
}


@goodshort_bp.route('/goodshort/proxy/m3u8', methods=['GET'])
def goodshort_proxy_m3u8():
    """
    Proxy m3u8 playlist + inject AES key + rewrite .ts URLs.
    Query:
      url — filePath m3u8 dari response /stream
      key — AES-128 key base64 (opsional)
    """
    import re
    from urllib.parse import quote
    from flask import Response

    m3u8_url  = request.args.get('url', '')
    video_key = request.args.get('key', '')

    if not m3u8_url:
        return json_response({"error": "Provide ?url=<m3u8_url>"}, 400)

    try:
        resp = http_requests.get(m3u8_url, headers=_PROXY_HEADERS, timeout=15)
        if not resp.ok:
            return json_response({"error": f"CDN returned {resp.status_code}"}, 502)

        content  = resp.text
        base_url = m3u8_url.rsplit('/', 1)[0]
        host     = request.host_url.rstrip('/')

        # Inject AES key:
        #  - Jika key diberikan langsung (dari rawurl), embed sebagai data URI
        #  - Jika tidak, rewrite local:// → /goodshort/proxy/key?bookId=X
        book_id_param = request.args.get("bookId", "")
        if video_key:
            content = re.sub(
                r'URI="local://[^"]*"',
                f'URI="data:text/plain;base64,{video_key}"',
                content
            )
        else:
            # Parse prefix & epoch dari local:// URI, teruskan ke /proxy/key
            def _rewrite_key_uri(m):
                uri = m.group(1)
                em = re.search(r'epoch=(\d+)', uri)
                pm = re.search(r'prefix=([^"&]+)', uri)
                ep = em.group(1) if em else '1'
                pf = pm.group(1) if pm else ''
                kurl = f"{host}/goodshort/proxy/key"
                sep = '?'
                if book_id_param:
                    kurl += f"{sep}bookId={quote(book_id_param, safe='')}"; sep = '&'
                if pf:
                    kurl += f"{sep}prefix={quote(pf, safe='')}"; sep = '&'
                kurl += f"{sep}epoch={ep}"
                return f'URI="{kurl}"'
            content = re.sub(r'URI="(local://[^"]*)"', _rewrite_key_uri, content)

        # Rewrite .ts segment → lewat proxy kita
        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and stripped.endswith('.ts'):
                ts_full = stripped if stripped.startswith('http') else f"{base_url}/{stripped}"
                lines.append(f"{host}/goodshort/proxy/ts?url={quote(ts_full, safe='')}")
            else:
                lines.append(line)

        return Response(
            '\n'.join(lines),
            status=200,
            mimetype='application/vnd.apple.mpegurl',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache',
            }
        )
    except Exception as e:
        return json_response({"error": "Failed to fetch m3u8", "detail": str(e)}, 502)


@goodshort_bp.route('/goodshort/proxy/ts', methods=['GET'])
def goodshort_proxy_ts():
    """Proxy .ts video segment — stream langsung ke client."""
    from flask import Response, stream_with_context

    ts_url = request.args.get('url', '')
    if not ts_url:
        return Response('Missing url parameter', status=400)

    try:
        upstream = http_requests.get(
            ts_url, headers=_PROXY_HEADERS,
            stream=True, timeout=20
        )
        return Response(
            stream_with_context(upstream.iter_content(chunk_size=8192)),
            status=upstream.status_code,
            mimetype='video/mp2t',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=3600',
            }
        )
    except Exception as e:
        return Response(f'Proxy error: {e}', status=502)


# ─── Raw URL (dengan Key) ─────────────────────────────────────────────
# Membutuhkan token dari @nanomilkisbot
# Isi GOODSHORT_TOKEN di .env
# Endpoint ini return filePath yang sudah include ?key= → langsung bisa diplay

DRAMABOS_BASE = "https://goodshort.dramabos.my.id"


@goodshort_bp.route('/goodshort/rawurl/<book_id>', methods=['GET'])
def goodshort_rawurl(book_id):
    """
    Ambil data buku + video key dari goodshort.dramabos.my.id.
    Otomatis rewrite filePath → /goodshort/proxy/m3u8?url=...&key=...
    Query:
      lang    — bahasa (default: in)
      quality — kualitas video (default: 720p)
    """
    import os
    from urllib.parse import quote

    token   = os.getenv('GOODSHORT_TOKEN', '')
    lang    = request.args.get('lang', 'in')
    quality = request.args.get('quality', '720p')

    if not token:
        return json_response({
            "error": "GOODSHORT_TOKEN belum diset di .env",
            "info": "Dapatkan token dari @nanomilkisbot di Telegram"
        }, 503)

    try:
        url  = f"{DRAMABOS_BASE}/rawurl/{book_id}"
        resp = http_requests.get(url, params={
            "lang": lang, "q": quality, "code": token
        }, headers={"User-Agent": "Fi-x-Zam-API/1.0"}, timeout=20)

        data = resp.json()
    except Exception as e:
        return json_response({"error": "Failed to fetch rawurl", "detail": str(e)}, 502)

    inner = data.get("data") or {}
    video_key = inner.get("videoKey", "")
    host      = request.host_url.rstrip('/')

    # Rewrite m3u8 URL setiap episode → sertakan key supaya langsung bisa diplay
    episodes = inner.get("episodes", [])
    for ep in episodes:
        m3u8_url = ep.get("m3u8", "")
        if m3u8_url:
            proxy_url = f"{host}/goodshort/proxy/m3u8?url={quote(m3u8_url, safe='')}"
            if video_key:
                proxy_url += f"&key={quote(video_key, safe='')}"
            ep["m3u8"] = proxy_url

    return json_response(data)


# ─── Key Proxy ────────────────────────────────────────────────────────
# Coba ambil key:
#   1. GoodShort API langsung (pakai signed request kita sendiri)
#   2. goodshort.dramabos.my.id (jika GOODSHORT_TOKEN diset)
# Tidak perlu token jika GoodShort API punya endpoint key-nya.

import os as _os, json as _json, base64 as _b64

_KEY_FILE = _os.path.join(_os.path.dirname(__file__), '..', 'goodshort_keys.json')
# Known keys hardcoded sebagai fallback (prefix:epoch → AES-128 key base64)
# Key ini berlaku untuk semua buku GoodShort dengan prefix yang sama,
# termasuk episode berbayar — enkripsi tidak bergantung pada payment status.
_KNOWN_KEYS = {
    "u3KP5obqZp:1": "C4klinNVvXsNxuU6i3KLOQ==",
}

_key_cache = {k: _b64.b64decode(v) for k, v in _KNOWN_KEYS.items()}


def _load_key_cache():
    """Load key dari file (overrides/extends _KNOWN_KEYS)."""
    try:
        with open(_KEY_FILE) as f:
            for k, v in _json.load(f).items():
                _key_cache[k] = _b64.b64decode(v)
    except Exception:
        pass


def _save_key_cache():
    try:
        with open(_KEY_FILE, 'w') as f:
            _json.dump({k: _b64.b64encode(v).decode() for k, v in _key_cache.items()}, f)
    except Exception:
        pass


_load_key_cache()   # load on import


@goodshort_bp.route('/goodshort/proxy/key', methods=['GET'])
def goodshort_proxy_key():
    import os, base64
    from flask import Response

    book_id = request.args.get('bookId', '')
    prefix  = request.args.get('prefix', '')
    epoch   = request.args.get('epoch', '1')
    cache_k = f"{prefix}:{epoch}"

    # ── Cache hit (memory atau file) ──
    if cache_k in _key_cache:
        return Response(_key_cache[cache_k], status=200,
                        mimetype='application/octet-stream',
                        headers={'Access-Control-Allow-Origin': '*'})

    # ── Coba 1: GoodShort API (no extra token needed) ──
    if book_id or prefix:
        endpoints_to_try = [
            ("book/offline/key",    {"bookId": book_id, "prefix": prefix, "epoch": int(epoch)}),
            ("chapter/offline/key", {"bookId": book_id, "prefix": prefix}),
            ("book/key",            {"bookId": book_id}),
        ]
        for ep, body in endpoints_to_try:
            try:
                result = _req(ep, body)
                inner  = result.get("data") or {}
                k64    = inner.get("key") or inner.get("videoKey") or inner.get("aesKey")
                if k64:
                    key_bytes = base64.b64decode(k64)
                    if len(key_bytes) == 16:
                        _key_cache[cache_k] = key_bytes
                        _save_key_cache()   # persist ke disk
                        print(f"[GoodShort] Key found via API endpoint: {ep}")
                        return Response(key_bytes, status=200,
                                        mimetype='application/octet-stream',
                                        headers={'Access-Control-Allow-Origin': '*'})
            except Exception:
                pass

    # ── Coba 2: goodshort.dramabos.my.id (butuh GOODSHORT_TOKEN) ──
    token = os.getenv('GOODSHORT_TOKEN', '')
    if token and book_id:
        try:
            resp = http_requests.get(
                f"{DRAMABOS_BASE}/rawurl/{book_id}",
                params={"lang": "in", "q": "720p", "code": token},
                headers={"User-Agent": "Fi-x-Zam-API/1.0"},
                timeout=20
            )
            k64 = (resp.json().get("data") or {}).get("videoKey", "")
            if k64:
                key_bytes = base64.b64decode(k64)
                _key_cache[cache_k] = key_bytes
                _save_key_cache()   # persist ke disk
                print(f"[GoodShort] Key found via dramabos.my.id")
                return Response(key_bytes, status=200,
                                mimetype='application/octet-stream',
                                headers={'Access-Control-Allow-Origin': '*'})
        except Exception as e:
            print(f"[GoodShort] dramabos fallback failed: {e}")

    return Response(
        'AES key not found — set GOODSHORT_TOKEN in .env (from @nanomilkisbot)',
        status=503
    )
