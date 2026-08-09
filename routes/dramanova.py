"""
routes/dramanova.py — DramaNova Short Drama API

Reverse-engineered from DramaNova v1.3.07 (com.udrama.ruiqilin).
Native API: https://mobapp.yfeitrade.com/api/

Headers and behaviour modelled on a captured real-device request:
    GET /api/playlet/drama/{id}?language=in
    clientid: 8aaa2824912e16e799e82203b89668df
    authorization: Bearer <jwt>
    x-app-version: 307
    x-app-package: com.udrama.ruiqilin
    x-app-tenantid: 417850
    x-channel: google
    x-device-id: <16-hex>           (Android ANDROID_ID style)
    x-device-model: Samsung+SM-A156E
    x-os-version: 12
    x-time-zone: Asia/Jakarta
    x-trace-id: <uuid>
    x-client-time: <unix_ms>
    x-platform: android
    x-language: in
    x-country: US
    x-media-source: Google
    user-agent: okhttp/4.12.0

Auth flow (mirrors DramaStartService.java):
  1. Generate guest username = device_id (16-hex, ANDROID_ID style).
  2. POST /auth/register with body=AES(json), header encrypt-key=RSA(aesKey_b64).
  3. POST /auth/login -> returns access_token / refresh_token.
  4. Subsequent calls add Authorization: Bearer <token> + clientid.

Encryption (EncryptUtil.java):
  - aes_key_b64 = base64(first16(uuid_no_dash))
  - body cipher = AES/ECB/PKCS5Padding, key = base64decode(aes_key_b64)
  - encrypt-key header = base64( RSA/ECB/PKCS1Padding(aes_key_b64) )

Optional env overrides:
  DRAMANOVA_TOKEN   - bypass register/login and use this Bearer token directly.
  DRAMANOVA_DEVICE  - pin a specific 16-hex device id (otherwise random per process).
"""
from flask import Blueprint, request
import requests
import json
import time
import uuid
import base64
import os
import threading
import logging
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad
from utils import json_response
from config import API_AUTHOR, API_CONTACT

dramanova_bp = Blueprint('dramanova', __name__, url_prefix='/dramanova')
log = logging.getLogger("dramanova")

# ── Constants (DramaConstant.java) ─────────────────────────────────
DN_BASE_URL = "https://mobapp.yfeitrade.com/api/"
DN_CLIENT_ID = "8aaa2824912e16e799e82203b89668df"
DN_TENANT_ID = "417850"
DN_GRANT_TYPE = "password"
DN_USER_TYPE = "app_user"

DN_APP_VERSION = "307"        # matches v1.3.07
DN_APP_PACKAGE = "com.udrama.ruiqilin"
DN_CHANNEL = "google"
DN_PLATFORM = "android"
DN_DEVICE_MODEL = "Samsung+SM-A156E"
DN_OS_VERSION = "12"
DN_TIME_ZONE = "Asia/Jakarta"
DN_COUNTRY = "ID"
DN_MEDIA_SOURCE = "Google"
DN_DEFAULT_LANGUAGE = "in"     # short ISO code as the app sends ("in" for Indonesian)
DN_DEFAULT_VARIANT = "googleplay"

# VolcEngine / BytePlus VOD endpoint used to redeem the PlayAuthToken.
DN_VOD_HOST = "https://vod.byteplusapi.com"

# RSA public key (X.509 SubjectPublicKeyInfo, RSA-2048).
DN_PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyOMWanUbtO4VLaB9wf8G"
    "T4SqgkqPmHDoa+IYs3Ik2uAvfBWpUkxeqOVQARuSQ0rYZ/ZhWkF0pcf4OsO1Ue1d"
    "68555cEMO/kCFhJkgQ45IXEwRdsEDBPNipwlCZH1ePbQpIGW3PEFONDc41QUcoAM"
    "YsFI/YCQ8t8+1qDk2yPuh/3BNnPJUJj3B8j/KX/gJEj5dNF9OiFc6wi4XqAb7OVf"
    "pcvSq3YbxkBGxaj3mNmO+30Y4uf8cxDc/vHAeAqcvpQDdACyjSaH22uZLCLNUWnP"
    "xgVfIUah+lbvYzPDsgPXollx00RbrVYAWDCC+lbUQUI3eyzqUuoVIOABiXU8uvJm"
    "PQIDAQAB"
)
_DN_PUBLIC_KEY = RSA.import_key(base64.b64decode(DN_PUBLIC_KEY_B64))
_DN_RSA_CIPHER = PKCS1_v1_5.new(_DN_PUBLIC_KEY)

