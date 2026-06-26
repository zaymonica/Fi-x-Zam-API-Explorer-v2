"""
routes/netshort.py - NetShort Short Drama API
Encryption reverse engineered from NetShort APK v2.2.0

Flow:
- Request: Generate 32-char random string as AES key → AES/ECB encrypt body →
  Base64 encode AES key → RSA encrypt with server public key → set as encrypt-key header
- Response: RSA decrypt encrypt-key header with client private key →
  Base64 decode → get AES key → AES/ECB decrypt body
"""
import os
import json
import time
import base64
import string
import random
import hashlib
import urllib.parse
import requests as http_requests
from flask import Blueprint, request
from utils import json_response, error_response
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

netshort_bp = Blueprint('netshort', __name__, url_prefix='/netshort')

API_AUTHOR = "Sonzai X シ"
API_CONTACT = "https://t.me/November2k"

NETSHORT_BASE = "https://appsecapi.netshort.com/prod-app-api"

# Optional override; otherwise we self-register a visitor session.
NETSHORT_AUTH_OVERRIDE = os.getenv("NETSHORT_TOKEN", "").strip()

# Used inside the /auth/login body. The Android client sends Build values; we
# imitate a stable Samsung A15 5G handset because that produced a working JWT
# during reverse-engineering.
NETSHORT_DEVICE_MODEL = "SM-A156E"
NETSHORT_OS_NAME = "Android"
NETSHORT_OS_VER = "12"
NETSHORT_APP_VER = "2.2.0"

# RSA Public Key (for encrypting request AES key)
RSA_PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2poXMstZ8NCWE7915MXzDWC5/t+oB2waGfskPqSZwLqxd4ZBR0H1cb1tAZRZcV7P+LmOd6SYNxhnELaWuKTD+D3xkz8Tt1L5j/ynGqVt1MDbiQIEzXQKUkNDSH6T0A+Xzo/67/8QOQXlVJfW06resbaeNvibfx6Qc78j96bCIPlxPrtieilVTBHUFOXjirxK/ki/mO8P2smRbpt73fsQWdGmTGMfYGvfPApGyxbxLkL/qrBjU25XpM8a0MBqzFWUAchHmqSBJ6Mbfam1SSgf3b2U28s67nOW+JiOrhd6iVLcsLFxXA54HX+Zbej3AbOB6jKaEmp/bz1amneE1NYXwwIDAQAB"

# RSA Private Key (for decrypting response AES key)
RSA_PRIVATE_KEY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCK0Tl1pd7bjTRU93bWoHW1hLCDj2+9bg1MgY8j5C7xXaw6bJfToXhWbH1fXNbnFFVqxyYNErcuOUwJZxyDgcxUXM4yWnRseb2GF97GOicAQ2keDzVYmwky4lrSRwvcXutJRLPUCRQNfc6upfk2G5TKh6/CcP4TV1eXTF7+vdEw2SHxAOITKbSfcaZXr/hVs6a1aRHsBF+7RG99ebwZIP6/AgIyqX9RbDVN6ixi1v2G3/bwAULHLSqGdSaqij/ca17fbFGITaeCeEaZ6d/P4ZuOK+PEPdbPQt6SbY4lZaYwRvdrpH73kigPITgDzIDONFybJ1m7wRKlq1wxWHwbimptAgMBAAECggEAPz3cYJXFtt5YphDrahJGLgEabYVOUc2ub1li/eX54OpdCWzpqneYnD7myyg/m5zu4SuDUVdibsOZuXrpSZw7m3+ATP5apgS8bDe5vTNHC16qqBAjrI9NHIp09/F4HNh9dq6/Am10XkUfgP+KTrU4DyDL2NijV+pltD8N1B5kDE1igokVcsavhnu2INoMRXYE78Wq6urNECuFWw9hldv81M9m2w56t1CQOUukpo4mfmLjZRe2s+kwtcBVefGHP8Cj0OeH2dGltjl2YSQMRBFUCVoixYpOrcjIHoqzWri8IfUZ2tW+nUvHl5IZ9RVxefnFaLGnxiXd2sk6Sn4aD/l9YQKBgQDVv3HaOZxHRqlNSPrNGqplGhE066HnDsq6MlPukiovxE43CRBmpTnk9zDCqrDh9t2HbJuao7nSq5WlBERWgwqXU/qDpH43W7Y/lJfHkDv6A2m0viJa0a9x8+CJpNnCDu1ATo4/IQKwoXYice6JKnUyXgkGKn+HipiN6tO0EtWHlQKBgQCmQfklKFtXtm/FZ6NIMs+d+EyvaE5xNLKGYQxmiCR10WGYd8ZV+K0Q6qXHS+a32TirWB9F3TqPOklTytMrfPZB3BCXj4weEldb8W716G8FYf7LLhaT+MdpF7KDcruObwoQAvKV3N4eX6tUEMmdrx9hpCmmIU5EeXUkhGdmwk7BeQKBgAIXMkThJV8pGMTRvuo8pYgBnkN3PoklAuSZU2rU8Sawc9dj9k4atZtAs7BjvQEoyffmHwt/KHUgCoGnrgdulq7uOlgJRtbBxeGPUYC5L2z9lY4YAfwDawThTsPp4dtdDAMCAbAqYX1axu4FUUD0MltAwjPWPJMVzvIsZs+vE3mVAoGAJPja3OaCmZjadj2709xoyypic0dw2j/ry3JdfZec9A5h87P/CTNJ2U81GoLIhe3qakAohDLUSPGfSOD74NnjMXYswmeLs0xE3Q9tq4XK2pmWPby8DJ/wSHCapByplN0gkbr2E1mQk5SW1xT8oPJGukH1eRpC+3s/D6XaEMH5HZECgYEAigoX5l39LDsCgeaUcI4S9grkaas/WsKv37eqo3oD9Qk6VFiMM5L5Zig6aXJxuAPLVjb38caJRPmPmOXLT2kEP1E1h6OJOhEhETwVIUtcBzsK25ju9LqL89bC+W0uS7BPvk6Tcws/tXHCkQCTgb9jVXceZ2ox+6axvlW/5WgHt5Q="


