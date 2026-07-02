"""
routes/flickreels.py — FlickReels Short Drama API
Signature reverse-engineered from FlickReels v2.2.6.1 APK (SignUtil + BasicParamsInterceptor)
"""
import hashlib
import hmac
import json
import random
import string
import time
import requests
from flask import Blueprint, request
from utils import error_response, json_response
from config import API_AUTHOR, API_CONTACT

flickreels_bp = Blueprint('flickreels', __name__, url_prefix='/flickreels')

# ── Constants ────────────────────────────────────────────────────
FLICKREELS_API = "https://api.farsunpteltd.com"
HMAC_SECRET = "tsM5SnqFayhX7c2HfRxm"
DEVICE_KEY = "MyaRfZW5RgafSyC"
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJfIiwiYXVkIjoiXyIsImlhdCI6MTc3ODA0NzQxNywiZGF0YSI6eyJtZW1iZXJfaWQiOjUzODIyNjM3LCJwYWNrYWdlX2lkIjoiMiIsIm1haW5fcGFja2FnZV9pZCI6MTAwfX0.X9xU-cOXYXCJjoAR6B5TquWCoCrn5K5HWarGhQR_Xc8"
DEVICE_ID = "8d96071e92644c05"
GOOGLE_AD_ID = "ccd3aa81-5be0-44ab-9ad3-65ab8b15d3ea"
APPSFLYER_UID = "1778047414632-724674290094277846"

# Navigation IDs per category
NAV_HOME = "405"
NAV_NEW = "78"

# ── Signature Engine ─────────────────────────────────────────────

def _gen_nonce(n=32):
    """Generate random nonce (SignUtil.c)."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def _sort_body(body_str):
    """Sort JSON body keys via TreeMap and flatten (SignUtil.d)."""
    if not body_str or body_str == "{}":
        return hashlib.md5("".encode()).hexdigest()
    data = json.loads(body_str)
    parts = []
    for key in sorted(data.keys()):
        val = data[key]
        if val is None:
            continue
        if isinstance(val, (list, dict)):
            val_str = json.dumps(val, separators=(',', ':'), ensure_ascii=False)
        elif isinstance(val, bool):
            val_str = "true" if val else "false"
        else:
            val_str = str(val)
        parts.append(f"{key}_{val_str}")
    return "_".join(parts)


def _md5(s):
    """MD5 hex digest (MD5.c)."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _hmac_sha256(data, key):
    """HMAC-SHA256 hex digest (SignUtil.e)."""
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def _gen_sign(body_str, timestamp, nonce):
    """Generate request sign header (SignUtil.f)."""
    sorted_body = _sort_body(body_str)
    md5_body = _md5(sorted_body)
    sign_data = f"{sorted_body}_{timestamp}_{nonce}_{md5_body}"
    return _hmac_sha256(sign_data, HMAC_SECRET)


def _gen_device_sign(timestamp):
    """Generate device_sign field (BasicParamsInterceptor)."""
    return _hmac_sha256(f"{DEVICE_ID}_{DEVICE_KEY}_{timestamp}", DEVICE_KEY)


def _common_body(timestamp):
    """Build common body fields injected by BasicParamsInterceptor."""
    return {
        "main_package_id": 100,
        "googleAdId": GOOGLE_AD_ID,
        "device_id": DEVICE_ID,
        "device_sign": _gen_device_sign(timestamp),
        "apps_flyer_uid": APPSFLYER_UID,
        "os": "android",
        "device_brand": "Samsung",
        "device_number": "12",
        "device_model": "SM-A156E",
        "language_id": "6",
        "isA": True, "isB": True, "isC": False,
        "isD": True, "isE": False, "isF": False,
        "countryCode": "ID",
    }


def _api_post(path, extra_body):
    """Make a signed POST request to FlickReels API."""
    ts = str(int(time.time()))
    nonce = _gen_nonce()
    body = {**extra_body, **_common_body(ts)}
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    sign = _gen_sign(body_str, ts, nonce)

    headers = {
        "User-Agent": "MyUserAgent",
        "Accept-Encoding": "gzip",
        "version": "2.2.6.1",
        "sign": sign,
        "timestamp": ts,
        "nonce": nonce,
        "token": TOKEN,
        "cache-control": "no-cache",
        "content-type": "application/json; charset=UTF-8",
    }

    r = requests.post(f"{FLICKREELS_API}{path}", headers=headers, data=body_str, timeout=15)
    return r