# Override knobs.
_ENV_TOKEN = os.getenv("DRAMANOVA_TOKEN", "").strip()
_ENV_DEVICE = os.getenv("DRAMANOVA_DEVICE", "").strip()


# ── Crypto helpers ─────────────────────────────────────────────────
def _generate_aes_key():
    """Return base64-encoded AES key (16 ASCII bytes from a UUID hex prefix)."""
    raw = uuid.uuid4().hex[:16].encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _encrypt_aes(plaintext, aes_key_b64):
    """AES/ECB/PKCS5Padding, base64-decoded key, returns base64 ciphertext."""
    key = base64.b64decode(aes_key_b64)
    cipher = AES.new(key, AES.MODE_ECB)
    ct = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(ct).decode("ascii")


def _encrypt_rsa(aes_key_b64):
    """RSA/ECB/PKCS1Padding of the AES key string with the public key."""
    ct = _DN_RSA_CIPHER.encrypt(aes_key_b64.encode("utf-8"))
    return base64.b64encode(ct).decode("ascii")


# ── Header builder ─────────────────────────────────────────────────
def _common_headers(language, device_id, *, with_auth=False, token=None):
    """Build the full x-* header set used by the real Android client."""
    now_ms = str(int(time.time() * 1000))
    headers = {
        "User-Agent": "okhttp/4.12.0",
        "Accept-Encoding": "gzip",
        "x-app-version": DN_APP_VERSION,
        "x-app-package": DN_APP_PACKAGE,
        "x-app-tenantid": DN_TENANT_ID,
        "x-channel": DN_CHANNEL,
        "x-device-id": device_id,
        "x-device-model": DN_DEVICE_MODEL,
        "x-os-version": DN_OS_VERSION,
        "x-time-zone": DN_TIME_ZONE,
        "x-trace-id": str(uuid.uuid4()),
        "x-client-time": now_ms,
        "x-platform": DN_PLATFORM,
        "x-language": language,
        "x-country": DN_COUNTRY,
        "x-media-source": DN_MEDIA_SOURCE,
        "content-language": language,
        "clientid": DN_CLIENT_ID,
    }
    if with_auth and token:
        headers["authorization"] = f"Bearer {token}"
    return headers