def _random_string(length=32):
    """Generate random alphanumeric string like cn.hutool.core.util.RandomUtil.randomString(32)"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def _encrypt_request(body: dict) -> tuple:
    """Encrypt request body. Returns (encrypted_body, encrypt_key_header)"""
    # Generate 32-char random AES key string
    aes_key_str = _random_string(32)
    aes_key_bytes = aes_key_str.encode('utf-8')
    
    # AES/ECB encrypt the JSON body
    plaintext = json.dumps(body, separators=(',', ':')).encode('utf-8')
    cipher = AES.new(aes_key_bytes, AES.MODE_ECB)
    encrypted_body = base64.b64encode(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')
    
    # Base64 encode the AES key string, then RSA encrypt with public key
    aes_key_b64 = base64.b64encode(aes_key_str.encode('utf-8')).decode('utf-8')
    
    pub_key = RSA.import_key(base64.b64decode(RSA_PUBLIC_KEY))
    rsa_cipher = PKCS1_v1_5.new(pub_key)
    encrypted_key = base64.b64encode(rsa_cipher.encrypt(aes_key_b64.encode('utf-8'))).decode('utf-8')
    
    return encrypted_body, encrypted_key


def _decrypt_response(encrypted_body: str, encrypt_key_header: str) -> str:
    """Decrypt response body using encrypt-key from response header."""
    # RSA decrypt the encrypt-key header with private key
    priv_key = RSA.import_key(base64.b64decode(RSA_PRIVATE_KEY))
    rsa_cipher = PKCS1_v1_5.new(priv_key)
    encrypted_key_bytes = base64.b64decode(encrypt_key_header)
    aes_key_b64 = rsa_cipher.decrypt(encrypted_key_bytes, sentinel=None)
    
    if not aes_key_b64:
        raise ValueError("RSA decrypt failed")
    
    # Base64 decode to get AES key string
    aes_key_str = base64.b64decode(aes_key_b64).decode('utf-8')
    aes_key_bytes = aes_key_str.encode('utf-8')
    
    # AES/ECB decrypt the body
    encrypted_data = base64.b64decode(encrypted_body)
    cipher = AES.new(aes_key_bytes, AES.MODE_ECB)
    decrypted = unpad(cipher.decrypt(encrypted_data), AES.block_size)
    
    return decrypted.decode('utf-8')


def _get_headers(encrypt_key: str, *, with_auth: bool = True) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 12; SM-A156E Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/110.0.5481.154 Mobile Safari/537.36',
        'Content-Type': 'application/json',
        'canary': 'v2',
        'os': '1',
        'version': NETSHORT_APP_VER,
        'versioncode': '0',
        'network': 'wifi,cold,true',
        'device-code': _SESSION.device_code,
        'encrypt-key': encrypt_key,
        'timestamp': str(int(time.time() * 1000)),
        'content-language': 'id_ID',
    }
    if with_auth:
        headers['authorization'] = _SESSION.bearer()
    return headers


def _do_request(endpoint: str, body: dict, *, with_auth: bool = True, _retried: bool = False) -> dict:
    """Encrypt request, send, decrypt response. Auto-refresh token on 401."""
    if with_auth:
        _SESSION.ensure_token()

    enc_body, enc_key = _encrypt_request(body)
    headers = _get_headers(enc_key, with_auth=with_auth)

    r = http_requests.post(
        NETSHORT_BASE + endpoint,
        data=enc_body,
        headers=headers,
        timeout=20
    )

    body_text = r.text.strip()
    resp_encrypt_key = r.headers.get('encrypt-key', '')

    parsed = None
    if body_text.startswith('{'):
        try:
            parsed = json.loads(body_text)
        except Exception:
            parsed = {"code": 500, "msg": "Invalid JSON", "data": None, "raw": body_text[:200]}
    elif resp_encrypt_key:
        try:
            parsed = json.loads(_decrypt_response(body_text, resp_encrypt_key))
        except Exception as e:
            parsed = {"code": 500, "msg": f"Decrypt failed: {str(e)}", "data": None}
    else:
        parsed = {"code": 500, "msg": "No encrypt-key in response", "data": None}

    # Refresh token transparently on the first 401, then retry once.
    if (with_auth and not _retried and isinstance(parsed, dict)
            and parsed.get("code") in (401, 403)):
        if _SESSION.refresh():
            return _do_request(endpoint, body, with_auth=with_auth, _retried=True)

    return parsed


class _NetShortSession:
    """Lazy holder for the visitor JWT and stable device-code."""

    def __init__(self):
        self._lock = __import__('threading').Lock()
        # 16-hex ANDROID_ID style. Stable per process.
        self.device_code = ''.join(
            random.choice(string.hexdigits.lower()[:16]) for _ in range(16))
        self.token = NETSHORT_AUTH_OVERRIDE  # may be empty

    def bearer(self) -> str:
        return f"Bearer {self.token}" if self.token else "Bearer"

    def ensure_token(self) -> None:
        if self.token:
            return
        with self._lock:
            if self.token:
                return
            self._login()

    def refresh(self) -> bool:
        with self._lock:
            return self._login()

    # ── private ──
    def _login(self) -> bool:
        body = {
            "deviceCode": self.device_code,
            "model": NETSHORT_DEVICE_MODEL,
            "os": NETSHORT_OS_NAME,
            "osVer": NETSHORT_OS_VER,
            "appVer": NETSHORT_APP_VER,
            "source": "visitor",
        }
        try:
            res = _do_request('/auth/login', body, with_auth=False, _retried=True)
        except Exception as e:
            return False
        token = ((res or {}).get('data') or {}).get('token')
        if token:
            self.token = token
            return True
        return False


_SESSION = _NetShortSession()


# ═══════════════════════════════════════════════════════════════════════
#  Normalization → app (SonzaiXBox) shape
#
#  The app expects list endpoints to return data: [{ "books": [<MeloloBook>] }]
#  and detail to return drama_id / drama_name / thumb_url / episode_count(int) /
#  description / tags / video_list[{episode, episode_id, cover, isLocked}].
#  NetShort upstream wraps short-play items in many container shapes
#  (dataList / shortPlayList / searchCodeSearchResult / ranking buckets) with
#  cover under episodeCover|shortPlayCover. These helpers flatten any of them.
# ═══════════════════════════════════════════════════════════════════════
def _ns_norm_book(b):
    labels = b.get("labelArray") or b.get("labelNameList") or b.get("labelNames") or []
    flat = []
    for t in labels:
        if isinstance(t, dict):
            n = t.get("labelName") or t.get("name")
            if n:
                flat.append(n)
        elif t:
            flat.append(str(t))
    return {
        "drama_id": str(b.get("shortPlayId") or b.get("id") or ""),
        "drama_name": (b.get("shortPlayName") or "").replace("<em>", "").replace("</em>", ""),
        "description": b.get("shotIntroduce") or "",
        "episode_count": str(b.get("totalEpisode") or 0),
        "watch_value": str(b.get("popularityValue") or b.get("rankingValue") or ""),
        "is_new_book": "0",
        "language": b.get("language") or "id",
        "thumb_url": b.get("episodeCover") or b.get("shortPlayCover") or "",
        "tags": flat,
    }


def _ns_collect(node, seen=None):
    """Recursively pull every short-play item (has shortPlayId) from any shape."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        if node.get("shortPlayId") and node.get("shortPlayName"):
            key = str(node.get("shortPlayId"))
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_ns_collect(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_ns_collect(v, seen))
    return out


