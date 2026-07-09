"""
routes/shortmax.py — ShortMax (a.k.a. ShortTV) Short Drama API
Reverse-engineered from ShortMax_2.19.0.apk (package: com.startshorts.androidplayer)

Tech notes (from APK):
  - Base URL    : https://api.shorttv.live  (fallback: https://api.shorttv.app)
  - Auth        : tourist via POST app/login/v4/initLogin
                  body fields: deviceCode, seq, secretKey
                  secretKey   = RSA/ECB/PKCS1Padding(rc4_key, base64) using
                                a hard-coded 1024-bit pubkey (KeyUtil.b())
  - Body crypto : RC4(json_str, rc4_key) → hex string  (hk.d.d)
                  rc4_key  = 32-char [a-z0-9] random (cn.hutool RandomUtil)
  - Response    : { isEncrypt: true, result: "<rc4 hex>" }  →
                  RC4_decrypt(hex, rc4_key) → JSON
  - Whitelist   : login/system endpoints are NOT body-encrypted (header
                  isEncrypt=false). See `_PLAINTEXT_PATHS` below.
  - TraceParam  : login endpoints add MD5(concat_values + androidVersion)
                  then RC4-hex with rc4_key.

Public endpoints (mirroring meloshort/netshort/reelshort):
  GET  /shortmax/home                        — Discover tab home
  GET  /shortmax/new                         — For-You list (latest)
  GET  /shortmax/populer                     — Popular shorts (rankings)
  GET  /shortmax/search?q=...&page=N         — Keyword search
  GET  /shortmax/detail?id=<shortPlayId>     — Drama detail + episode list
  GET  /shortmax/stream?id=<shortPlayId>&episode_no=N
                                             — Play slide for one episode
"""
import base64
import hashlib
import json
import os
import random
import string
import threading
import time
import uuid

import requests as http_requests
from flask import Blueprint, request

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from utils import json_response, error_response
from config import API_AUTHOR, API_CONTACT

shortmax_bp = Blueprint('shortmax', __name__, url_prefix='/shortmax')

# ─── Constants (from APK) ─────────────────────────────────────────────
SHORTMAX_BASE = "https://api.shorttv.live"
SHORTMAX_FALLBACK = "https://api.shorttv.app"

# 1024-bit RSA pubkey, reconstructed from KeyUtil.b() char-list obfuscation.
# (Just the base64 body of an X.509 SubjectPublicKeyInfo blob.)
RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDQN8wJEvdcpklku3uwxLaz67OtP3GpAK2A"
    "HUY/+PWvijPVKBSRCXD6wir+JKJQ7zcx7sEnAxUi/CMzwRn+BmKomIvQpzIUzLuaAxiu5RM0"
    "BAkKWXAxKScsj8nY3vlbChOdw4ICxqrSO3QZMeDxzyNLXKnXm7OFBB/w5xli5zUhDQIDAQAB"
)

# App fingerprint
APP_VERSION = "2.19.0"
APP_VERSION_CODE = "21900"
CHANNEL = "google_play"
CLIENT_PLATFORM = "android"
ENVIRONMENT = "prod"
LANGUAGE = "id"
LOCALE = "id_ID"
TIMEZONE = "Asia/Jakarta"
SYSTEM_COUNTRY = "ID"
DEVICE_MODEL = "SM-A156E"          # Samsung Galaxy A15 5G
ANDROID_VERSION = "14"             # OS marketing version (DeviceUtil.V)
SYSTEM_VERSION = "34"              # SDK int as string (DeviceUtil.O)
RESOLUTION = "1080x2340"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-A156E Build/UP1A.231005.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 "
    "Mobile Safari/537.36"
)

# Endpoints whose body is sent in plaintext (header isEncrypt=false).
_PLAINTEXT_PATHS = {
    "app/login/v3/tripartiteLogin",
    "app/login/loginMobile",
    "app/login/v4/initLogin",
    "app/hiAdMatch/deepLinkReport",
    "app/hiAppReport/lpReport",
    "app/eventController/appEventReportV1",
    "app/correction/time",
    "app/system/getUpgradeVersionManageInfo",
    "config/getSdkDeviceConfig",
    "app/abtest/getAbtestParamsNew",
}

