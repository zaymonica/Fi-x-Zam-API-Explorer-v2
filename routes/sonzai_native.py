"""sonzai_native.py — Provider native Fi-x-Zam (mandiri, gak butuh proses Sonzai).

Cara kerja:
  Import langsung CLASS provider dari Sonzai Aggregator (app/providers/*.py),
  lalu bungkus panggilan async-nya pake asyncio.run() (Flask = sync).

  Hasil: Fi-x-Zam punya logika provider Sonzai NATIVE di dalam dirinya.
  Gak tergantung proses Sonzai (:8585) hidup. Cuma butuh dep `httpx`.

Endpoint (gaya Fi-x-Zam):
  /sonzai/<provider>/home
  /sonzai/<provider>/search?q=
  /sonzai/<provider>/detail?id=
  /sonzai/<provider>/stream?id=&ep=
  /sonzai/<provider>/download?id=&ep=&format=
"""
import os
import sys
import asyncio
import functools

from flask import Blueprint, request

from utils import json_response

# ── path Sonzai (biar bisa import app.providers.*) ──────────────────
SONZAI_ROOT = os.getenv("SONZAI_ROOT", "/home/ubuntu/aggregator")
if SONZAI_ROOT not in sys.path:
    sys.path.insert(0, SONZAI_ROOT)
os.chdir(SONZAI_ROOT)  # provider baca env/data relatif
_token_file = "/home/ubuntu/sonzai_embed_token2.txt"
if os.path.exists(_token_file):
    os.environ.setdefault("MELOLO_TOKEN", open(_token_file).read().strip())

# ── import class provider Sonzai ────────────────────────────────────
from app.providers.reelshort import ReelShortProvider
from app.providers.melolo import MeloloProvider
from app.providers.goodshort import GoodShortProvider
from app.providers.cashdrama import CashDramaProvider
from app.providers.dramabox import DramaboxProvider
from app.providers.shortmax import ShortMaxProvider
from app.providers.rapidtv import RapidtvProvider
from app.providers.dramanova import DramaNovaProvider

# registry: nama -> instance provider
PROVIDERS = {
    "reelshort":  ReelShortProvider(),
    "melolo":     MeloloProvider(),
    "goodshort":  GoodShortProvider(),
    "cashdrama":  CashDramaProvider(),
    "dramabox":   DramaboxProvider(),
    "shortmax":   ShortMaxProvider(),
    "rapidtv":    RapidtvProvider(),
    "dramanova":  DramaNovaProvider(),
}

# default lang per provider (ReelShort pakai 'in', lainnya 'id')
DEFAULT_LANG = {"reelshort": "in", "melolo": "id", "goodshort": "id",
                "cashdrama": "id", "dramabox": "id", "shortmax": "id",
                "rapidtv": "id", "dramanova": "in"}

sonzai_native_bp = Blueprint("sonzai_native", __name__)

# ── event loop persisten (dijalankan di background thread) ──────────
# Provider nahan httpx.AsyncClient yang ke-bind ke 1 event loop.
# Kalau pakai asyncio.run() per-request, loop ditutup -> "Event loop is closed".
# Solusi: 1 loop abadi di thread terpisah; tiap request dijadwalkan via
# run_coroutine_threadsafe (thread-safe, loop tidak pernah ditutup).
import threading
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()