def _ns_list_resp(type_, raw_data, extra=None):
    books = [_ns_norm_book(b) for b in _ns_collect(raw_data)]
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": [{"books": books}],
    }
    if extra:
        payload.update(extra)
    return json_response(payload)


# ─── ENDPOINTS ──────────────────────────────────────────────────────

@netshort_bp.route('/home', methods=['GET'])
def home():
    """For You / Home Feed"""
    page = int(request.args.get('page', 1))
    limit = 10
    offset = (page - 1) * limit
    try:
        data = _do_request('/video/shortPlay/theater/for-you/load_user_recommend', {
            'offset': offset,
            'limit': limit,
            'reload': True,
            'policyType': 0
        })
        return _ns_list_resp("home", data.get('data', {}), {"page": page})
    except Exception as e:
        return error_response(500, f"NetShort /home error: {e}")


@netshort_bp.route('/new', methods=['GET'])
def new():
    """New Releases"""
    try:
        data = _do_request('/video/shortPlay/ranking/load_all_chart', {})
        new_release = (data.get('data') or {}).get('newRelease', {})
        return _ns_list_resp("new", new_release)
    except Exception as e:
        return error_response(500, f"NetShort /new error: {e}")

@netshort_bp.route('/search', methods=['GET'])
def search():
    """Search dramas by keyword"""
    query = request.args.get('query', '') or request.args.get('q', '')
    page = int(request.args.get('page', 1))
    if not query:
        return error_response(400, "Missing 'query' parameter")
    try:
        data = _do_request('/video/shortPlay/search/searchByKeyword', {
            'searchCode': query,
            'pageNo': page,
            'pageSize': 20,
            'searchFlag': 1
        })
        return _ns_list_resp("search", data.get('data', {}), {"query": query, "page": page})
    except Exception as e:
        return error_response(500, f"NetShort /search error: {e}")


