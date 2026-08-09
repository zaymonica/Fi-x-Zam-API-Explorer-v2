"""
routes/dramawave.py — DramaWave Short Drama

Auth (reversed from DramaWave_1.8.50 / HeaderInterceptor.kt + AccountRepository):
  - APP_SECRET = "8IAcbWyCsVhYv82S2eofRqK1DF3nNDAv" (constant in app)
  - Anonymous login: POST /anonymous/login {device_id, device_name:"", sign}
      sign = md5(APP_SECRET + device_id)
    → returns {auth_key, auth_secret}
  - Authorization header for every other call:
      oauth_signature=md5(APP_SECRET + "&" + auth_secret),oauth_token=auth_key,ts=<ms>
  Tokens are minted on demand and cached, so they never go stale.

Search: /search/drama is deprecated server-side (returns empty for everyone).
  The live search the app now uses is /search/suggestion, which returns matching
  dramas with a deep_link carrying the series id (dramawave://.../detail?id=<id>).
"""
from flask import Blueprint, request
import requests
import json
import time
import hashlib
import base64
import uuid
import re
import threading
from utils import json_response
import concurrent.futures
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from config import API_AUTHOR, API_CONTACT

dramawave_bp = Blueprint('dramawave', __name__, url_prefix='/dramawave')

DW_BASE = "https://api.mydramawave.com/dm-api"
APP_SECRET = "8IAcbWyCsVhYv82S2eofRqK1DF3nNDAv"

DW_HEADERS = {
    "User-Agent": "okhttp/4.12.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "country": "ID",
    "timezone": "+7",
    "device-country": "ID",
    "language": "id-ID",
    "device-language": "in-ID",
    "x-device-brand": "Samsung",
    "x-device-product": "pa3q",
    "device-version": "32",
    "x-device-model": "SM-S938U",
    "screen-width": "619",
    "x-device-fingerprint": "Samsung/pa3q/pa3q:12/V417IR/218:user/release-keys",
    "network-type": "wifi",
    "app-name": "com.dramawave.app",
    "app-version": "1.8.50",
    "x-device-manufacturer": "Samsung",
    "screen-height": "1101",
    "is-mainland": "false",
    "mcc-country": "302",
    "device": "android",
}

DW_TAB_KEYS = {
    "new": {"tabKey": "681", "moduleKey": "2010"},
    "populer": {"tabKey": "678", "moduleKey": "1348"},
}


def _md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


# ── Session (anonymous login) ───────────────────────────────────────────
# Cached per-process; refreshed automatically on expiry/auth failure.
_session_lock = threading.Lock()
_session = {"device_id": None, "session_id": None, "auth_key": None, "auth_secret": None}


def _base_headers():
    h = DW_HEADERS.copy()
    if _session["device_id"]:
        h["device-id"] = _session["device_id"]
    if _session["session_id"]:
        h["session-id"] = _session["session_id"]
    return h


def _anonymous_login():
    """Mint a fresh anonymous session. Returns True on success."""
    device_id = uuid.uuid4().hex
    session_id = str(uuid.uuid4())
    h = DW_HEADERS.copy()
    h["device-id"] = device_id
    h["session-id"] = session_id
    h["content-type"] = "application/json"
    body = {"device_id": device_id, "device_name": "", "sign": _md5(APP_SECRET + device_id)}
    try:
        r = requests.post(f"{DW_BASE}/anonymous/login", headers=h, json=body, timeout=10)
        data = (r.json() or {}).get("data") or {}
        key, secret = data.get("auth_key"), data.get("auth_secret")
        if not key or not secret:
            return False
        _session.update({"device_id": device_id, "session_id": session_id,
                         "auth_key": key, "auth_secret": secret})
        return True
    except Exception:
        return False


def _ensure_session():
    if not _session["auth_key"]:
        with _session_lock:
            if not _session["auth_key"]:
                _anonymous_login()
    return bool(_session["auth_key"])


def _auth_header():
    sig = _md5(APP_SECRET + "&" + (_session["auth_secret"] or ""))
    return f"oauth_signature={sig},oauth_token={_session['auth_key']},ts={int(time.time() * 1000)}"