# ── Helper: clean drama item ────────────────────────────────────

def _clean_drama(item):
    """Normalize a drama/playlet item from various response formats."""
    pid = item.get("playlet_id") or item.get("id") or ""
    tags = []
    # hotRank format
    if "tag_name" in item and isinstance(item["tag_name"], list):
        tags = item["tag_name"]
    # other formats
    elif "tag_list" in item:
        for t in item.get("tag_list", []):
            tags.append(t.get("tag_name") or t.get("name", ""))
    elif "tag_list_with_id" in item:
        for t in item.get("tag_list_with_id", []):
            tags.append(t.get("name", ""))

    return {
        "drama_id": str(pid),
        "drama_name": item.get("title") or item.get("name") or "",
        "cover": item.get("cover") or item.get("cover_square") or "",
        "description": item.get("introduce") or "",
        "episode_count": item.get("upload_num") or 0,
        "tags": [t for t in tags if t],
    }


# ── Normalization → SonzaiXBox app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }] with fields
# drama_id / drama_name / thumb_url / episode_count(str) / description / tags.
def _to_book(cleaned):
    return {
        "drama_id": cleaned.get("drama_id", ""),
        "drama_name": cleaned.get("drama_name", ""),
        "description": cleaned.get("description", ""),
        "episode_count": str(cleaned.get("episode_count") or 0),
        "watch_value": str(cleaned.get("hot_num") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": cleaned.get("cover", ""),
        "tags": cleaned.get("tags", []),
    }


def _books_resp(type_, dramas, extra=None):
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": [{"books": [_to_book(d) for d in dramas]}],
    }
    if extra:
        payload.update(extra)
    return json_response(payload)


# ── Routes ───────────────────────────────────────────────────────

@flickreels_bp.route('/home', methods=['GET'])
def home():
    page = int(request.args.get('page', '1'))

    try:
        if page == 1:
            r = _api_post("/app/playlet/navigationColumn", {
                "is_exp": 1, "navigation_id": NAV_HOME,
                "page": 1, "page_size": 20,
            })
        else:
            r = _api_post("/app/playlet/lastColumn", {
                "column_config_id": "10716", "is_exp": 1,
                "navigation_id": NAV_HOME, "page": page, "page_size": 20,
            })

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        dramas = []
        resp_data = data.get("data", [])
        if isinstance(resp_data, list):
            for section in resp_data:
                for item in section.get("list", []):
                    dramas.append(_clean_drama(item))

        return _books_resp("home", dramas, {"page": page})
    except Exception as e:
        return error_response(500, str(e))


@flickreels_bp.route('/new', methods=['GET'])
def new():
    page = int(request.args.get('page', '1'))

    try:
        if page == 1:
            r = _api_post("/app/playlet/navigationColumn", {
                "is_exp": 0, "navigation_id": NAV_NEW,
                "page": 1, "page_size": 20,
            })
        else:
            r = _api_post("/app/playlet/lastColumn", {
                "column_config_id": "6230", "is_exp": 0,
                "navigation_id": NAV_NEW, "page": page, "page_size": 20,
            })

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        dramas = []
        resp_data = data.get("data", [])
        if isinstance(resp_data, list):
            for section in resp_data:
                for item in section.get("list", []):
                    dramas.append(_clean_drama(item))

        return _books_resp("new", dramas, {"page": page})
    except Exception as e:
        return error_response(500, str(e))


@flickreels_bp.route('/populer', methods=['GET'])
def populer():
    try:
        r = _api_post("/app/playlet/hotRank", {})

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        categories = []
        for cat in data.get("data", []):
            items = []
            for item in cat.get("data", []):
                drama = _clean_drama(item)
                drama["hot_num"] = item.get("hot_num", "")
                drama["rank"] = item.get("rank_order", 0)
                items.append(drama)
            categories.append({
                "category": cat.get("name", ""),
                "rank_type": cat.get("rank_type", 0),
                "dramas": items,
            })

        # Flatten all ranked dramas into the app's [{books:[...]}] shape.
        flat = []
        seen = set()
        for cat in categories:
            for d in cat["dramas"]:
                if d["drama_id"] not in seen:
                    seen.add(d["drama_id"])
                    flat.append(d)
        return _books_resp("populer", flat)
    except Exception as e:
        return error_response(500, str(e))