@netshort_bp.route('/populer', methods=['GET'])
def populer():
    """Rankings / Trending"""
    try:
        data = _do_request('/video/shortPlay/ranking/load_all_chart', {})
        return _ns_list_resp("populer", data.get('data', {}))
    except Exception as e:
        return error_response(500, f"NetShort /populer error: {e}")


@netshort_bp.route('/detail', methods=['GET'])
def detail():
    """Drama detail info"""
    drama_id = (request.args.get('id') or request.args.get('shortPlayId')
                or request.args.get('dramaId'))
    if not drama_id:
        return error_response(400, "Missing 'id' (shortPlayId) parameter")
    try:
        data = _do_request('/video/shortPlay/base/detail_info/V2', {
            'shortPlayId': drama_id
        })
        raw = data.get('data') or {}

        labels = raw.get("shortPlayLabelList") or []
        tags = [l.get("labelName") for l in labels if isinstance(l, dict) and l.get("labelName")]

        # app-shape episode list (NetshortEpisode: episode, episode_id, cover, isLocked)
        video_list = []
        for ep in raw.get("shortPlayEpisodeInfos") or []:
            video_list.append({
                "episode": ep.get("episodeNo"),
                "episode_id": str(ep.get("episodeId") or ""),
                "cover": ep.get("episodeCover"),
                "isLocked": bool(ep.get("isLock", 0)),
            })

        merged = {
            # ── app shape ──
            "drama_id": str(raw.get("shortPlayId") or drama_id),
            "drama_name": raw.get("shortPlayName") or "",
            "description": raw.get("shotIntroduce") or "",
            "episode_count": raw.get("totalEpisode") or len(video_list),
            "thumb_url": raw.get("shortPlayCover") or "",
            "tags": tags,
            "video_list": video_list,
        }
        # keep raw fields too (web UI / other consumers)
        merged.update({k: v for k, v in raw.items() if k not in merged})

        return json_response({
            "author": API_AUTHOR,
            "contact": API_CONTACT,
            "type": "detail",
            "data": merged
        })
    except Exception as e:
        return error_response(500, f"NetShort /detail error: {e}")