# ─── RC4 (hex variant — matches hk.d.d/c) ─────────────────────────────
def _rc4_ksa(key: bytes):
    s = list(range(256))
    j = 0
    klen = len(key)
    if klen == 0:
        return s
    for i in range(256):
        j = (j + s[i] + key[i % klen]) & 0xff
        s[i], s[j] = s[j], s[i]
    return s

def _rc4_xor(data: bytes, key: bytes) -> bytes:
    s = _rc4_ksa(key)
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xff
        a = s[i]
        j = (j + a) & 0xff
        s[i] = s[j]
        s[j] = a
        out[k] = data[k] ^ s[(s[i] + a) & 0xff]
    return bytes(out)

def rc4_hex_encrypt(plain: str, key: str) -> str:
    """hk.d.d() — RC4 encrypt then char-cast → hex-encode."""
    if plain is None or key is None:
        return ""
    enc = _rc4_xor(plain.encode("utf-8"), key.encode("utf-8"))
    # In Java the bytes are upcast to chars (sign-extension blocked by &0xff
    # in the helper) and then hex-encoded. The helper iterates each char and
    # does Integer.toHexString(c & 0xff). We can replicate by hex-encoding
    # the raw bytes directly because for byte values 0–255 both produce the
    # same lower-case 2-digit hex.
    return enc.hex()

def rc4_hex_decrypt(hex_str: str, key: str) -> str:
    """hk.d.c() — hex decode → RC4 decrypt → bytes-to-string."""
    if hex_str is None or key is None:
        return ""
    raw = bytes.fromhex(hex_str.strip())
    dec = _rc4_xor(raw, key.encode("utf-8"))
    return dec.decode("utf-8", "replace")


# ─── RSA helper (RSAUtil.encryptByPublicKey) ──────────────────────────
def rsa_encrypt_b64(plain: bytes) -> str:
    """RSA/ECB/PKCS1Padding with 117-byte chunks, base64-default flag."""
    pub = RSA.import_key(base64.b64decode(RSA_PUBLIC_KEY_B64))
    cipher = PKCS1_v1_5.new(pub)
    out = bytearray()
    block_max = 117  # 1024/8 - 11
    for i in range(0, len(plain), block_max):
        chunk = plain[i:i + block_max]
        out.extend(cipher.encrypt(chunk))
    # Android Base64.NO_WRAP-equivalent default (no newlines)
    return base64.b64encode(bytes(out)).decode("ascii")


# ─── MD5 (matches hk.c.a) ─────────────────────────────────────────────
def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


# ─── Session ──────────────────────────────────────────────────────────
class _Session:
    """Holds the RC4 key, device id, seq, token. Tourist login on demand."""
    def __init__(self):
        self._lock = threading.Lock()
        self.rc4_key: str = self._rand_alnum(32)
        # 16 hex chars — Android-id-like, stable per process
        self.device_id: str = ''.join(random.choice("0123456789abcdef") for _ in range(16))
        self.seq: str = str(uuid.uuid4())
        self.token: str | None = None
        self.uid: int | None = None
        self.gaid: str = "00000000-0000-0000-0000-000000000000"
        self.session_id: str = uuid.uuid4().hex
        self.first_open_time: int = int(time.time() * 1000)

    @staticmethod
    def _rand_alnum(n: int) -> str:
        # cn.hutool RandomUtil.randomString(n) — alphanumeric (lower+upper+digits)
        # Codepath in NetShort uses lower+digits, but ShortMax uses RandomUtil
        # which is mixed-case alnum. We stick with mixed-case for fidelity.
        chars = string.ascii_letters + string.digits
        return ''.join(random.choice(chars) for _ in range(n))

    def ensure_token(self) -> bool:
        if self.token:
            return True
        with self._lock:
            if self.token:
                return True
            return self._login()

    def refresh(self) -> bool:
        with self._lock:
            self.token = None
            return self._login()

    def _login(self) -> bool:
        secret_key_b64 = rsa_encrypt_b64(self.rc4_key.encode("utf-8"))
        body = {
            "deviceCode": self.device_id,
            "seq": self.seq,
            "secretKey": secret_key_b64,
        }
        try:
            res = _do_raw_request("app/login/v4/initLogin", body)
        except Exception:
            return False
        data = (res or {}).get("data") or {}
        token = data.get("token")
        if token:
            self.token = token
            user = (data.get("userResponse") or {})
            self.uid = user.get("userId") or user.get("uid")
            return True
        return False