@flickreels_bp.route('/search', methods=['GET'])
def search():
    keyword = request.args.get('q', request.args.get('keyword', ''))
    if not keyword:
        return error_response(400, "Query Missing (q)")

    try:
        r = _api_post("/app/user_search/search", {
            "is_mid_page": 0, "keyword": keyword,
        })

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        dramas = []
        resp_data = data.get("data", {})
        items = resp_data.get("list", []) if isinstance(resp_data, dict) else resp_data
        for item in items:
            dramas.append(_clean_drama(item))

        return _books_resp("search", dramas, {"keyword": keyword})
    except Exception as e:
        return error_response(500, str(e))


@flickreels_bp.route('/detail', methods=['GET'])
def detail():
    playlet_id = request.args.get('id', '')
    if not playlet_id:
        return error_response(400, "Playlet ID Missing (id)")

    try:
        r = _api_post("/app/playlet/chapterList", {
            "auto_unlock": False, "chapter_type": -1,
            "fragmentPosition": 0, "playlet_id": str(playlet_id),
            "show_type": 0, "source": 4,
            "vip_btn_scene": '{"scene_type":[1,3],"play_type":1,"collection_status":0}',
        })

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        d = data.get("data", {})
        episodes = []
        for ep in d.get("list", []):
            episodes.append({
                "episode": ep.get("chapter_num"),
                "chapter_id": ep.get("chapter_id"),
                "title": ep.get("chapter_title", ""),
                "cover": ep.get("chapter_cover", ""),
                "duration": ep.get("duration", 0),
                "is_locked": ep.get("is_lock", 0) == 1,
                "is_free": ep.get("is_need_pay", 0) == 0,
                "hls_url": ep.get("hls_url", ""),
            })

        tags = []
        for t in d.get("tag_list", []):
            tags.append(t.get("tag_name", ""))

        return json_response({
            "type": "detail",
            "data": {
                "drama_id": d.get("playlet_id", playlet_id),
                "drama_name": d.get("title", ""),
                "cover": d.get("cover", ""),
                "episode_count": len(episodes),
                "episodes": episodes,
                "tags": [t for t in tags if t],
            },
        })
    except Exception as e:
        return error_response(500, str(e))


@flickreels_bp.route('/stream', methods=['GET'])
def stream():
    playlet_id = request.args.get('id', '')
    ep = request.args.get('ep', '1')

    if not playlet_id:
        return error_response(400, "Playlet ID Missing (id)")

    try:
        ep_num = int(ep)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    try:
        # First get chapter list to find the chapter_id for the episode
        r = _api_post("/app/playlet/chapterList", {
            "auto_unlock": False, "chapter_type": -1,
            "fragmentPosition": 0, "playlet_id": str(playlet_id),
            "show_type": 0, "source": 4,
            "vip_btn_scene": '{"scene_type":[1,3],"play_type":1,"collection_status":0}',
        })

        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")

        data = r.json()
        if data.get("status_code") != 1:
            return error_response(502, data.get("msg", "Upstream Error"))

        chapters = data.get("data", {}).get("list", [])
        target = None
        for ch in chapters:
            if ch.get("chapter_num") == ep_num:
                target = ch
                break

        if not target:
            return error_response(404, f"Episode {ep_num} not found")

        return json_response({
            "type": "stream",
            "data": {
                "drama_id": playlet_id,
                "drama_name": data.get("data", {}).get("title", ""),
                "episode": ep_num,
                "chapter_id": target.get("chapter_id"),
                "title": target.get("chapter_title", ""),
                "duration": target.get("duration", 0),
                "is_locked": target.get("is_lock", 0) == 1,
                "hls_url": target.get("hls_url", ""),
                "cover": target.get("chapter_cover", ""),
            },
        })
    except Exception as e:
        return error_response(500, str(e))