# ── Session manager ────────────────────────────────────────────────
class _DramaNovaSession:
    """Holds device_id + JWT, refreshing automatically on 401."""

    def __init__(self):
        self._lock = threading.Lock()
        # ANDROID_ID style: 16 lowercase hex chars (matches captured x-device-id).
        self.device_id = (_ENV_DEVICE or uuid.uuid4().hex[:16]).lower()
        self.token = _ENV_TOKEN or None
        self.refresh_token = None
        self.expires_at = float("inf") if _ENV_TOKEN else 0.0
        self.user_id = None

    # ── auth primitives ──
    def _post_encrypted(self, path, payload, language=DN_DEFAULT_LANGUAGE):
        aes_key = _generate_aes_key()
        body_cipher = _encrypt_aes(json.dumps(payload, separators=(",", ":")), aes_key)
        encrypt_key = _encrypt_rsa(aes_key)
        headers = _common_headers(language, self.device_id)
        headers["encrypt-key"] = encrypt_key
        headers["Content-Type"] = "text/plain; charset=UTF-8"
        url = DN_BASE_URL + path
        r = requests.post(url, headers=headers,
                          data=body_cipher.encode("utf-8"), timeout=15)
        try:
            return r.json()
        except Exception:
            log.warning("non-JSON %s response (%s): %s", path, r.status_code, r.text[:200])
            return {"code": r.status_code, "msg": r.text[:300]}

    def _register(self):
        return self._post_encrypted("auth/register", {
            "username": self.device_id,
            "password": self.device_id,
            "grantType": DN_GRANT_TYPE,
            "clientId": DN_CLIENT_ID,
            "tenantId": DN_TENANT_ID,
            "userType": DN_USER_TYPE,
        })

    def _login(self):
        return self._post_encrypted("auth/login", {
            "clientId": DN_CLIENT_ID,
            "grantType": DN_GRANT_TYPE,
            "tenantId": DN_TENANT_ID,
            "username": self.device_id,
            "password": self.device_id,
        })

    def _ensure_login(self, force=False):
        if _ENV_TOKEN and not force:
            self.token = _ENV_TOKEN
            return
        with self._lock:
            now = time.time()
            if (not force) and self.token and now < (self.expires_at - 30):
                return
            log.info("DramaNova login (force=%s, device_id=%s)", force, self.device_id)
            res = self._login()
            data = res.get("data") if isinstance(res, dict) else None
            if not data or not data.get("access_token"):
                # First run for this device → register, then login again.
                reg = self._register()
                log.info("DramaNova register: code=%s msg=%s",
                         (reg or {}).get("code"), (reg or {}).get("msg"))
                res = self._login()
                data = res.get("data") if isinstance(res, dict) else None
            if not data or not data.get("access_token"):
                raise RuntimeError(f"DramaNova login failed: {res}")
            self.token = data["access_token"]
            self.refresh_token = data.get("refresh_token")
            self.expires_at = now + float(data.get("expires_in") or 3600)
            self.user_id = data.get("openid")

    # ── authed transports ──
    def authed_get(self, path, params=None, language=None):
        self._ensure_login()
        lang = language or DN_DEFAULT_LANGUAGE
        url = DN_BASE_URL + path
        headers = _common_headers(lang, self.device_id, with_auth=True, token=self.token)
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code in (401, 403):
            self._ensure_login(force=True)
            headers = _common_headers(lang, self.device_id, with_auth=True, token=self.token)
            r = requests.get(url, headers=headers, params=params, timeout=15)
        try:
            return r.json()
        except Exception:
            return {"code": r.status_code, "msg": r.text[:300]}


_session = _DramaNovaSession()


# ── VolcEngine VOD resolver ────────────────────────────────────────
def _resolve_play_info(file_id, language=DN_DEFAULT_LANGUAGE):
    """Fetch a PlayAuthToken for `file_id` then call VolcEngine GetPlayInfo.

    Returns a tuple (raw_token_payload, play_info_json). Raises on hard errors.
    """
    tok_res = _session.authed_get(f"playlet/drama/pat/{file_id}", language=language)
    if not (isinstance(tok_res, dict) and tok_res.get("code") == 200):
        raise RuntimeError(f"PlayAuthToken request failed: {tok_res}")
    tok = ((tok_res.get("data") or {}).get("token")) or ""
    if not tok:
        raise RuntimeError(f"PlayAuthToken empty: {tok_res}")

    # Token is base64( {"GetPlayInfoToken":"<signed-query>","TokenVersion":"V2"} ).
    decoded = json.loads(base64.b64decode(tok + "==").decode("utf-8"))
    play_qs = decoded.get("GetPlayInfoToken")
    if not play_qs:
        raise RuntimeError(f"GetPlayInfoToken missing: {decoded}")

    url = DN_VOD_HOST + "/?" + play_qs
    r = requests.get(url, timeout=15, headers={"User-Agent": "okhttp/4.12.0"})
    try:
        play_info = r.json()
    except Exception:
        raise RuntimeError(f"GetPlayInfo non-JSON: {r.text[:300]}")
    return tok, play_info


def _flatten_play_info(play_info):
    """Reduce VolcEngine's response to our public shape."""
    result = (play_info or {}).get("Result") or {}
    items = result.get("PlayInfoList") or []
    qualities = []
    for it in items:
        qualities.append({
            "definition": it.get("Definition"),
            "format": it.get("Format"),
            "codec": it.get("Codec"),
            "width": it.get("Width"),
            "height": it.get("Height"),
            "bitrate": it.get("Bitrate"),
            "size": it.get("Size"),
            "duration": it.get("Duration"),
            "main_url": it.get("MainPlayUrl"),
            "backup_url": it.get("BackupPlayUrl"),
            "expires_at": it.get("MainUrlExpire"),
        })

    def _score(q):
        try:
            d = (q.get("definition") or "").rstrip("pP")
            return int(d) if d.isdigit() else 0
        except Exception:
            return 0
    def _https(u):
        if isinstance(u, str) and u.startswith("http://"):
            return "https://" + u[7:]
        return u

    qualities.sort(key=_score, reverse=True)
    for q in qualities:
        q["main_url"] = _https(q.get("main_url") or "")
        q["backup_url"] = _https(q.get("backup_url") or "")
    best = qualities[0] if qualities else None
    return {
        "vid": result.get("Vid"),
        "duration": result.get("Duration"),
        "poster": _https(result.get("PosterUrl") or ""),
        "video_url": _https((best or {}).get("main_url") or ""),
        "backup_url": _https((best or {}).get("backup_url") or ""),
        "definition": (best or {}).get("definition"),
        "qualities": qualities,
    }


