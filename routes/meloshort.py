"""
routes/meloshort.py - MeloShort Short Drama API
Session token di-generate via anonymous login (/incentive/login/anonymous).
Token berlaku ~30 hari; di-cache di file JSON supaya semua gunicorn worker
berbagi satu token yang sama (menghindari rate-limit registrasi device).
"""
import os
import uuid
import time
import json as _json
import threading
import requests
from flask import Blueprint, request
from utils import json_response, error_response

meloshort_bp = Blueprint('meloshort', __name__, url_prefix='/meloshort')

API_AUTHOR = "Sonzai X シ"
API_CONTACT = "https://t.me/November2k"

MELOSHORT_BASE = "https://api.meloshort.com"
DEVICE_UUID = "8524214c-77d2-34e6-be25-252de91c9096"

# Token is cached to a file so all gunicorn workers share the same session.
_TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "meloshort_token.json")
_token_lock = threading.Lock()


def _get_base_headers():
    return {
        "User-Agent": "meloDrama/2.61.00(Android;SM-A156E;12)",
        "Accept-Encoding": "gzip",
        "app": "com.drama.happy.look",
        "os": "1",
        "mobile-brand": "Samsung a15x",
        "device-uuid": DEVICE_UUID,
        "version": "2.61.00",
        "lang": "in",
        "region": "ID",
        "timezone": "Asia/Jakarta",
        "content-type": "application/json; charset=utf-8",
        "locale": "en",
        "hasvpn": "true",
        "hasproxy": "false",
        "developer": "false",
        "emulator": "false",
        "usb": "false",
        "mcc": "",
    }


def _load_token() -> tuple:
    """Load token and expiry from shared file. Returns (token, expires_ts)."""
    try:
        with open(_TOKEN_FILE, "r") as f:
            d = _json.load(f)
        return d.get("token", ""), float(d.get("expires", 0))
    except Exception:
        return "", 0.0


def _save_token(token: str, expires: float):
    os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
    with open(_TOKEN_FILE, "w") as f:
        _json.dump({"token": token, "expires": expires}, f)


def _do_anonymous_login() -> str:
    """POST /incentive/login/anonymous and return a fresh session_token."""
    r = requests.post(
        f"{MELOSHORT_BASE}/incentive/login/anonymous",
        headers=_get_base_headers(),
        json={
            "device_type": "android",
            "device_id": DEVICE_UUID,
            "device_uuid": DEVICE_UUID,
            "country": "ID",
        },
        timeout=20,
    )
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"anonymous login failed: {body.get('msg')}")
    return body["data"]["session_token"]


def get_headers() -> dict:
    """Return headers with a valid (auto-refreshed) session token.
    Token is stored in a shared file so all gunicorn workers use the same one.
    """
    with _token_lock:
        token, expires = _load_token()
        if not token or time.time() >= expires - 1800:
            token = _do_anonymous_login()
            expires = time.time() + 25 * 24 * 3600
            _save_token(token, expires)
    h = _get_base_headers()
    h["x-session-token"] = token
    return h


def format_video_url(url):
    if not url:
        return ""
    if url.startswith('/'):
        return MELOSHORT_BASE + url
    return url


# ── Normalization → SonzaiXBox app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. MeloShort
# returns flat drama items with its own field names (drama_id / drama_title
# / drama_cover / chapters). Map each item to the app's MeloloBook.
def _ms_norm_book(b):
    tags = b.get("tags") or []
    flat = []
    for t in tags:
        if isinstance(t, dict):
            n = t.get("title") or t.get("name")
            if n:
                flat.append(n)
        elif t:
            flat.append(str(t))
    return {
        "drama_id": str(b.get("drama_id") or b.get("dramaId") or b.get("drama_intid") or ""),
        "drama_name": b.get("drama_title") or b.get("title") or b.get("drama_name") or "",
        "description": b.get("description") or "",
        "episode_count": str(b.get("chapters") or b.get("chapterTotal") or 0),
        "watch_value": str(b.get("likes") or b.get("fav_count") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": b.get("drama_cover") or b.get("cover") or b.get("drama_cover_h") or "",
        "tags": flat,
    }


def _ms_list_resp(type_, items, extra=None):
    books = [_ms_norm_book(b) for b in (items or []) if isinstance(b, dict)]
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": [{"books": books}],
    }
    if extra:
        payload.update(extra)
    return json_response(payload)


# ─── Endpoints ─────────────────────────────────────────────────────────────

@meloshort_bp.route('/home', methods=['GET'])
def home():
    page = request.args.get('page', 1)
    url = f"{MELOSHORT_BASE}/v3/all?page={page}&page_size=20&lang=in"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        raw = r.json()
        # data is a list directly
        items = raw.get('data') or []
        if isinstance(items, dict):
            items = items.get('list', [])
        return _ms_list_resp("home", items, {"page": int(page)})
    except Exception as e:
        return error_response(500, f"MeloShort /home error: {e}")


@meloshort_bp.route('/new', methods=['GET'])
def new_recom():
    reset = request.args.get('reset', 1)
    url = f"{MELOSHORT_BASE}/v3/recom_list?reset={reset}&current_chapter=continue&lang=in"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        raw = r.json()
        # data is a dict with key 'list'
        d = raw.get('data') or {}
        items = d.get('list', []) if isinstance(d, dict) else d
        return _ms_list_resp("new", items, {"page": int(reset)})
    except Exception as e:
        return error_response(500, f"MeloShort /new error: {e}")