_SESSION = _Session()


# ─── HTTP plumbing ────────────────────────────────────────────────────
def _build_headers(path: str, *, encrypt: bool, with_auth: bool) -> dict:
    h = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
        "isEncrypt": "true" if encrypt else "false",
        "channel": CHANNEL,
        "gaid": _SESSION.gaid,
        "deviceId": _SESSION.device_id,
        "clientPlatform": CLIENT_PLATFORM,
        "TraceId": str(uuid.uuid4()),
        "language": LANGUAGE,
        "locale": LOCALE,
        "timeZone": TIMEZONE,
        "model": DEVICE_MODEL,
        "systemVersion": SYSTEM_VERSION,
        "androidVersion": ANDROID_VERSION,
        "mcc": "510",  # Indonesia (best-effort)
        "environment": ENVIRONMENT,
        "buildValue": APP_VERSION_CODE,
        "afVersion": "1",
        "hasProxy": "false",
        "resolution": RESOLUTION,
        "session_id": _SESSION.session_id,
        "system_country_code": SYSTEM_COUNTRY,
        "isR": "false",
        "isE": "false",
        "isD": "false",
        "vefCode": md5_hex(_SESSION.device_id)[:16],
        "version": APP_VERSION,
    }
    if with_auth and _SESSION.token:
        h["Authorization"] = _SESSION.token
    return h


def _form_encode(d: dict) -> str:
    """Mimic OkHttp FormBody (RFC 3986 form-url-encoded, no plus-for-space)."""
    from urllib.parse import quote
    parts = []
    for k, v in d.items():
        if v is None:
            v = ""
        parts.append(f"{quote(str(k), safe='')}={quote(str(v), safe='')}")
    return "&".join(parts)


def _do_raw_request(path: str, body: dict) -> dict:
    """Login-style request: body = JSON map (no RC4), plus TraceParam header."""
    headers = _build_headers(path, encrypt=False, with_auth=False)
    raw_body = json.dumps(body, separators=(',', ':'), ensure_ascii=False)

    # TraceParam = RC4_hex(MD5(concat(values_in_form_order) + androidVersion), rc4_key)
    concat = "".join(str(v) for v in body.values() if str(v))
    trace_md5 = md5_hex(concat + ANDROID_VERSION)
    headers["TraceParam"] = rc4_hex_encrypt(trace_md5, _SESSION.rc4_key)

    return _send(path, raw_body, headers, encrypt=False)


def _do_request(path: str, body: dict | None = None,
                *, with_auth: bool = True, _retried: bool = False) -> dict:
    """Standard request. Auto-handles auth, encryption, 401 retry."""
    if with_auth:
        if not _SESSION.ensure_token():
            return {"status": 401, "message": "Tourist login failed", "data": None}

    body = body or {}
    encrypt = path not in _PLAINTEXT_PATHS
    headers = _build_headers(path, encrypt=encrypt, with_auth=with_auth)

    json_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    if encrypt:
        raw_body = rc4_hex_encrypt(json_str, _SESSION.rc4_key)
    else:
        raw_body = json_str

    res = _send(path, raw_body, headers, encrypt=encrypt)
    # Auto-refresh token on 401/403 then retry once
    if (with_auth and not _retried and isinstance(res, dict)
            and res.get("status") in (401, 403, 1001)):
        if _SESSION.refresh():
            return _do_request(path, body, with_auth=with_auth, _retried=True)
    return res