def _run(coro):
    """Jadwalkan coroutine ke event loop persisten, tunggu hasilnya (sync)."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=300)


def _slim_items(res):
    """Normalisasi respons provider -> list item {id,title,cover}.
    Provider bisa balikin items di top-level ATAU di bawah 'data'."""
    if not isinstance(res, dict):
        return [], {}
    data = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
    # cek top-level dulu, lalu di bawah data
    items = (res.get("items") or res.get("books") or res.get("list")
             or data.get("items") or data.get("books") or data.get("list") or [])
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        out.append({
            "id": x.get("id") or x.get("book_id") or x.get("drama_id") or x.get("vid"),
            "title": x.get("title") or x.get("name"),
            "cover": x.get("cover") or x.get("thumb_url") or x.get("poster"),
        })
    return out, data


def _wrap(res, extra=None):
    if not isinstance(res, dict):
        return json_response({"error": "respons provider tidak valid"}, 502)
    payload = {"author": "Fi x Zam シ", "source": "sonzai-native"}
    payload.update(res)
    if extra:
        payload.update(extra)
    return json_response(payload)


def _get_provider(name):
    p = PROVIDERS.get(name)
    if p is None:
        return None, json_response({"error": f"provider '{name}' tidak tersedia"}, 404)
    return p, None


# ── home ────────────────────────────────────────────────────────────
@sonzai_native_bp.route("/sonzai/<name>/home", methods=["GET"])
def home(name):
    p, err = _get_provider(name)
    if err: return err
    params = {"lang": request.args.get("lang", DEFAULT_LANG.get(name, "id")), "page": request.args.get("page", 1)}
    try:
        res = _run(p.home(params))
    except Exception as e:
        return json_response({"error": f"{name}: {type(e).__name__}: {e}"}, 502)
    items, data = _slim_items(res)
    return _wrap({"type": "home", "count": len(items), "items": items})


# ── search ──────────────────────────────────────────────────────────
@sonzai_native_bp.route("/sonzai/<name>/search", methods=["GET"])
def search(name):
    p, err = _get_provider(name)
    if err: return err
    q = request.args.get("q") or request.args.get("keyword")
    if not q:
        return json_response({"error": "q required"}, 400)
    params = {"q": q, "keyword": q, "lang": request.args.get("lang", DEFAULT_LANG.get(name, "id"))}
    try:
        res = _run(p.search(params))
    except Exception as e:
        return json_response({"error": f"{name}: {type(e).__name__}: {e}"}, 502)
    items, data = _slim_items(res)
    return _wrap({"type": "search", "q": q, "count": len(items), "items": items})


# ── detail / chapters ───────────────────────────────────────────────
@sonzai_native_bp.route("/sonzai/<name>/detail", methods=["GET"])
@sonzai_native_bp.route("/sonzai/<name>/chapters", methods=["GET"])
def detail(name):
    p, err = _get_provider(name)
    if err: return err
    did = (request.args.get("id") or request.args.get("book_id")
           or request.args.get("drama_id") or request.args.get("vid"))
    if not did:
        return json_response({"error": "id required"}, 400)
    params = {"id": did, "book_id": did, "drama_id": did,
              "lang": request.args.get("lang", DEFAULT_LANG.get(name, "id"))}
    # coba 'detail', fallback 'chapters' (ReelShort pakai 'chapters')
    route_method = p.route("detail") or p.route("chapters")
    if route_method is None:
        return json_response({"error": f"{name}: tidak punya endpoint detail"}, 404)
    try:
        res = _run(route_method(params))
    except Exception as e:
        return json_response({"error": f"{name}: {type(e).__name__}: {e}"}, 502)
    return _wrap({"type": "detail", "data": res})


# ── stream / play ───────────────────────────────────────────────────
@sonzai_native_bp.route("/sonzai/<name>/stream", methods=["GET"])
@sonzai_native_bp.route("/sonzai/<name>/play", methods=["GET"])
def stream(name):
    p, err = _get_provider(name)
    if err: return err
    did = (request.args.get("id") or request.args.get("book_id")
           or request.args.get("drama_id") or request.args.get("vid"))
    if not did:
        return json_response({"error": "id required"}, 400)
    params = {"id": did, "book_id": did, "drama_id": did, "vid": did,
              "ep": request.args.get("ep", 1), "episode": request.args.get("ep", 1),
              "quality": request.args.get("quality"),
              "lang": request.args.get("lang", DEFAULT_LANG.get(name, "id"))}
    route_method = p.route("stream")
    try:
        res = _run(route_method(params))
    except Exception as e:
        return json_response({"error": f"{name}: {type(e).__name__}: {e}"}, 502)
    return _wrap({"type": "stream", "data": res})


# ── download (full video: HLS -> remux MP4 via downloader Sonzai) ────
@sonzai_native_bp.route("/sonzai/<name>/download", methods=["GET"])
def download(name):
    p, err = _get_provider(name)
    if err: return err
    did = (request.args.get("id") or request.args.get("book_id")
           or request.args.get("drama_id") or request.args.get("vid"))
    if not did:
        return json_response({"error": "id required"}, 400)
    params = {"id": did, "book_id": did, "drama_id": did, "vid": did,
              "ep": request.args.get("ep", 1), "chapter_index": request.args.get("chapter_index", 0),
              "chapter_id": request.args.get("chapter_id"),
              "format": request.args.get("format", "mp4"),
              "quality": request.args.get("quality"),
              "lang": request.args.get("lang", DEFAULT_LANG.get(name, "id"))}
    # resolve URL video via provider (async, lewat event loop persisten)
    try:
        info = _run(p.resolve_download(params))
    except Exception as e:
        return json_response({"error": f"{name}: {type(e).__name__}: {e}"}, 502)
    if not isinstance(info, dict) or not info.get("url"):
        return json_response({"error": f"{name}: no video url", "detail": info}, 502)

    url = info["url"]
    native_mp4 = info.get("type") == "mp4"
    fmt = params["format"]
    tok = getattr(p, "auth_token", None)

    # pakai downloader + remux Sonzai (async) via event loop persisten
    import hashlib
    from app import downloader as _dl
    import httpx as _httpx
    cache_dir = "/home/ubuntu/fixzam/cache"
    os.makedirs(cache_dir, exist_ok=True)
    key_raw = f"{name}|{sorted(params.items())}|{fmt}"
    ckey = hashlib.sha256(key_raw.encode()).hexdigest()[:24]
    out_ext = "mp4" if (fmt == "mp4" or native_mp4) else "ts"
    cache_path = os.path.join(cache_dir, f"{name}-{ckey}.{out_ext}")

    # kalau cache udah ada, langsung serve
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        from flask import send_file
        return send_file(cache_path, mimetype="video/mp4" if out_ext == "mp4" else "video/mp2t")

    async def _produce():
        client = _httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        ah = None
        if tok:
            ah = {"User-Agent": _dl.random_ua(), "Accept": "*/*", "Authorization": f"Bearer {tok}"}
        ua = _dl.random_ua()
        if out_ext == "mp4" and not native_mp4:
            seg_iter = _dl.iter_hls(client, url, headers=ah, drm_token=info.get("drm_token"), ua=ua)
            final = await _dl.remux_ts_to_mp4(seg_iter, cache_path)
            await client.aclose()
            return final
        if native_mp4:
            raw = cache_path + ".raw.mp4"
            seg_iter = _dl.iter_mp4(client, url, headers=ah, ua=ua)
            tmp = raw + ".part"
            with open(tmp, "wb") as f:
                async for chunk in seg_iter:
                    f.write(chunk)
            os.replace(tmp, raw)
            codec = _dl.probe_video_codec(raw)
            if codec in ("hevc", "h265", "vp9", "av1"):
                await _dl.transcode_to_h264(raw, cache_path)
            else:
                os.replace(raw, cache_path)
            await client.aclose()
            return cache_path
        # ts langsung
        seg_iter = _dl.iter_hls(client, url, headers=ah, drm_token=info.get("drm_token"), ua=ua)
        tmp = cache_path + ".part"
        with open(tmp, "wb") as f:
            async for chunk in seg_iter:
                f.write(chunk)
        os.replace(tmp, cache_path)
        await client.aclose()
        return cache_path

    try:
        final = _run(_produce())
    except Exception as e:
        return json_response({"error": f"{name} download: {type(e).__name__}: {e}"}, 502)
    from flask import send_file
    if not os.path.exists(final) or os.path.getsize(final) == 0:
        return json_response({"error": f"{name}: no playable video produced"}, 502)
    return send_file(final, mimetype="video/mp4" if out_ext == "mp4" else "video/mp2t")