@meloshort_bp.route('/populer', methods=['GET'])
def populer():
    url = f"{MELOSHORT_BASE}/v3/discover/rank/all?lang=in"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        raw = r.json()
        # data is a dict with 'place_list' — each entry has a 'list' of dramas
        d = raw.get('data') or {}
        place_list = d.get('place_list', []) if isinstance(d, dict) else []
        items = []
        for place in place_list:
            items.extend(place.get('list', []))
        return _ms_list_resp("populer", items)
    except Exception as e:
        return error_response(500, f"MeloShort /populer error: {e}")


@meloshort_bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return error_response(400, "Missing 'query' parameter")
    url = f"{MELOSHORT_BASE}/v1/search?word={query}&lang=in"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        raw = r.json()
        d = raw.get('data') or []
        items = d if isinstance(d, list) else d.get('list', [])
        return _ms_list_resp("search", items, {"query": query})
    except Exception as e:
        return error_response(500, f"MeloShort /search error: {e}")


@meloshort_bp.route('/detail', methods=['GET'])
def detail():
    drama_id = request.args.get('drama_id') or request.args.get('id') or request.args.get('dramaId')
    chapter_id = request.args.get('chapter_id') or request.args.get('ep') or request.args.get('episodeId')

    if not drama_id:
        return error_response(400, "Missing 'drama_id' parameter")

    try:
        list_url = f"{MELOSHORT_BASE}/v1/drama/chapter/list?drama_id={drama_id}&page=1&page_size=1000&lang=in"
        r_list = requests.get(list_url, headers=get_headers(), timeout=15)
        chapter_list = r_list.json().get('data', [])

        if not chapter_id and chapter_list:
            chapter_id = chapter_list[0]['chapter_id']

        drama_info = {}
        if chapter_id:
            info_url = f"{MELOSHORT_BASE}/v1/noval/drama/chapter/detail?drama_id={drama_id}&chapter_id={chapter_id}&auto_pay=1&lang=in"
            r_info = requests.get(info_url, headers=get_headers(), timeout=15)
            drama_info = r_info.json().get('data', {})

        # app-shape episode list (MeloshortEpisode: episode, episode_id, cover, isLocked)
        video_list = []
        for ch in chapter_list:
            video_list.append({
                "episode": ch.get("chapter_index"),
                "episode_id": ch.get("chapter_id"),
                "cover": ch.get("first_frame"),
                "isLocked": not bool(ch.get("is_free", 1)),
            })

        return json_response({
            "type": "detail",
            "data": {
                # ── app (SonzaiXBox) shape ──
                "drama_id": drama_info.get('drama_id', drama_id),
                "drama_name": drama_info.get('drama_title', ''),
                "description": drama_info.get('drama_description', ''),
                "episode_count": drama_info.get('chapters', len(chapter_list)),
                "is_finished": bool(drama_info.get('is_completed', 0)),
                "thumb_url": drama_info.get('drama_cover', ''),
                "tags": [],
                "video_list": video_list,
                # ── raw fields ──
                "drama_title": drama_info.get('drama_title', ''),
                "chapters_total": drama_info.get('chapters', len(chapter_list)),
                "drama_cover": drama_info.get('drama_cover', ''),
                "drama_description": drama_info.get('drama_description', ''),
                "episodes": chapter_list,
            }
        })
    except Exception as e:
        return error_response(500, f"MeloShort detail error: {e}")


@meloshort_bp.route('/stream', methods=['GET'])
def stream():
    drama_id = request.args.get('drama_id') or request.args.get('id') or request.args.get('dramaId')
    chapter_id = request.args.get('chapter_id') or request.args.get('ep') or request.args.get('episodeId')

    if not drama_id or not chapter_id:
        return error_response(400, "Missing 'drama_id' and/or 'chapter_id' parameters")

    url = f"{MELOSHORT_BASE}/v1/noval/drama/chapter/detail?drama_id={drama_id}&chapter_id={chapter_id}&auto_pay=1&lang=in"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        data = r.json().get('data', {})

        play_url = format_video_url(data.get('play_url'))
        play_url_720p = format_video_url(data.get('play_url_720p'))

        # app-shape videos[{quality,url}]
        videos = []
        if play_url_720p:
            videos.append({"quality": "720p", "url": play_url_720p})
        if play_url:
            videos.append({"quality": "480p", "url": play_url})

        # app-shape subtitles[{language,url,format}]
        subtitles = []
        for sub in data.get('sublist', []) or []:
            su = format_video_url(sub.get('url') or sub.get('subtitle'))
            if su:
                subtitles.append({
                    "language": sub.get('language') or sub.get('lang') or '',
                    "url": su,
                    "format": sub.get('format') or sub.get('type') or 'srt',
                })

        return json_response({
            "type": "stream",
            "data": {
                # ── app (SonzaiXBox) shape ──
                "episode_id": data.get('chapter_id'),
                "videos": videos,
                "subtitles": subtitles,
                # ── raw fields ──
                "drama_id": data.get('drama_id'),
                "drama_title": data.get('drama_title'),
                "chapter_id": data.get('chapter_id'),
                "chapter_index": data.get('chapter_index'),
                "chapter_name": data.get('chapter_name'),
                "chapters_total": data.get('chapters'),
                "video_url": play_url_720p or play_url,
                "video_url_sd": play_url,
            }
        })
    except Exception as e:
        return error_response(500, f"MeloShort stream error: {e}")