def _send(path: str, raw_body: str, headers: dict, *, encrypt: bool) -> dict:
    """Low-level HTTP send + response decode. Tries primary then fallback."""
    last_err = None
    for base in (SHORTMAX_BASE, SHORTMAX_FALLBACK):
        url = f"{base}/{path.lstrip('/')}"
        try:
            r = http_requests.post(
                url, data=raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body,
                headers=headers, timeout=20,
            )
            text = r.text
            try:
                obj = r.json()
            except Exception:
                # Server returned a bare encrypted hex blob (rare).
                if encrypt and text:
                    try:
                        return json.loads(rc4_hex_decrypt(text, _SESSION.rc4_key))
                    except Exception as e2:
                        last_err = e2
                        continue
                return {"status": r.status_code, "message": "Invalid JSON",
                        "data": None, "raw": text[:200]}

            # If body is encrypted envelope { isEncrypt:true, result:"<hex>"}
            is_enc = (
                str(obj.get("isEncrypt", "")).lower() == "true"
                or str(r.headers.get("isEncrypt", "")).lower() == "true"
            )
            if is_enc and isinstance(obj.get("result"), str):
                try:
                    decoded = rc4_hex_decrypt(obj["result"], _SESSION.rc4_key)
                    obj = json.loads(decoded)
                except Exception as e:
                    last_err = e
                    continue
            return obj
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All ShortMax endpoints failed: {last_err}")


def _resp(type_: str, data, **extra):
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": data,
    }
    payload.update(extra)
    return json_response(payload)


# ── Normalization → SonzaiXBox app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. ShortMax
# nests shortPlay items inside many containers (tabPageResponse / banner
# lists / forYouList / shortPlays / items). A shortPlay item has
# id|shortPlayId + shortPlayName + picUrl|coverId|horizontalCoverId.
_SHORTMAX_IMG_BASE = "https://volcengine-forward.shorttv.live"


def _sm_cover(b):
    for k in ("picUrl", "coverUrl", "horizontalCover", "cover"):
        v = b.get(k)
        if v and str(v).startswith("http"):
            return v
    # coverId / horizontalCoverId are relative image paths
    for k in ("coverId", "horizontalCoverId", "verticalCoverId"):
        v = b.get(k)
        if v:
            return _SHORTMAX_IMG_BASE + v if str(v).startswith("/") else v
    return ""