def _request(method, path, body=None, _retry=True):
    if not _ensure_session():
        return {"error": "Failed to obtain DramaWave session"}
    headers = _base_headers()
    headers["Authorization"] = _auth_header()
    headers["content-type"] = "application/json; charset=UTF-8" if method == "POST" else "application/json"
    url = f"{DW_BASE}/{path}"
    try:
        if method == "POST":
            r = requests.post(url, headers=headers, json=body, timeout=10)
        else:
            r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        # Re-mint session once on auth rejection, then retry.
        if _retry and isinstance(data, dict) and data.get("code") in (401, 403):
            with _session_lock:
                _anonymous_login()
            return _request(method, path, body, _retry=False)
        return data
    except Exception as e:
        return {"error": str(e)}


def dw_get(path):
    return _request("GET", path)


def dw_post(path, body):
    return _request("POST", path, body)


# ── Normalization → Fi x Zam app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. DramaWave
# nests a "series" object inside feed items. Each series has
# key/title/cover/desc/series_tag/episode_count.
def _dw_norm_series(s):
    tags = s.get("series_tag") or s.get("content_tags") or s.get("tag") or []
    if isinstance(tags, str):
        tags = [tags]
    flat = [str(t) for t in tags if t]
    return {
        "drama_id": str(s.get("key") or s.get("series_id") or s.get("id") or ""),
        "drama_name": s.get("title") or s.get("name") or "",
        "description": s.get("desc") or "",
        "episode_count": str(s.get("episode_count") or 0),
        "watch_value": str(s.get("view_count") or s.get("follow_count") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": s.get("cover") or "",
        "tags": flat,
    }


def _dw_collect(node, seen=None):
    """Pull every DramaWave series object (key/title/cover) from any feed shape."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        if node.get("title") and node.get("cover") and (node.get("key") or node.get("series_id")):
            key = str(node.get("key") or node.get("series_id"))
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_dw_collect(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_dw_collect(v, seen))
    return out


def _dw_list_resp(raw_body):
    raw = raw_body.get("data") if isinstance(raw_body, dict) else raw_body
    books = [_dw_norm_series(s) for s in _dw_collect(raw)]
    return json_response({
        "author": API_AUTHOR,
        "contact":API_CONTACT,
        "data": [{"books": books}],
    })


@dramawave_bp.route('/home', methods=['GET'])
def get_home():
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)

    offset = (page - 1) * 10
    body = {
        "next": f"offset={offset}&page_size=10",
        "module_id": 1593,
    }
    return _dw_list_resp(dw_post("home/module/feed", body))

@dramawave_bp.route('/search', methods=['GET'])
def search_drama():
    keyword = request.args.get('q', request.args.get('search', ''))
    if not keyword:
        return json_response({"error": "Provide search query, e.g. ?q=cinta"}, 400)

    # /search/drama is deprecated server-side (always empty); /search/suggestion
    # is the live search the app uses. It returns matching dramas with the series
    # id embedded in a deep_link (dramawave://dramawave.app/detail?id=<id>).
    raw = dw_post("search/suggestion", {"keyword": keyword, "next": ""})
    if not isinstance(raw, dict) or raw.get("code") != 200:
        return json_response(raw)

    items = (raw.get("data") or {}).get("items") or []
    books = []
    for it in items:
        deep_link = it.get("deep_link", "")
        m = re.search(r'[?&]id=([A-Za-z0-9]+)', deep_link)
        books.append({
            "drama_id": m.group(1) if m else "",
            "drama_name": it.get("keyword") or "",
            "description": "",
            "episode_count": "0",
            "watch_value": str(it.get("weight") or ""),
            "is_new_book": "0",
            "language": "id",
            "thumb_url": it.get("cover") or "",
            "tags": [],
        })

    return json_response({
        "author": API_AUTHOR,
        "contact":API_CONTACT,
        "data": [{"books": books}],
    })

@dramawave_bp.route('/new', methods=['GET'])
def get_new():
    return handle_tab('new')

@dramawave_bp.route('/populer', methods=['GET'])
def get_populer():
    return handle_tab('populer')

def handle_tab(tab_name):
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)
    tab_info = DW_TAB_KEYS[tab_name]
    tabKey = tab_info["tabKey"]
    moduleKey = tab_info["moduleKey"]
    
    if page == 1:
        return _dw_list_resp(dw_get(f"homepage/v2/tab/index?tab_key={tabKey}&position_index=10001"))

    offset = (page - 2) * 10
    next_str = f"last_quality=0&offset={offset}&position_index=10001&timestamp=" if tab_name == "new" else f"offset={offset}&position_index=10001"

    body = {
        "next": next_str,
        "module_key": moduleKey,
    }
    return _dw_list_resp(dw_post("homepage/v2/tab/feed", body))

@dramawave_bp.route('/detail', methods=['GET'])
def get_detail():
    dramaId = request.args.get('id', request.args.get('dramaId', ''))
    if not dramaId:
        return json_response({"error": "Provide id or dramaId"}, 400)
        
    with concurrent.futures.ThreadPoolExecutor() as executor:
        f1 = executor.submit(dw_get, f"drama/info_v2?series_id={dramaId}")
        f2 = executor.submit(dw_get, f"drama/price?series_id={dramaId}")
        infoRes = f1.result()
        priceRes = f2.result()
        
    if infoRes.get('code') != 200 or not infoRes.get('data', {}).get('info'):
        return json_response(infoRes)
        
    info = infoRes['data']['info']
    
    episode_list = info.get('episode_list')
    if priceRes.get('code') == 200 and priceRes.get('data', {}).get('episode_list'):
        episode_list = priceRes['data']['episode_list']
        
    result = {
        "code": 200,
        "message": "success",
        "data": {
            "info": {
                "id": info.get("id"),
                "name": info.get("name"),
                "desc": info.get("desc"),
                "tag": info.get("tag"),
                "content_tags": info.get("content_tags"),
                "cover": info.get("cover"),
                "episode_count": info.get("episode_count"),
                "view_count": info.get("view_count"),
                "follow_count": info.get("follow_count"),
                "comment_count": info.get("comment_count"),
                "episode_price": info.get("episode_price"),
                "pay_mode": info.get("pay_mode"),
                "hot_score": info.get("hot_score"),
                "performers": info.get("performers"),
                "original_audio_language": info.get("original_audio_language"),
                "episode_list": episode_list,
            }
        }
    }
    return json_response(result)

@dramawave_bp.route('/stream', methods=['GET'])
def get_stream():
    dramaId = request.args.get('dramaId', request.args.get('id', ''))
    if not dramaId:
        return json_response({"error": "Provide dramaId"}, 400)
    
    episode = request.args.get('episode', request.args.get('ep', None), type=int)
    
    # Use native DramaWave API to get episode list with video URLs
    info_data = dw_get(f"drama/info_v2?series_id={dramaId}")
    
    if info_data.get('code') != 200 or not info_data.get('data', {}).get('info'):
        return json_response(info_data, 400)
    
    info = info_data['data']['info']
    episode_list = info.get('episode_list', [])
    
    if not episode_list:
        return json_response({"error": "No episodes found"}, 404)
    
    if episode is not None:
        # Find specific episode by index
        ep_data = None
        for ep in episode_list:
            if ep.get('index') == episode:
                ep_data = ep
                break
        
        if not ep_data:
            idx = episode - 1
            if 0 <= idx < len(episode_list):
                ep_data = episode_list[idx]
        
        if not ep_data:
            return json_response({"error": f"Episode {episode} not found"}, 404)
        
        # Build stream response
        return json_response({
            "code": 200,
            "message": "success",
            "data": {
                "drama_id": dramaId,
                "drama_name": info.get("name", ""),
                "episode": episode,
                "episode_id": ep_data.get("id", ""),
                "duration": ep_data.get("duration", 0),
                "cover": ep_data.get("cover", ""),
                "h264_m3u8": ep_data.get("external_audio_h264_m3u8", ""),
                "h265_m3u8": ep_data.get("external_audio_h265_m3u8", ""),
                "video_url": ep_data.get("video_url", ""),
                "m3u8_url": ep_data.get("m3u8_url", ""),
                "subtitle_list": ep_data.get("subtitle_list", []),
                "unlock": ep_data.get("unlock", False),
                "video_type": ep_data.get("video_type", ""),
            }
        })
    
    # No episode specified — return all episodes with stream URLs
    episodes = []
    for ep in episode_list:
        episodes.append({
            "episode": ep.get("index", 0),
            "episode_id": ep.get("id", ""),
            "duration": ep.get("duration", 0),
            "h264_m3u8": ep.get("external_audio_h264_m3u8", ""),
            "h265_m3u8": ep.get("external_audio_h265_m3u8", ""),
            "unlock": ep.get("unlock", False),
            "video_type": ep.get("video_type", ""),
        })
    
    return json_response({
        "code": 200,
        "message": "success",
        "data": {
            "drama_id": dramaId,
            "drama_name": info.get("name", ""),
            "episode_count": info.get("episode_count", len(episodes)),
            "episodes": episodes,
        }
    })


# ═══════════════════════════════════════════════════════════════════════
#  /streamv2 — Playback via dramakuy resolver
#
# dramakuy.com hosts a DramaWave resolver returning the play info as a CryptoJS
# AES "Salted__" blob (OpenSSL EVP_BytesToKey/MD5, AES-CBC). Decrypted JSON
# carries a direct video-v6.mydramawave.com HLS (.m3u8) plus subtitle_list.
# Takes dramaId + ep directly — no DramaWave oauth session needed, no cookie.
# ═══════════════════════════════════════════════════════════════════════
DRAMAKUY_BASE = "https://dramakuy.com"
DRAMAKUY_PASSPHRASE = b"DracinBox-SecureKey2026"


def _cryptojs_decrypt(b64_blob, passphrase=DRAMAKUY_PASSPHRASE):
    """Decrypt a CryptoJS AES 'Salted__' blob (OpenSSL EVP_BytesToKey/MD5)."""
    raw = base64.b64decode(b64_blob)
    if raw[:8] != b"Salted__":
        raise ValueError("not a CryptoJS salted blob")
    salt = raw[8:16]
    ct = raw[16:]
    d = b""
    prev = b""
    while len(d) < 48:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        d += prev
    key, iv = d[:32], d[32:48]
    return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ct), 16)


def _dramakuy_resolve(drama_id, ep, lang="in"):
    """Call dramakuy DramaWave resolver and return decrypted play info JSON.
    Upstream is flaky and intermittently returns "Failed to fetch episode",
    so retry a few times before giving up."""
    url = f"{DRAMAKUY_BASE}/api/dramawave/episode?dramaId={drama_id}&ep={ep}&lang={lang}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "referer": f"{DRAMAKUY_BASE}/watch/dramawave/{drama_id}/{ep}",
        "accept": "*/*",
    }
    last_err = "unknown"
    for attempt in range(6):
        r = None
        try:
            r = requests.get(url, headers=headers, timeout=20)
            body = r.json()
        except Exception:
            last_err = f"HTTP {r.status_code}" if r is not None else "request failed"
            time.sleep(1)
            continue
        blob = body.get("data")
        if not isinstance(blob, str):
            last_err = "unexpected response"
            time.sleep(1)
            continue
        try:
            decrypted = json.loads(_cryptojs_decrypt(blob).decode("utf-8"))
        except Exception as e:
            return None, f"decrypt failed: {e}"
        if isinstance(decrypted, dict) and decrypted.get("error"):
            last_err = decrypted["error"]
            time.sleep(1)
            continue
        return decrypted, None
    return None, last_err


@dramawave_bp.route('/streamv2', methods=['GET'])
def streamv2():
    """Resolve a playable DramaWave episode via the dramakuy resolver.

    Params:
      id / dramaId (required), ep / episode (episode number, default 1),
      lang (subtitle/audio language, default 'in').

    Returns a direct video-v6.mydramawave.com HLS (.m3u8) + subtitle list.
    """
    drama_id = request.args.get('id') or request.args.get('dramaId')
    if not drama_id:
        return json_response({"error": "Missing 'id' (dramaId) parameter"}, 400)

    episode_no = request.args.get('ep') or request.args.get('episode') or '1'
    try:
        ep_num = int(episode_no)
    except ValueError:
        return json_response({"error": "Invalid episode number (ep)"}, 400)

    lang = request.args.get('lang', 'in')

    data, err = _dramakuy_resolve(drama_id, ep_num, lang)
    if err:
        return json_response({"error": "Stream temporarily unavailable"}, 502)

    hls_url = data.get("hls_url", "")
    return json_response({
        "code": 200,
        "message": "success",
        "type": "streamv2",
        "data": {
            "drama_id": drama_id,
            "episode": data.get("chapter_num", ep_num),
            "hls_url": hls_url,
            "play_url": hls_url,
            "subtitle_list": data.get("subtitle_list", []),
            "streams": [{"url": hls_url, "encode": "H264", "format": "m3u8"}] if hls_url else []
        }
    })