@netshort_bp.route('/stream', methods=['GET'])
def stream():
    """Episode stream info"""
    drama_id = request.args.get('id') or request.args.get('shortPlayId')
    episode_id = request.args.get('ep') or request.args.get('episodeId')
    episode_no = int(request.args.get('episode_no', 1))

    if not drama_id:
        return error_response(400, "Missing 'id' (shortPlayId) parameter")

    try:
        # Auto-resolve episodeId from episode_no if not provided
        if not episode_id:
            detail = _do_request('/video/shortPlay/base/detail_info/V2', {
                'shortPlayId': drama_id
            })
            episodes = (detail.get('data') or {}).get('shortPlayEpisodeInfos', [])
            if not episodes:
                return error_response(404, "No episodes found for this drama")
            match = next((ep for ep in episodes if ep.get('episodeNo') == episode_no), None)
            if not match:
                return error_response(404, f"Episode {episode_no} not found (total: {len(episodes)})")
            episode_id = match['episodeId']

        data = _do_request('/video/shortPlay/base/episode/detail_info', {
            'shortPlayId': drama_id,
            'episodeId': episode_id,
            'episodeNo': episode_no,
            'episodeType': 1
        })
        return json_response({
            "author": API_AUTHOR,
            "contact": API_CONTACT,
            "type": "stream",
            "data": data.get('data', {})
        })
    except Exception as e:
        return error_response(500, f"NetShort /stream error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /streamv2 — Playback via dramakuy resolver
#
# dramakuy.com hosts a NetShort resolver returning the play info as a CryptoJS
# AES "Salted__" blob (OpenSSL EVP_BytesToKey/MD5, AES-CBC). Decrypted JSON
# carries a direct txvideo.netshort.com mp4 (wrapped behind dramakuy's own
# /api/proxy/video) plus a subtitle URL. Takes shortPlayId + episodeNumber
# directly — no NetShort RSA/AES session needed.
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


def _dramakuy_resolve(short_play_id, episode_number):
    """Call dramakuy NetShort resolver and return decrypted play info JSON."""
    url = f"{DRAMAKUY_BASE}/api/netshort/watch?shortPlayId={short_play_id}&episodeNumber={episode_number}"
    r = http_requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "referer": f"{DRAMAKUY_BASE}/watch/netshort/{short_play_id}/{episode_number}",
    }, timeout=20)
    try:
        body = r.json()
    except Exception:
        return None, f"HTTP {r.status_code}"
    blob = body.get("data")
    if not isinstance(blob, str):
        return None, "unexpected response"
    try:
        decrypted = json.loads(_cryptojs_decrypt(blob, DRAMAKUY_PASSPHRASE).decode("utf-8"))
    except Exception as e:
        return None, f"decrypt failed: {e}"
    if isinstance(decrypted, dict) and decrypted.get("error"):
        return None, decrypted["error"]
    return decrypted, None


def _absolutize_dramakuy_url(u):
    """Unwrap dramakuy's /api/proxy/video?url=<encoded> to the direct CDN URL.
    Also rewrites awscdn.netshort.com → txvideo.netshort.com (more reliable host)."""
    if not u:
        return u
    parsed = urllib.parse.urlparse(u)
    if parsed.path.endswith("/api/proxy/video"):
        inner = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if inner:
            u = urllib.parse.unquote(inner)
    elif u.startswith("/"):
        u = DRAMAKUY_BASE + u
    return u.replace("awscdn.netshort.com", "txvideo.netshort.com")


@netshort_bp.route('/streamv2', methods=['GET'])
def streamv2():
    """Resolve a playable NetShort episode via the dramakuy resolver.

    Params:
      id (shortPlayId, required), ep / episode_no (episode number, default 1).

    Returns a direct txvideo.netshort.com mp4 — plays in any browser/player.
    """
    short_play_id = request.args.get('id') or request.args.get('shortPlayId')
    if not short_play_id:
        return error_response(400, "Missing 'id' (shortPlayId) parameter")

    episode_no = request.args.get('ep') or request.args.get('episode_no') or '1'
    try:
        ep_num = int(episode_no)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    try:
        data, err = _dramakuy_resolve(short_play_id, ep_num)
        if err:
            return error_response(502, f"Resolver error: {err}")

        play_url = _absolutize_dramakuy_url(data.get("videoUrl", ""))
        subtitle_url = _absolutize_dramakuy_url(data.get("subtitleUrl", ""))

        return json_response({
            "author": API_AUTHOR,
            "contact": API_CONTACT,
            "type": "streamv2",
            "data": {
                "short_play_id": short_play_id,
                "episode_no": data.get("episodeNo", ep_num),
                "play_url": play_url,
                "subtitle_url": subtitle_url,
                "streams": [{"url": play_url, "encode": "H264", "format": "mp4"}] if play_url else [],
                "source": "fallback",
            }
        })
    except Exception as e:
        return error_response(500, f"NetShort /streamv2 error: {e}")