def _sm_norm_book(b):
    labels = b.get("labelList") or []
    flat = [l.get("labelName") for l in labels if isinstance(l, dict) and l.get("labelName")]
    return {
        "drama_id": str(b.get("id") or b.get("shortPlayId") or ""),
        "drama_name": b.get("shortPlayName") or b.get("name") or "",
        "description": b.get("summary") or b.get("recommendContent") or "",
        "episode_count": str(b.get("totalEpisodes") or 0),
        "watch_value": str(b.get("playNum") or b.get("collectNum") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": _sm_cover(b),
        "tags": flat,
    }


def _sm_collect(node, seen=None):
    """Pull every ShortMax shortPlay item (shortPlayName + id/shortPlayId)."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        if node.get("shortPlayName") and (node.get("id") or node.get("shortPlayId")):
            key = str(node.get("id") or node.get("shortPlayId"))
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_sm_collect(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_sm_collect(v, seen))
    return out


def _sm_books_resp(type_, raw_data, **extra):
    books = [_sm_norm_book(b) for b in _sm_collect(raw_data)]
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": [{"books": books}],
    }
    payload.update(extra)
    return json_response(payload)


# ═══════════════════════════════════════════════════════════════════════
#  Helper / debug
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/session', methods=['GET'])
def session_state():
    return json_response({
        "rc4_key_len": len(_SESSION.rc4_key),
        "device_id": _SESSION.device_id,
        "seq": _SESSION.seq,
        "token_acquired": bool(_SESSION.token),
        "uid": _SESSION.uid,
    })


@shortmax_bp.route('/login', methods=['GET'])
def force_login():
    ok = _SESSION.refresh()
    return json_response({
        "ok": ok,
        "token_acquired": bool(_SESSION.token),
        "uid": _SESSION.uid,
    })


# ═══════════════════════════════════════════════════════════════════════
#  /home — Discover tab
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/home', methods=['GET'])
def home():
    try:
        body = {
            "newbieShowType": 0,
            "installTime": _SESSION.first_open_time,
            "isCodeStarted": False,
            "experimentKey": "",
            "experimentParam": "",
        }
        data = _do_request("app/homeData/getTabHomeData", body)
        return _sm_books_resp("home", data.get("data") if isinstance(data, dict) else data,
                              status=data.get("status") if isinstance(data, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /home error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /new — Latest waterfall (For-You)
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/new', methods=['GET'])
def new():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        body = {
            "pageNum": page,
            "pageSize": limit,
            "isColdBoot": 1 if page == 1 else 0,
        }
        data = _do_request("app/forYou/getForYouListPageNewV3", body)
        return _sm_books_resp("new", data.get("data") if isinstance(data, dict) else data,
                              page=page,
                              status=data.get("status") if isinstance(data, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /new error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /populer — Trending shorts
#
#  Note: app/hiShortPlay/getPopularShortPlay is only used by the APK for
#  campaign deep-link attribution; on a clean tourist session it returns
#  {"needDecrypt": false}. Real "trending" lives inside the home banner
#  with ruleCode=5 (e.g. "Kamu mungkin suka"), paginated via
#  app/homeData/getBannerMorePage.
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/populer', methods=['GET'])
def populer():
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    banner_id = request.args.get('bannerId')

    try:
        # 1) If caller didn't pin a banner, discover the trending one.
        title = None
        if not banner_id:
            home = _do_request("app/homeData/getTabHomeData", {
                "newbieShowType": 0,
                "installTime": _SESSION.first_open_time,
                "isCodeStarted": False,
                "experimentKey": "",
                "experimentParam": "",
            })
            banners = (((home.get("data") or {}).get("tabPageResponse") or {})
                       .get("bannerResponseList") or [])
            # Prefer ruleCode==5 with the most items, else fall back to largest.
            ranked = sorted(
                (b for b in banners if isinstance(b, dict)),
                key=lambda b: (
                    1 if b.get("ruleCode") == 5 else 0,
                    len(b.get("shortPlayResponseList") or []),
                ),
                reverse=True,
            )
            if ranked:
                banner_id = ranked[0].get("bannerId")
                title = ranked[0].get("title")
        if not banner_id:
            return error_response(502, "No trending banner found in home data")

        # 2) Page through it.
        more = _do_request("app/homeData/getBannerMorePage", {
            "businessId": str(banner_id),
            "scene": "",
            "recommendId": 0,
            "experimentKey": "",
            "experimentParam": "",
            "pageSize": limit,
            "pageNum": page,
            "firstPageSize": limit,
        })
        d = more.get("data") if isinstance(more, dict) else more
        items = []
        if isinstance(d, dict):
            items = d.get("shortPlayResponseList") or []

        return _sm_books_resp("populer", {
            "items": items,
        }, bannerId=banner_id, title=title, page=page, limit=limit,
           status=more.get("status") if isinstance(more, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /populer error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /search — Keyword search
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q') or request.args.get('query') or ''
    if not query:
        return error_response(400, "Missing 'q' parameter")
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    try:
        body = {
            "pageNum": page,
            "pageSize": limit,
            "searchText": query,
            # Defaults pulled from RedeemCodeEquity.Companion in the APK.
            # The interceptor auto-parses these JSON arrays back into List<>.
            "equitySubTypes": [11, 12],
            "conditionCodes": ["earnSingle", "earnByDays"],
        }
        data = _do_request("app/search/searchPageV2", body)
        return _sm_books_resp("search", data.get("data") if isinstance(data, dict) else data,
                              query=query, page=page,
                              status=data.get("status") if isinstance(data, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /search error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /detail — ShortPlay detail + episode list
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/detail', methods=['GET'])
def detail():
    sid = request.args.get('id') or request.args.get('shortPlayId') \
        or request.args.get('businessId')
    if not sid:
        return error_response(400, "Missing 'id' (shortPlayId) parameter")

    try:
        sid_int = int(sid)
    except ValueError:
        return error_response(400, "'id' must be numeric shortPlayId")

    try:
        head = _do_request("app/hiShortPlay/shortPlayDetail", {
            "scene": "",
            "businessId": sid_int,
        })
        ep_list = _do_request("app/hiDrama/dramaListV4", {
            "shortPlayId": sid_int,
            "pageNum": 1,
            "pageSize": int(request.args.get('episode_limit', 100)),
        })

        def _data(x):
            return x.get("data") if isinstance(x, dict) else x

        info = _data(head) or {}
        eps_raw = _data(ep_list) or {}
        ep_items = (eps_raw.get("dramaListResponseList")
                    if isinstance(eps_raw, dict) else eps_raw) or []

        labels = info.get("labelResponseList") or info.get("labelList") or []
        tags = [l.get("labelName") for l in labels if isinstance(l, dict) and l.get("labelName")]

        # app-shape episode list (episode, episode_id, cover, isLocked)
        video_list = []
        for ep in ep_items:
            video_list.append({
                "episode": ep.get("episodeNum"),
                "episode_id": str(ep.get("id") or ""),
                "cover": None,
                "isLocked": ep.get("lock", 0) == 2 or ep.get("alreadyLock", 0) == 1,
            })

        merged = {
            "drama_id": str(info.get("id") or sid_int),
            "drama_name": info.get("shortPlayName") or "",
            "description": info.get("summary") or info.get("recommendContent") or "",
            "episode_count": info.get("totalEpisodes") or len(video_list),
            "thumb_url": _sm_cover(info),
            "tags": tags,
            "video_list": video_list,
            # raw payloads kept for other consumers
            "info": info,
            "episodes": eps_raw,
        }

        return _resp("detail", merged,
                     status=head.get("status") if isinstance(head, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /detail error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /stream — Episode play info
# ═══════════════════════════════════════════════════════════════════════
@shortmax_bp.route('/stream', methods=['GET'])
def stream():
    sid = request.args.get('id') or request.args.get('shortPlayId') \
        or request.args.get('dreamId')
    if not sid:
        return error_response(400, "Missing 'id' (shortPlayId) parameter")
    try:
        sid_int = int(sid)
    except ValueError:
        return error_response(400, "'id' must be numeric shortPlayId")

    episode_no = int(request.args.get('episode_no', 1))
    # playSlideV3 is a "for-you" slide: it pivots currentEpisodesReponse at a
    # SERVER-chosen episode (e.g. last-watched), NOT at our episode_no. So we
    # must request a window wide enough that episode_no lands in prev/cur/next,
    # then select by episodeNum. Allow explicit override via prev/next.
    prev_n = request.args.get('prev')
    next_n = request.args.get('next')
    prev_n = int(prev_n) if prev_n is not None else 200
    next_n = int(next_n) if next_n is not None else 200

    try:
        # playSlideV3 expects dreamId == shortPlayId (per APK Retrofit signature)
        body = {
            "scene": "",
            "dreamId": sid_int,
            "previousEpisodes": prev_n,
            "nextEpisodes": next_n,
            "videoType": 1,
        }
        data = _do_request("app/forYou/playSlideV3", body)

        def _data(x):
            return x.get("data") if isinstance(x, dict) else x

        d = _data(data) or {}
        # Best-effort selection: pick the requested episode_no if present
        cur = d.get("currentEpisodesReponse") if isinstance(d, dict) else None
        prev_eps = d.get("previousEpisodesReponse") if isinstance(d, dict) else None
        next_eps = d.get("nextEpisodesReponse") if isinstance(d, dict) else None

        chosen = None
        for pool in (cur and [cur], next_eps or [], prev_eps or []):
            if not pool:
                continue
            for ep in pool:
                if isinstance(ep, dict) and ep.get("episodeNum") == episode_no:
                    chosen = ep
                    break
            if chosen:
                break
        if not chosen and isinstance(cur, dict):
            chosen = cur

        # videoUrl is a JSON map { video_480, video_720, video_1080 } encoded
        # as a string. Parse it and surface a clean dict + best URL.
        streams = {}
        play_url = None
        vu = (chosen or {}).get("videoUrl")
        if isinstance(vu, str) and vu.strip().startswith("{"):
            try:
                streams = json.loads(vu)
            except Exception:
                streams = {}
        # Prefer 1080 → 720 → 480 → first available
        for k in ("video_1080", "video_720", "video_480"):
            if streams.get(k):
                play_url = streams[k]
                break
        if not play_url and streams:
            play_url = next(iter(streams.values()))

        return _resp("stream", {
            "shortPlayId": sid_int,
            "episode_no": episode_no,
            "play_url": play_url,
            "streams": streams,
        }, status=data.get("status") if isinstance(data, dict) else None)
    except Exception as e:
        return error_response(500, f"ShortMax /stream error: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /streamv2 — Playback via external resolver
#
# An external resolver returns play info as a CryptoJS AES "Salted__" blob
# (OpenSSL EVP_BytesToKey/MD5, AES-CBC). Decrypted JSON carries a `video`
# map (video_480/720/1080) + picked `hls_url`. Takes the resolver's own
# bookId + episode — no ShortMax RC4/RSA session needed.
# NOTE: resolver bookId is a DIFFERENT id space than our shortPlayId.
# ═══════════════════════════════════════════════════════════════════════
_RESOLVER_BASE = "https://dramakuy.com"
_RESOLVER_PASSPHRASE = b"DracinBox-SecureKey2026"


def _cryptojs_decrypt(b64_blob, passphrase=_RESOLVER_PASSPHRASE):
    """Decrypt a CryptoJS AES 'Salted__' blob (OpenSSL EVP_BytesToKey/MD5)."""
    raw = base64.b64decode(b64_blob)
    if raw[:8] != b"Salted__":
        raise ValueError("not a salted blob")
    salt = raw[8:16]
    ct = raw[16:]
    d = b""
    prev = b""
    while len(d) < 48:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        d += prev
    key, iv = d[:32], d[32:48]
    return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ct), 16)


def _resolve_play(book_id, episode):
    """Call the external resolver, return decrypted play info JSON.
    Upstream is flaky; retry a few times before giving up."""
    url = f"{_RESOLVER_BASE}/api/shortmax/play?bookId={book_id}&episode={episode}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "referer": f"{_RESOLVER_BASE}/watch/shortmax/{book_id}/{episode}",
        "accept": "*/*",
    }
    last_err = "unknown"
    for _ in range(6):
        r = None
        try:
            r = http_requests.get(url, headers=headers, timeout=20)
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
        except Exception:
            return None, "decrypt failed"
        if isinstance(decrypted, dict) and decrypted.get("error"):
            last_err = decrypted["error"]
            time.sleep(1)
            continue
        return decrypted, None
    return None, last_err


@shortmax_bp.route('/streamv2', methods=['GET'])
def streamv2():
    """Resolve a playable ShortMax episode.

    Params:
      id / bookId (required), ep / episode (default 1).

    Returns a direct HLS (.m3u8) + quality map.
    """
    book_id = request.args.get('id') or request.args.get('bookId')
    if not book_id:
        return error_response(400, "Missing 'id' (bookId) parameter")

    episode_no = request.args.get('ep') or request.args.get('episode') or '1'
    try:
        ep_num = int(episode_no)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    data, err = _resolve_play(book_id, ep_num)
    if err:
        return error_response(502, "Stream temporarily unavailable")

    streams = data.get("video") if isinstance(data.get("video"), dict) else {}
    play_url = data.get("hls_url") or data.get("url") or ""
    if not play_url:
        for k in ("video_1080", "video_720", "video_480"):
            if streams.get(k):
                play_url = streams[k]
                break

    return _resp("streamv2", {
        "shortPlayId": data.get("id", book_id),
        "book_id": book_id,
        "episode_no": data.get("episode", ep_num),
        "total": data.get("total"),
        "name": data.get("name"),
        "play_url": play_url,
        "streams": streams,
    })
