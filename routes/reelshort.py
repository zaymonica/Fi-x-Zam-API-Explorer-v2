"""
routes/reelshort.py — ReelShort Short Drama API (bahasa Indonesia)
Reverse-engineered from ReelShort v3.8.00 APK (com.crazymaple.reelshort)

Sign: HMAC-SHA256(secret, sorted_params_string)
  - Secret key extracted from libstupid.so .rodata offset 0x49240
  - Function: SBUtil.sha256Encrypt(str, normalSignKey=1)

Bahasa: header `lang` harus "in" untuk bahasa Indonesia (bukan "ID" / "id").
Sumber: com/newleaf/app/android/victor/manager/c.java
    `StringsKt.r(language, "id") ? ScarConstants.IN_SIGNAL_KEY : "en"`
    (ScarConstants.IN_SIGNAL_KEY = "in")

Endpoint publik (mengikuti pola meloshort/netshort):
  GET  /reelshort/home         — homepage / discover
  GET  /reelshort/new          — waterfall (daftar drama terbaru)
  GET  /reelshort/populer      — leaderboard / trending
  GET  /reelshort/search?q=... — pencarian
  GET  /reelshort/detail?id=.. — detail drama + daftar episode
  GET  /reelshort/stream?id=..&ep=.. — stream episode (video URL)

Helper (manajemen session):
  POST /reelshort/set-session  — inject session hasil capture device (workaround)
  GET  /reelshort/session      — lihat state session sekarang
"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
import zlib

import urllib.parse

import requests as http_requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from flask import Blueprint, request

from utils import json_response, error_response
from config import API_AUTHOR, API_CONTACT

reelshort_bp = Blueprint('reelshort', __name__, url_prefix='/reelshort')

# ─── Constants ────────────────────────────────────────────────────────
BASE_URL = "https://v-api.crazymaplestudios.com"
CDN_URL = "https://d1k8g7qaebqd28.cloudfront.net"

CHANNEL_ID = "AVG10003"
CLIENT_VER = "3.8.00"
API_VERSION = "1.4.14"
LANG = "in"  # Indonesian — per ScarConstants.IN_SIGNAL_KEY
DEV_ID = os.getenv("REELSHORT_DEV_ID", "5482c0b4fb836c76")

# Sign keys dari libstupid.so .rodata
_SIGN_KEYS = {
    1: "zj8N6zKEdrK8d1MxwHSvExdgQ868q1yT",  # normalSignKey  @ 0x49240
    2: "zj8N6zKEdrK8d1MxwHSvExdgQ868q1yT",  # reportSignKey
    3: "uJBPo3e5hEqGebFfxi8yAEuBELtViMqj",  # feedbackSignKey @ 0x49280
}

_state = {
    "uid": 0,
    "session": "",
    "devId": DEV_ID,
}


# ─── Sign generation (verified) ──────────────────────────────────────
def _generate_sign(params_dict, key_type=1):
    secret = _SIGN_KEYS.get(key_type, _SIGN_KEYS[1])
    parts = []
    for k in sorted(params_dict.keys()):
        v = str(params_dict.get(k, ""))
        if v:
            parts.append(f"{k}={v}")
    sign_input = "&".join(parts)
    return hmac.new(
        secret.encode("utf-8"),
        sign_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _make_headers_and_sign(body_params=None, lang_override=None):
    ts = str(int(time.time()))
    trace_id = str(int(time.time() * 1000)) + str(abs(hash(uuid.uuid4())) % 10000)
    uid = str(_state.get("uid", 0))
    session = _state.get("session", "")
    dev_id = _state.get("devId", DEV_ID)
    lang_val = lang_override or LANG

    sign_params = {
        "uid": uid,
        "channelId": CHANNEL_ID,
        "ts": ts,
        "apiVersion": API_VERSION,
        "session": session,
        "lang": lang_val,
        "devId": dev_id,
        "clientVer": CLIENT_VER,
        "clientTraceId": trace_id,
    }
    if body_params:
        sign_params.update(body_params)

    sign = _generate_sign(sign_params)

    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept-encoding": "br,gzip",
        "content-type": "application/x-www-form-urlencoded",
        "uid": uid,
        "channelid": CHANNEL_ID,
        "ts": ts,
        "apiversion": API_VERSION,
        "session": session,
        "lang": lang_val,
        "devid": dev_id,
        "clientver": CLIENT_VER,
        "clienttraceid": trace_id,
        "sign": sign,
    }
    return headers


# ─── HTTP ────────────────────────────────────────────────────────────
def _post(endpoint, data=None, use_cdn=False, lang_override=None, _retry=False):
    base = CDN_URL if use_cdn else BASE_URL
    url = f"{base}/{endpoint.lstrip('/')}"
    headers = _make_headers_and_sign(data, lang_override=lang_override)
    try:
        resp = http_requests.post(
            url, headers=headers, data=data or {}, timeout=20,
        )
        result = resp.json()
    except Exception as e:
        if not use_cdn:
            return _post(endpoint, data, use_cdn=True, lang_override=lang_override)
        return {"error": "Failed to fetch upstream", "detail": str(e)}

    # Session expired → auto re-login sekali
    if isinstance(result, dict) and result.get("code") == 101 and not _retry:
        _state["session"] = ""
        _state["uid"] = 0
        _ensure_session()
        return _post(endpoint, data, use_cdn=use_cdn,
                     lang_override=lang_override, _retry=True)

    if isinstance(result, dict):
        result.pop("ip", None)
    return result


def _ensure_session():
    if _state.get("session"):
        return
    result = _post("api/video/user/userLogin", {
        "dev_model": "SM-A156E",
        "os": "android",
        "os_version": "14",
        "sid": "1",
    })
    data = result.get("data", {}) if isinstance(result, dict) else {}
    if data.get("session"):
        _state["uid"] = data.get("user_info", {}).get("uid", 0)
        _state["session"] = data["session"]
        _state["devId"] = data.get("devId", DEV_ID)


def _resp(type_, data, extra=None):
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": data,
    }
    if extra:
        payload.update(extra)
    return json_response(payload)


# ═══════════════════════════════════════════════════════════════════════
#  Normalization → app shape
#
#  The Fi x Zam app expects every short-drama list endpoint to return
#  `data: [ { "books": [ <MeloloBook> ] } ]`, where a MeloloBook has
#  drama_id / drama_name / thumb_url / episode_count(str) / description /
#  watch_value / tags. ReelShort's upstream gives book dicts with
#  book_id / book_title / book_pic / chapter_count / special_desc, and
#  wraps them in three different container shapes (flat list, dict with
#  `books`, or sections each holding `books`). These helpers flatten any
#  of those into the app shape.
# ═══════════════════════════════════════════════════════════════════════
def _norm_book(b):
    """Map a ReelShort book dict → app MeloloBook shape."""
    tags = b.get("tag_list") or b.get("tag") or b.get("theme") or []
    if isinstance(tags, str):
        tags = [tags]
    # tag_list entries can be objects {tag_name:...}; flatten to strings
    flat_tags = []
    for t in tags:
        if isinstance(t, dict):
            name = t.get("tag_name") or t.get("name") or t.get("theme_name")
            if name:
                flat_tags.append(name)
        elif t:
            flat_tags.append(str(t))
    return {
        "drama_id": b.get("book_id") or b.get("t_book_id") or "",
        "drama_name": b.get("book_title") or "",
        "description": b.get("special_desc") or b.get("book_sub_title") or "",
        "episode_count": str(b.get("chapter_count") or 0),
        "watch_value": str(b.get("read_count") or b.get("collect_count") or ""),
        "is_new_book": "0",
        "language": b.get("lang") or "in",
        "thumb_url": b.get("book_pic") or "",
        "tags": flat_tags,
    }


def _collect_books(data):
    """Pull every book dict out of any ReelShort list container shape."""
    books = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("books"), list):
                books.extend(node["books"])
            # a bare book dict (search/new flat items)
            elif node.get("book_id") or node.get("book_title"):
                books.append(node)
            else:
                for v in node.values():
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return books


def _norm_list_resp(type_, raw_data, extra=None):
    """Reshape any ReelShort list payload into app shape: [{books:[...]}]."""
    books = [_norm_book(b) for b in _collect_books(raw_data) if (b.get("book_id") or b.get("t_book_id"))]
    return _resp(type_, [{"books": books}], extra)


# ═══════════════════════════════════════════════════════════════════════
#  SESSION MANAGEMENT (helper)
# ═══════════════════════════════════════════════════════════════════════
@reelshort_bp.route('/set-session', methods=['POST'])
def reelshort_set_session():
    """POST JSON: {"uid":..., "session":"...", "devId":"..."}"""
    body = request.get_json(force=True) or {}
    if body.get("uid"):
        _state["uid"] = body["uid"]
    if body.get("session"):
        _state["session"] = body["session"]
    if body.get("devId"):
        _state["devId"] = body["devId"]
    return json_response({"status": "session updated", "state": _state})


@reelshort_bp.route('/session', methods=['GET'])
def reelshort_get_session():
    return json_response({"state": _state})


# ═══════════════════════════════════════════════════════════════════════
#  /home — Discover / Homepage
# ═══════════════════════════════════════════════════════════════════════
@reelshort_bp.route('/home', methods=['GET'])
def home():
    _ensure_session()
    try:
        data = _post("api/ms/hall/infoV4", {
            "is_first_req": "1",
            "widescreen": "0",
            "no_continue_watch": "0",
            "current_level1_tab_id": request.args.get('tab_id', '0'),
            "current_level2_tab_id": request.args.get('sub_tab_id', '0'),
            "action_type": "0",
        })
        return _norm_list_resp("home", data.get("data", {}))
    except Exception as e:
        return error_response(500, f"ReelShort /home error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /new — Drama Terbaru (waterfall)
#
# Waterfall endpoint butuh bs_id valid. Kalau caller tidak kasih,
# otomatis ambil bs_id dari section kedua (biasanya waterfall utama)
# pada /home infoV4.
# ═══════════════════════════════════════════════════════════════════════
_cached_waterfall_bs_id = {"val": None, "ts": 0}

def _resolve_waterfall_bs_id():
    """Ambil bs_id waterfall dari infoV4 — cached 10 menit."""
    now = time.time()
    if _cached_waterfall_bs_id["val"] and (now - _cached_waterfall_bs_id["ts"] < 600):
        return _cached_waterfall_bs_id["val"]
    info = _post("api/ms/hall/infoV4", {
        "is_first_req": "1",
        "widescreen": "0",
        "no_continue_watch": "0",
        "current_level1_tab_id": "0",
        "current_level2_tab_id": "0",
        "action_type": "0",
    })
    sections = (info.get("data") or {}).get("lists") or []
    # Pilih section terakhir yang punya bs_id (waterfall biasanya paling akhir)
    for sec in reversed(sections):
        bs = sec.get("bs_id")
        if bs:
            _cached_waterfall_bs_id["val"] = str(bs)
            _cached_waterfall_bs_id["ts"] = now
            return str(bs)
    return "0"


@reelshort_bp.route('/new', methods=['GET'])
def new():
    _ensure_session()
    page = request.args.get('page', '1')
    limit = request.args.get('limit', '20')
    bs_id = request.args.get('bs_id') or _resolve_waterfall_bs_id()
    try:
        data = _post("api/ms/hall/hallWaterfallPagesV4", {
            "bs_id": bs_id,
            "page": page,
            "limit": limit,
            "widescreen": "0",
        })
        return _norm_list_resp("new", data.get("data", {}), {
            "page": int(page),
            "bs_id": bs_id,
        })
    except Exception as e:
        return error_response(500, f"ReelShort /new error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /populer — Leaderboard / Trending
# ═══════════════════════════════════════════════════════════════════════
@reelshort_bp.route('/populer', methods=['GET'])
def populer():
    _ensure_session()
    page = request.args.get('page', '1')
    limit = request.args.get('limit', '20')
    try:
        data = _post("api/ms/hall/getLeaderboardPageV4", {
            "page": page,
            "limit": limit,
            "bs_id": request.args.get('bs_id', '0'),
            "ranking_period": request.args.get('period', '0'),
            "ranking_rule": request.args.get('rule', '0'),
        })
        return _norm_list_resp("populer", data.get("data", {}), {"page": int(page)})
    except Exception as e:
        return error_response(500, f"ReelShort /populer error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /search — Search dramas by keyword
# ═══════════════════════════════════════════════════════════════════════
@reelshort_bp.route('/search', methods=['GET'])
def search():
    _ensure_session()
    query = request.args.get('q', '') or request.args.get('query', '') or request.args.get('word', '')
    if not query:
        return error_response(400, "Missing 'q' parameter")
    page = request.args.get('page', '1')
    limit = request.args.get('limit', '10')
    try:
        data = _post("api/video/search/search", {
            "word": query,
            "page": page,
            "limit": limit,
        })
        return _norm_list_resp("search", data.get("data", {}), {
            "query": query,
            "page": int(page),
        })
    except Exception as e:
        return error_response(500, f"ReelShort /search error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /detail — Drama detail + daftar episode
# ═══════════════════════════════════════════════════════════════════════
@reelshort_bp.route('/detail', methods=['GET'])
def detail():
    _ensure_session()
    book_id = request.args.get('id') or request.args.get('book_id') or request.args.get('bookId')
    if not book_id:
        return error_response(400, "Missing 'id' (book_id) parameter")

    try:
        # Info utama buku
        detail_resp = _post("api/video/book/getBookDetailV2", {
            "book_id": book_id,
            "from": request.args.get('from', '0'),
            "play_details": "1",
        })
        detail_data = detail_resp.get("data") or {}
        book_info = detail_data.get("retBook") or {}

        # Daftar episode (chapter list lengkap). Upstream key has drifted
        # between chapter_lists / chapter_list — accept either.
        chapters_resp = _post("api/video/book/getChapterList", {
            "book_id": book_id,
        })
        ch_data = chapters_resp.get("data") or {}
        chapters = ch_data.get("chapter_lists") or ch_data.get("chapter_list") or []

        # app-shape episode list (ReelshortEpisode: index, chapterId, title,
        # isLocked, serialNumber). Skip serial 0 (trailer) — episodes are 1-based.
        video_list = []
        for c in chapters:
            serial = c.get("serial_number")
            if serial is None or serial < 1:
                continue
            video_list.append({
                "index": serial,
                "serialNumber": serial,
                "chapterId": c.get("chapter_id"),
                "title": c.get("chapter_name") or f"Episode {serial}",
                "isLocked": bool(c.get("is_lock", 0)) or bool(c.get("charge", 0)),
            })

        tags = book_info.get("tag") or book_info.get("theme") or []
        if isinstance(tags, str):
            tags = [tags]

        return _resp("detail", {
            # ── app (Fi x Zam) shape ──
            "drama_id": book_info.get("book_id", book_id),
            "drama_name": book_info.get("book_title", ""),
            "description": book_info.get("special_desc", "") or book_info.get("book_sub_title", ""),
            "episode_count": book_info.get("chapter_count", len(chapters)),
            "thumb_url": book_info.get("book_pic", ""),
            "tags": tags,
            "watch_value": str(book_info.get("read_count", "")),
            "video_list": video_list,
            # ── raw fields (kept for the web UI / other consumers) ──
            "book_id": book_info.get("book_id", book_id),
            "book_title": book_info.get("book_title", ""),
            "book_pic": book_info.get("book_pic", ""),
            "book_sub_title": book_info.get("book_sub_title", ""),
            "special_desc": book_info.get("special_desc", ""),
            "share_text": book_info.get("share_text", ""),
            "chapter_count": book_info.get("chapter_count", len(chapters)),
            "tag": book_info.get("tag", []),
            "theme": book_info.get("theme", []),
            "lang": book_info.get("lang", LANG),
            "score": book_info.get("score", 0),
            "read_count": book_info.get("read_count", 0),
            "status": book_info.get("status", 0),
            "paid_start": book_info.get("paid_start", 0),
            "is_paid": book_info.get("is_paid", 0),
            "is_collect": book_info.get("is_collect", 0),
            "is_preview": book_info.get("is_preview", 0),
            "has_video": book_info.get("has_video", False),
            "have_trailer": book_info.get("have_trailer", False),
            "first_chapter_id": book_info.get("first_chapter_id", ""),
            "book_share_url": book_info.get("book_share_url", ""),
            "actors": book_info.get("actors", []),
            "cast": book_info.get("cast", []),
            "episodes": chapters,
        })
    except Exception as e:
        return error_response(500, f"ReelShort /detail error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /stream — Episode stream info (video URL)
# ═══════════════════════════════════════════════════════════════════════

# ─── play_info decryption ────────────────────────────────────────────
# Reverse-engineered from libstupid.so (SBUtil.decryptChapterContent):
#   1) AES-128-CBC (key = "VvRSNGFynLBW7aCP", iv = "gLn8sxqpzyNjehDP"),
#      PKCS7 padded — keys & IV are obfuscated MOV/MOVK constants in the
#      fns pointed to by SBUtil.PRIVATE_KEY_VERSION (=2) at fn 0x741b8 /
#      0x742ac inside libstupid.so.
#   2) base64 decode the plaintext
#   3) raw zlib (deflate) inflate → JSON array of {PlayURL, Encode, Dpi, ...}
_PLAY_INFO_KEY = b"VvRSNGFynLBW7aCP"
_PLAY_INFO_IV  = b"gLn8sxqpzyNjehDP"


def _decrypt_play_info(play_info_b64):
    if not play_info_b64:
        return []
    try:
        raw = base64.b64decode(play_info_b64)
        cipher = AES.new(_PLAY_INFO_KEY, AES.MODE_CBC, _PLAY_INFO_IV)
        stage1 = unpad(cipher.decrypt(raw), 16)
        stage2 = base64.b64decode(stage1)
        plain = zlib.decompress(stage2)
        return json.loads(plain.decode("utf-8", "replace"))
    except Exception:
        return []


def _pick_best_playurl(streams):
    """Pilih URL terbaik: prioritaskan H264 (kompatibilitas player lebih luas),
    lalu resolusi (dpi) tertinggi."""
    if not streams:
        return ""
    h264 = [s for s in streams if (s.get("Encode") or "").upper() == "H264"]
    pool = h264 or streams
    try:
        best = max(pool, key=lambda s: int(s.get("Dpi") or 0))
    except Exception:
        best = pool[0]
    return best.get("PlayURL", "")


@reelshort_bp.route('/stream', methods=['GET'])
def stream():
    _ensure_session()
    book_id = (request.args.get('id') or request.args.get('book_id')
               or request.args.get('bookId'))
    if not book_id:
        return error_response(400, "Missing 'id' (book_id) parameter")

    chapter_id = (request.args.get('ep') or request.args.get('chapter_id')
                  or request.args.get('chapterId'))
    episode_no = request.args.get('episode_no')

    try:
        # chapter list (accept drifted key chapter_lists / chapter_list)
        chapters_resp = _post("api/video/book/getChapterList", {"book_id": book_id})
        ch_data = chapters_resp.get("data") or {}
        chapter_list = ch_data.get("chapter_lists") or ch_data.get("chapter_list") or []

        # Resolve chapter_id + serial_number
        serial_number = None
        if chapter_id:
            match = next((c for c in chapter_list if c.get("chapter_id") == chapter_id), None)
            if match:
                serial_number = match.get("serial_number")
        else:
            if not chapter_list:
                return error_response(404, "No chapters found for this drama")
            if episode_no is not None:
                try:
                    target = int(episode_no)
                except ValueError:
                    target = 1
                match = next((c for c in chapter_list if c.get("serial_number") == target), None)
                if not match:
                    idx = max(0, target)
                    if idx >= len(chapter_list):
                        return error_response(
                            404, f"Episode {episode_no} not found (total: {len(chapter_list)})")
                    match = chapter_list[idx]
                chapter_id = match.get("chapter_id")
                serial_number = match.get("serial_number")
            else:
                chapter_id = chapter_list[0].get("chapter_id")
                serial_number = chapter_list[0].get("serial_number")

        if not chapter_id:
            return error_response(500, "Failed to resolve chapter_id")

        data = _post("api/video/book/getChapterContent", {
            "book_id": book_id,
            "chapter_id": chapter_id,
        })
        content = data.get("data") or {}

        clips = content.get("json_string") or []
        primary = clips[0] if clips else {}

        decoded_clips = []
        for c in clips:
            streams = _decrypt_play_info(c.get("play_info", ""))
            decoded_clips.append({
                "clip_id": c.get("clip_id"),
                "sum_clip_id": c.get("sum_clip_id"),
                "video_id": c.get("video_id"),
                "video_pic": c.get("video_pic"),
                "duration": c.get("duration"),
                "is_last_clip": c.get("is_last_clip", 0),
                "streams": streams,
                "play_url": _pick_best_playurl(streams),
            })

        # Single-episode responses expose play_info as a top-level STRING field
        # (not a json_string clip array). Decode it as the primary clip.
        if not decoded_clips and isinstance(content.get("play_info"), str):
            streams = _decrypt_play_info(content.get("play_info", ""))
            if streams:
                decoded_clips.append({
                    "clip_id": None,
                    "sum_clip_id": None,
                    "video_id": content.get("video_id"),
                    "video_pic": content.get("video_pic"),
                    "duration": content.get("duration"),
                    "is_last_clip": 1,
                    "streams": streams,
                    "play_url": _pick_best_playurl(streams),
                })

        primary_streams = decoded_clips[0]["streams"] if decoded_clips else []
        primary_url = decoded_clips[0]["play_url"] if decoded_clips else ""
        if not primary and decoded_clips:
            primary = decoded_clips[0]

        # ── app-shape videoList (ReelshortVideo: playUrl, encode, dpi, bitrate) ──
        # Native play_info (H264 + H265) for unlocked episodes; H264 preferred
        # since it's most compatible. Order H264 first, then by dpi desc.
        video_list = []
        for s in sorted(
            primary_streams,
            key=lambda s: ((s.get("Encode") or "").upper() == "H264", int(s.get("Dpi") or 0)),
            reverse=True,
        ):
            url = s.get("PlayURL", "")
            if not url:
                continue
            video_list.append({
                "playUrl": url,
                "encode": (s.get("Encode") or "").upper(),
                "dpi": s.get("Dpi"),
                "bitrate": str(s.get("Bitrate") or ""),
            })

        is_locked = bool(content.get("is_preview", 0)) or not video_list

        # Locked/paid episode → native gives nothing. Fall back to the dramakuy
        # resolver (HEVC). Android's ExoPlayer decodes HEVC fine, so this is a
        # usable fallback for the app (unlike desktop browsers).
        if not video_list and serial_number is not None:
            d_data, d_err = _dramakuy_resolve(book_id, serial_number)
            if not d_err and isinstance(d_data, dict):
                sd_url = ""
                for s in (d_data.get("videoList") or d_data.get("streams") or []):
                    sd_url = _absolutize_dramakuy_url(s.get("url", ""))
                    if sd_url:
                        break
                variants = _cdn_master_variants(sd_url) if sd_url else []
                if not variants and sd_url:
                    variants = [{"url": sd_url, "quality": 720, "encode": "H265"}]
                for v in variants:
                    video_list.append({
                        "playUrl": v["url"],
                        "encode": v.get("encode", "H265"),
                        "dpi": v.get("quality"),
                        "bitrate": str(v.get("bandwidth") or ""),
                    })
                if video_list:
                    primary_url = primary_url or video_list[0]["playUrl"]
                    is_locked = False

        return _resp("stream", {
            # ── app (Fi x Zam) shape: ReelshortStreamData ──
            "isLocked": is_locked,
            "videoList": video_list,
            # ── raw fields (kept for the web UI / other consumers) ──
            "book_id": content.get("book_id", book_id),
            "book_title": content.get("book_title", ""),
            "chapter_id": content.get("chapter_id", chapter_id),
            "chapter_name": content.get("chapter_name", ""),
            "video_pic": content.get("video_pic", "") or primary.get("video_pic", ""),
            "duration": primary.get("duration"),
            "is_preview": content.get("is_preview", 0),
            "is_auto_pay": content.get("is_auto_pay", 0),
            "unlock_cost": content.get("unlock_cost", 0),
            "screen_mode": content.get("screen_mode", 1),
            "video_id": primary.get("video_id", ""),
            "play_url": primary_url,
            "streams": primary_streams,
            "clips": decoded_clips,
        })
    except Exception as e:
        return error_response(500, f"ReelShort /stream error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /streamv2 — Playback via dramakuy resolver (bypass libstupid decrypt)
#
# dramakuy.com hosts a ReelShort resolver that returns the play info as a
# CryptoJS AES "Salted__" blob (OpenSSL EVP_BytesToKey/MD5, AES-CBC). The
# passphrase was recovered from dramakuy's Next.js bundle. Decrypted JSON
# carries videoList/streams with v-mps.crazymaplestudios.com m3u8 URLs
# (wrapped behind dramakuy's own /api/proxy/video).
#
# Unlike /stream this takes bookId + episodeNumber directly — no chapter_id
# resolution or libstupid play_info decryption needed.
# ═══════════════════════════════════════════════════════════════════════
DRAMAKUY_BASE = "https://dramakuy.com"
DRAMAKUY_PASSPHRASE = "DracinBox-SecureKey2026"


def _cryptojs_decrypt(b64_blob, passphrase):
    """Decrypt a CryptoJS AES 'Salted__' blob (OpenSSL EVP_BytesToKey/MD5)."""
    raw = base64.b64decode(b64_blob)
    if raw[:8] != b"Salted__":
        raise ValueError("not a CryptoJS salted blob")
    salt = raw[8:16]
    ct = raw[16:]
    d = b""
    prev = b""
    pw = passphrase.encode()
    while len(d) < 48:
        prev = hashlib.md5(prev + pw + salt).digest()
        d += prev
    key, iv = d[:32], d[32:48]
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    return unpad(pt, 16)


def _dramakuy_resolve(book_id, episode_number):
    """Call dramakuy ReelShort resolver and return decrypted play info JSON."""
    url = f"{DRAMAKUY_BASE}/api/reelshort/watch?bookId={book_id}&episodeNumber={episode_number}"
    r = http_requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "referer": f"{DRAMAKUY_BASE}/watch/reelshort/{book_id}/{episode_number}",
    }, timeout=20)
    try:
        body = r.json()
    except Exception:
        return None, f"dramakuy HTTP {r.status_code}"
    blob = body.get("data")
    if not isinstance(blob, str):
        return None, "unexpected dramakuy response"
    try:
        decrypted = json.loads(_cryptojs_decrypt(blob, DRAMAKUY_PASSPHRASE).decode("utf-8"))
    except Exception as e:
        return None, f"decrypt failed: {e}"
    # dramakuy returns 4xx + an encrypted {"error": "..."} for missing titles
    if isinstance(decrypted, dict) and decrypted.get("error"):
        return None, decrypted["error"]
    return decrypted, None


def _absolutize_dramakuy_url(u):
    """dramakuy wraps the real m3u8 in /api/proxy/video?url=<encoded>&referer=...
    Unwrap it to the direct v-mps.crazymaplestudios.com URL (plays without proxy).
    Falls back to prepending the dramakuy host for non-proxy relative URLs."""
    if not u:
        return u
    parsed = urllib.parse.urlparse(u)
    if parsed.path.endswith("/api/proxy/video"):
        inner = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if inner:
            return urllib.parse.unquote(inner)
    if u.startswith("/"):
        return DRAMAKUY_BASE + u
    return u


def _cdn_master_variants(sd_url):
    """Given a single ...-video-sd.m3u8 URL, derive the CDN master playlist
    (/{video_id}/{hash}.m3u8) and parse all quality variants (ld/sd/hd =
    540p/720p/1080p). All variants are HEVC/H265. Returns [] on failure so
    the caller can fall back to the single sd URL.

    sd path:  /{video_id}/video/{hash}-{q}-video-sd.m3u8
    master:   /{video_id}/{hash}.m3u8
    """
    try:
        parsed = urllib.parse.urlparse(sd_url)
        parts = parsed.path.split("/")
        # ['', video_id, 'video', '{hash}-{q}-video-sd.m3u8']
        if len(parts) < 4 or parts[2] != "video":
            return []
        video_id = parts[1]
        file_hash = parts[3].split("-", 1)[0]
        master_url = f"{parsed.scheme}://{parsed.netloc}/{video_id}/{file_hash}.m3u8"
        r = http_requests.get(master_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if r.status_code != 200 or "EXT-X-STREAM-INF" not in r.text:
            return []
        base = master_url.rsplit("/", 1)[0] + "/"
        out = []
        lines = r.text.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF"):
                continue
            attrs = line.split(":", 1)[1] if ":" in line else ""
            res = ""
            bw = 0
            for a in attrs.split(","):
                a = a.strip()
                if a.startswith("RESOLUTION="):
                    res = a.split("=", 1)[1]
                elif a.startswith("BANDWIDTH="):
                    try:
                        bw = int(a.split("=", 1)[1])
                    except ValueError:
                        pass
            rel = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not rel or rel.startswith("#"):
                continue
            # portrait video: width is the conventional quality label (540/720/1080)
            quality = None
            if "x" in res:
                try:
                    quality = int(res.split("x")[0])
                except ValueError:
                    quality = None
            out.append({
                "url": base + rel if not rel.startswith("http") else rel,
                "quality": quality,
                "resolution": res,
                "bandwidth": bw,
                "encode": "H265",
            })
        out.sort(key=lambda s: s.get("quality") or 0, reverse=True)
        return out
    except Exception:
        return []


def _native_streams_for_episode(book_id, ep_num):
    """Decrypt native play_info for an episode → list of {url, encode, quality}.

    Native API exposes an H264 variant (browser-playable) alongside H265, but
    only for unlocked/free episodes. Returns [] when the episode is locked or
    has no play_info. Uses the authenticated session like /stream does.
    """
    _ensure_session()
    cl_resp = _post("api/video/book/getChapterList", {"book_id": book_id})
    cl = (cl_resp.get("data") or {}).get("chapter_lists") \
        or (cl_resp.get("data") or {}).get("chapter_list") or []
    match = next((c for c in cl if c.get("serial_number") == ep_num), None)
    if not match:
        return []
    cc = _post("api/video/book/getChapterContent", {
        "book_id": book_id,
        "chapter_id": match.get("chapter_id"),
    })
    ccd = cc.get("data") or {}
    streams = _decrypt_play_info(ccd.get("play_info", ""))
    out = []
    for s in streams:
        url = s.get("PlayURL", "")
        if not url:
            continue
        out.append({
            "url": url,
            "quality": s.get("Dpi"),
            "encode": (s.get("Encode") or "").upper(),
        })
    return out


@reelshort_bp.route('/streamv2', methods=['GET'])
def streamv2():
    """Resolve a playable ReelShort episode.

    Params:
      id (book_id, required), ep / episode_no (episode number, default 1).

    Prefers the native H264 variant (plays in any browser). The fallback
    source only serves HEVC/H265 m3u8 — audio-only in Chrome/Brave/Firefox —
    so we use it for locked episodes the native API won't return.
    Use ?source=fallback to force the fallback path.
    """
    book_id = request.args.get('id') or request.args.get('book_id')
    if not book_id:
        return error_response(400, "Missing 'id' (book_id) parameter")

    episode_no = request.args.get('ep') or request.args.get('episode_no') or '1'
    try:
        ep_num = int(episode_no)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    force = (request.args.get('source') or '').lower()

    try:
        # 1. Native H264 first (browser-playable) unless caller forces fallback
        if force != 'fallback':
            native = _native_streams_for_episode(book_id, ep_num)
            h264 = [s for s in native if s["encode"] == "H264"]
            if h264:
                best = max(h264, key=lambda s: int(s.get("quality") or 0))
                return _resp("streamv2", {
                    "book_id": book_id,
                    "serial_number": ep_num,
                    "play_url": best["url"],
                    "encode": "H264",
                    "streams": h264,
                    "source": "native",
                }, {"episode": ep_num})

        # 2. dramakuy fallback (HEVC — fine for HEVC-capable players)
        data, err = _dramakuy_resolve(book_id, ep_num)
        if err:
            return error_response(502, f"Resolver error: {err}")

        # dramakuy only hands back the single 720p sd URL; expand it to all
        # qualities (540/720/1080) via the CDN master playlist when available.
        sd_url = ""
        for s in (data.get("videoList") or data.get("streams") or []):
            sd_url = _absolutize_dramakuy_url(s.get("url", ""))
            if sd_url:
                break

        streams = _cdn_master_variants(sd_url) if sd_url else []
        if not streams and sd_url:
            # master playlist unavailable — fall back to the single sd URL
            streams = [{"url": sd_url, "quality": 720, "encode": "H265"}]

        # default to 720p if present, else the highest available
        play_url = ""
        if streams:
            sd = next((s for s in streams if s.get("quality") == 720), None)
            play_url = (sd or streams[0])["url"]

        return _resp("streamv2", {
            "book_id": book_id,
            "chapter_id": data.get("chapter_id", ""),
            "chapter_name": data.get("chapter_name", ""),
            "serial_number": data.get("serial_number", ep_num),
            "video_id": data.get("video_id", ""),
            "video_pic": data.get("video_pic", ""),
            "duration": data.get("duration"),
            "aspect_ratio": data.get("aspect_ratio"),
            "screen_mode": data.get("screen_mode", 1),
            "is_lock": data.get("is_lock", 0),
            "play_url": play_url,
            "streams": streams,
            "source": "fallback",
            "codec_note": "Fallback source serves HEVC/H265; some desktop browsers play audio only. Use an HEVC-capable player or device.",
        }, {"episode": ep_num})
    except Exception as e:
        return error_response(500, f"ReelShort /streamv2 error: {e}")