# ── Frontend-friendly shaping ──────────────────────────────────────
def _ok(payload):
    return {"code": 200, "message": "success", "data": payload}


def _shape_drama_list_item(item):
    if not isinstance(item, dict):
        return item
    return {
        "drama_id": item.get("dramaId") or item.get("id"),
        "title": item.get("title") or item.get("name"),
        "description": item.get("description") or item.get("synopsis"),
        "synopsis": item.get("synopsis"),
        "poster": item.get("posterImgUrl") or item.get("posterImg"),
        "banner": item.get("bannerImgUrl") or item.get("bannerImg"),
        "total_episodes": item.get("totalEpisodes"),
        "is_completed": item.get("isCompleted"),
        "view_count": item.get("viewCount"),
        "like_count": item.get("likeCount"),
        "favorite_count": item.get("favoriteCount"),
        "categories": item.get("categories"),
        "language": item.get("defaultLanguage"),
        "source_provider": item.get("sourceProvider"),
        "published_at": item.get("publishedAt"),
        "raw": item,
    }


# ── Normalization → Fi x Zam app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. DramaNova
# items come in two field styles: raw (dramaId/posterImg/totalEpisodes) and
# shaped (drama_id/poster/total_episodes). _dn_book handles both.
def _dn_book(b):
    cats = b.get("categories") or b.get("categoryNames") or []
    if isinstance(cats, str):
        cats = [cats]
    flat = []
    for c in cats:
        if isinstance(c, dict):
            n = c.get("name") or c.get("title")
            if n:
                flat.append(n)
        elif c:
            flat.append(str(c))
    return {
        "drama_id": str(b.get("drama_id") or b.get("dramaId") or b.get("id") or ""),
        "drama_name": b.get("title") or b.get("name") or "",
        "description": b.get("description") or b.get("synopsis") or "",
        "episode_count": str(b.get("total_episodes") or b.get("totalEpisodes") or 0),
        "watch_value": str(b.get("view_count") or b.get("viewCount") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": (b.get("poster") or b.get("posterImg") or b.get("posterImgUrl")
                      or b.get("coverImage") or b.get("coverImageUrl")
                      or b.get("banner") or ""),
        "tags": flat,
    }


def _dn_collect(node, seen=None):
    """Pull every DramaNova drama item (has a drama id + title) from any shape."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        did = node.get("drama_id") or node.get("dramaId") or node.get("id")
        if did and (node.get("title") or node.get("name")):
            key = str(did)
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_dn_collect(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_dn_collect(v, seen))
    return out


def _dn_books_resp(raw_body):
    raw = raw_body.get("data") if isinstance(raw_body, dict) else raw_body
    books = [_dn_book(b) for b in _dn_collect(raw)]
    return json_response({
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "data": [{"books": books}],
    })


def _shape_episode(ep):
    if not isinstance(ep, dict):
        return ep
    videos = ep.get("videos") or []
    pick = None
    for v in videos:
        if isinstance(v, dict) and v.get("url"):
            if pick is None or (v.get("resolution") or "") > (pick.get("resolution") or ""):
                pick = v
    return {
        "episode_id": ep.get("id"),
        "episode_number": ep.get("episodeNumber"),
        "title": ep.get("episodeTitle"),
        "thumbnail": ep.get("thumbnailImg"),
        "duration": (pick or {}).get("duration"),
        "preview_duration": ep.get("previewDuration"),
        "view_count": ep.get("viewCount"),
        "like_count": ep.get("likeCount"),
        "lock_status": ep.get("lockStatus"),
        "status": ep.get("status"),
        "file_id": ep.get("fileId"),
        "video_url": (pick or {}).get("url"),
        "resolution": (pick or {}).get("resolution"),
        "videos": videos,
        "subtitle_tracks": ep.get("subtitleTracks"),
    }


# Unicode ranges for scripts that should NOT appear in an Indonesian title.
_NON_LATIN_RANGES = (
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0900, 0x097F),  # Devanagari (Hindi)
    (0x0980, 0x09FF),  # Bengali
    (0x0E00, 0x0E7F),  # Thai
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xFF00, 0xFFEF),  # Halfwidth/fullwidth
)


def _looks_indonesian(text):
    """Return True if `text` is empty or uses Latin-friendly script.

    DramaNova falls back to Hindi/Chinese when an Indonesian translation is
    missing. Detect that via the unicode ranges above and drop those items.
    """
    if not text:
        return True
    for ch in text:
        cp = ord(ch)
        for lo, hi in _NON_LATIN_RANGES:
            if lo <= cp <= hi:
                return False
    return True


def _filter_id_items(items):
    """Drop drama dicts whose `title` is not in an Indonesian-friendly script."""
    out = []
    for it in items or []:
        title = (it or {}).get("title") or (it or {}).get("name")
        if _looks_indonesian(title):
            out.append(it)
    return out


# ── Routes ─────────────────────────────────────────────────────────
@dramanova_bp.route("/home", methods=["GET"])
def home():
    """Home feed for the app — uses the discovery feed (clean drama items)."""
    page_size = request.args.get("size", 20, type=int)
    res = _session.authed_get("playlet/drama/discovery", params={
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "pageSize": page_size,
        "sp": 5,
    })
    rows = res.get("data") if isinstance(res, dict) else None
    if isinstance(rows, list):
        rows = _filter_id_items(rows)
    return _dn_books_resp(rows)


@dramanova_bp.route("/populer", methods=["GET"])
def populer():
    """Trending — paged recommended drama list."""
    page = request.args.get("page", 1, type=int)
    res = _session.authed_get("v2/home/more-recommend", params={
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "sourceProvider": 0,
        "attrSource": 1,
        "pageNum": page,
        "pageSize": 20,
    })
    rows = _filter_id_items(res.get("rows") or []) if isinstance(res, dict) else []
    return _dn_books_resp(rows)


@dramanova_bp.route("/new", methods=["GET"])
def new():
    """Newest — drama query sorted desc."""
    page = request.args.get("page", 1, type=int)
    res = _session.authed_get("playlet/drama/query", params={
        "pageNum": page,
        "pageSize": 20,
        "language": DN_DEFAULT_LANGUAGE,
        "isAsc": "desc",
    })
    rows = res.get("rows") if isinstance(res, dict) else None
    if isinstance(rows, list):
        rows = _filter_id_items(rows)
    return _dn_books_resp(rows)


@dramanova_bp.route("/home-raw", methods=["GET"])
def home_raw():
    """v2/home/index — homepage rails (banners + recommended modules)."""
    page = request.args.get("page", 1, type=int)
    attr_source = request.args.get("attrSource", 1, type=int)
    sp = request.args.get("sourceProvider", 0, type=int)

    params = {
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "attrSource": attr_source,
        "sourceProvider": sp,
    }
    if page > 1:
        params["pageNum"] = page
        params["pageSize"] = 20
    res = _session.authed_get("v2/home/index", params=params)

    if isinstance(res, dict) and res.get("code") == 200 and isinstance(res.get("data"), dict):
        d = res["data"]
        for key in ("heroModule", "recommendModule", "hotModule", "newModule",
                    "discoverModule", "completeModule", "editorModule"):
            if isinstance(d.get(key), list):
                d[key] = _filter_id_items(d[key])
    return json_response(res)


@dramanova_bp.route("/discovery", methods=["GET"])
def discovery():
    """playlet/drama/discovery — random/trending feed."""
    page_size = request.args.get("size", 10, type=int)
    res = _session.authed_get("playlet/drama/discovery", params={
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "pageSize": page_size,
        "sp": 5,
    })

    if isinstance(res, dict) and res.get("code") == 200:
        rows = res.get("data") or []
        if isinstance(rows, list):
            rows = _filter_id_items(rows)
            return json_response(_ok({
                "items": [_shape_drama_list_item(r) for r in rows],
                "count": len(rows),
            }))
    return json_response(res)


@dramanova_bp.route("/recommend", methods=["GET"])
def recommend():
    """v2/home/more-recommend — paged recommended drama list."""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("size", 10, type=int)

    res = _session.authed_get("v2/home/more-recommend", params={
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "sourceProvider": 0,
        "attrSource": 1,
        "pageNum": page,
        "pageSize": page_size,
    })

    if isinstance(res, dict) and res.get("code") == 200:
        rows = _filter_id_items(res.get("rows") or [])
        return json_response(_ok({
            "page": page,
            "page_size": page_size,
            "total": res.get("total"),
            "items": [_shape_drama_list_item(r) for r in rows],
        }))
    return json_response(res)


@dramanova_bp.route("/search", methods=["GET"])
def search():
    """playlet/drama/query — search drama by title (app-shape books)."""
    keyword = request.args.get("q", request.args.get("title", "")).strip()
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("size", 20, type=int)

    params = {
        "pageNum": page,
        "pageSize": page_size,
        "language": DN_DEFAULT_LANGUAGE,
        "isAsc": "desc",
    }
    if keyword:
        params["title"] = keyword
    category = request.args.get("category")
    if category:
        params["categoryId"] = category

    res = _session.authed_get("playlet/drama/query", params=params)
    rows = _filter_id_items(res.get("rows") or []) if isinstance(res, dict) else []
    return _dn_books_resp(rows)


@dramanova_bp.route("/list", methods=["GET"])
def drama_list():
    """playlet/drama/query — raw shaped list (other consumers)."""
    keyword = request.args.get("q", request.args.get("title", "")).strip()
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("size", 10, type=int)

    params = {
        "pageNum": page,
        "pageSize": page_size,
        "language": DN_DEFAULT_LANGUAGE,
        "isAsc": "desc",
    }
    if keyword:
        params["title"] = keyword
    category = request.args.get("category")
    if category:
        params["categoryId"] = category

    res = _session.authed_get("playlet/drama/query", params=params)

    if isinstance(res, dict) and res.get("code") == 200:
        rows = _filter_id_items(res.get("rows") or [])
        return json_response(_ok({
            "query": keyword,
            "page": page,
            "page_size": page_size,
            "total": res.get("total"),
            "items": [_shape_drama_list_item(r) for r in rows],
        }))
    return json_response(res)


@dramanova_bp.route("/detail", methods=["GET"])
def detail():
    """playlet/drama/{id} — full drama metadata + episode list."""
    drama_id = request.args.get("id", request.args.get("dramaId", "")).strip()
    if not drama_id:
        return json_response({"error": "Provide id or dramaId"}, 400)

    res = _session.authed_get(f"playlet/drama/{drama_id}",
                              params={"language": DN_DEFAULT_LANGUAGE})

    if isinstance(res, dict) and res.get("code") == 200:
        d = res.get("data") or {}
        episodes = [_shape_episode(e) for e in (d.get("episodes") or [])]
        info = _shape_drama_list_item(d)
        cats = info.get("categories") or []
        if isinstance(cats, str):
            cats = [cats]
        tags = [c.get("name") if isinstance(c, dict) else str(c) for c in cats]
        tags = [t for t in tags if t]
        video_list = [{
            "episode": e.get("episode_number"),
            "episode_id": str(e.get("episode_id") or ""),
            "cover": e.get("thumbnail"),
            "isLocked": str(e.get("lock_status") or "0") not in ("0", "None", ""),
        } for e in episodes]
        return json_response(_ok({
            # app shape
            "drama_id": str(info.get("drama_id") or drama_id),
            "drama_name": info.get("title") or "",
            "description": info.get("description") or info.get("synopsis") or "",
            "episode_count": len(episodes),
            "thumb_url": info.get("poster") or info.get("banner") or "",
            "tags": tags,
            "video_list": video_list,
            # raw
            "info": info,
            "monetization": d.get("monetization"),
            "episodes": episodes,
        }))
    return json_response(res)


@dramanova_bp.route("/stream", methods=["GET"])
def stream():
    """Return episode info plus a playable URL (or info for all episodes).

    Without `episode` -> episode list (no resolution); with `episode=N` ->
    single episode resolved through VolcEngine VOD into a usable mp4 URL.
    """
    drama_id = request.args.get("id", request.args.get("dramaId", "")).strip()
    if not drama_id:
        return json_response({"error": "Provide id or dramaId"}, 400)

    episode = request.args.get("episode", request.args.get("ep"))

    res = _session.authed_get(f"playlet/drama/{drama_id}",
                              params={"language": DN_DEFAULT_LANGUAGE})
    if not (isinstance(res, dict) and res.get("code") == 200):
        return json_response(res, 400)

    d = res.get("data") or {}
    raw_eps = d.get("episodes") or []
    eps = [_shape_episode(e) for e in raw_eps]

    if episode is None:
        return json_response(_ok({
            "drama_id": drama_id,
            "drama_name": d.get("title"),
            "episode_count": len(eps),
            "episodes": eps,
        }))

    try:
        ep_num = int(episode)
    except (TypeError, ValueError):
        return json_response({"error": "episode must be an integer"}, 400)

    pick = None
    for ep in eps:
        if ep.get("episode_number") == ep_num:
            pick = ep
            break
    if pick is None and 1 <= ep_num <= len(eps):
        pick = eps[ep_num - 1]
    if pick is None:
        return json_response({"error": f"Episode {ep_num} not found"}, 404)

    file_id = pick.get("file_id")
    play = None
    if file_id:
        try:
            _, play_info = _resolve_play_info(file_id)
            play = _flatten_play_info(play_info)
        except Exception as e:
            log.warning("resolve_play_info(%s) failed: %s", file_id, e)
            play = {"error": str(e)}

    return json_response(_ok({
        "drama_id": drama_id,
        "drama_name": d.get("title"),
        "episode": ep_num,
        "info": pick,
        "play": play,
    }))


@dramanova_bp.route("/play", methods=["GET"])
def play():
    """Resolve a fileId or (drama_id, episode) directly to playable URLs."""
    file_id = request.args.get("fileId", request.args.get("vid", "")).strip()

    if not file_id:
        drama_id = request.args.get("id", request.args.get("dramaId", "")).strip()
        episode = request.args.get("episode", request.args.get("ep"))
        if not drama_id or episode is None:
            return json_response({
                "error": "Provide fileId or (id + episode)"
            }, 400)
        try:
            ep_num = int(episode)
        except (TypeError, ValueError):
            return json_response({"error": "episode must be an integer"}, 400)
        d = _session.authed_get(f"playlet/drama/{drama_id}",
                                params={"language": DN_DEFAULT_LANGUAGE})
        if not (isinstance(d, dict) and d.get("code") == 200):
            return json_response(d, 400)
        raw_eps = (d.get("data") or {}).get("episodes") or []
        if not (1 <= ep_num <= len(raw_eps)):
            return json_response({"error": f"Episode {ep_num} not found"}, 404)
        file_id = (raw_eps[ep_num - 1] or {}).get("fileId")
        if not file_id:
            return json_response({"error": "Episode has no fileId"}, 404)

    try:
        _, play_info = _resolve_play_info(file_id)
    except Exception as e:
        log.exception("resolve_play_info failed")
        return json_response({"error": str(e)}, 502)

    return json_response(_ok({
        "file_id": file_id,
        **_flatten_play_info(play_info),
    }))


@dramanova_bp.route("/categories", methods=["GET"])
def categories():
    """recommend/homeModules — surface category modules used by the home page."""
    res = _session.authed_get("recommend/homeModules", params={
        "language": DN_DEFAULT_LANGUAGE,
        "variant": DN_DEFAULT_VARIANT,
        "sourceProvider": 0,
    })
    return json_response(res)


@dramanova_bp.route("/health", methods=["GET"])
def health():
    """Diagnostic — confirms the SDK auth handshake works."""
    try:
        _session._ensure_login()
        return json_response({
            "code": 200,
            "message": "ok",
            "data": {
                "device_id": _session.device_id,
                "openid": _session.user_id,
                "token_present": bool(_session.token),
                "expires_in": (
                    int(_session.expires_at - time.time())
                    if _session.expires_at != float("inf") else None
                ),
                "env_token_used": bool(_ENV_TOKEN),
            },
        })
    except Exception as e:
        log.exception("dramanova health failed")
        return json_response({"code": 500, "message": str(e)}, 500)
