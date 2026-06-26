"""
routes/moviebox.py — MovieBox (aoneroom / wefeed) ranking API
Reversed from MovieBox APK 3.0.15.0513.03 (pkg com.community.oneroom).

Endpoints (ranking-list by region category):
  /moviebox/indonesia   /moviebox/global    /moviebox/hollywood
  /moviebox/asia        /moviebox/horror    /moviebox/animasi

Auth chain (all required on every call):
  1. JWT       — POST /user-api/visitor-login {"deviceId": <hex>} → data.token (cached, ~90d)
  2. x-tr-sig  — {ts}|1|HmacMD5(base64key, signString) ; signString joined by '\n':
                 METHOD\nACCEPT\nCT\nBODYLEN\nTS\nBODY_MD5_HEX\nPATH?SORTED_QUERY
  3. X-Client-Token = {ts},{md5(md5(ts))}      (keyless)
  4. X-Client-Info  = compact JSON device profile (carries device_id + region)
"""
import time
import json
import hashlib
import hmac
import base64
import uuid
import threading
from urllib.parse import urlencode, urlparse, parse_qsl
import requests
from flask import Blueprint, request
from utils import json_response, error_response

moviebox_bp = Blueprint('moviebox', __name__, url_prefix='/moviebox')

API_AUTHOR = "Sonzai X シ"
API_CONTACT = "https://t.me/November2k"

# ─── MovieBox config (extracted from APK) ─────────────────────────────
MB_HOST = "https://api4sg.aoneroom.com"
MB_BFF = "/wefeed-mobile-bff"
# gateway_secret_online from AndroidManifest meta-data
MB_SIGN_SECRET = "76iRl07s0xSN9jqmEWAt79EBJZulIQIsV64FZr2O"
MB_KEY_VERSION = "1"
MB_VERSION_NAME = "3.0.15.0513.03"
MB_VERSION_CODE = 30015013
MB_PACKAGE = "com.community.oneroom"
MB_UA = f"{MB_PACKAGE}/{MB_VERSION_CODE}"

# Region profile (Indonesia)
MB_REGION = "ID"
MB_LANGUAGE = "in"
MB_TIMEZONE = "Asia/Jakarta"

MB_TIMEOUT = 20

# Ranking-list config (categoryType per region) — from ranking-list categoryList
MB_RANKING_LIST_ID = "9047558218997816672"
MB_RANKING_CATEGORIES = {
    "indonesia": {"name": "Indonesia", "type": "6528093688173053896"},
    "global": {"name": "Seluruh dunia", "type": "8821254238245470240"},
    "hollywood": {"name": "Hollywood", "type": "997144265920760504"},
    "asia": {"name": "Asia lainnya", "type": "4230655749032234008"},
    "horror": {"name": "Horror", "type": "5848753831881965888"},
    "animasi": {"name": "Animasi", "type": "7132534597631837112"},
}

# Drama ranking-list (separate rankingListId + categoryType set)
MB_DRAMA_LIST_ID = "7311490931390663312"
MB_DRAMA_CATEGORIES = {
    "kdrama": {"name": "K-Drama", "type": "4380734070238626200"},
    "indo": {"name": "Indo Drama", "type": "5283462032510044280"},
    "anime": {"name": "Anime", "type": "8617025562613270856"},
    "barat": {"name": "Barat", "type": "5307082080063488480"},
    "cdrama": {"name": "C-Drama", "type": "8624142774394406504"},
    "thai": {"name": "Thai-Drama", "type": "1164329479448281992"},
    "reality": {"name": "Reality", "type": "5720220657917522824"},
}

# ─── Token cache (process-wide) ──────────────────────────────────────
_token_lock = threading.Lock()
_token_cache = {"token": None, "device_id": None, "exp": 0}


# ─── Signing helpers ─────────────────────────────────────────────────

def _md5_hex(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def _client_token():
    """X-Client-Token = {ts},{md5(md5(ts))} — keyless."""
    ts = str(int(time.time() * 1000))
    return f"{ts},{_md5_hex(_md5_hex(ts))}"


def _client_info(device_id):
    """X-Client-Info compact JSON device profile (Indonesia region)."""
    info = {
        "package_name": MB_PACKAGE,
        "version_name": MB_VERSION_NAME,
        "version_code": MB_VERSION_CODE,
        "os": "android",
        "os_version": "13",
        "device_id": device_id,
        "install_store": "1",
        "brand": "samsung",
        "model": "SM-G991B",
        "system_language": MB_LANGUAGE,
        "net": "WIFI",
        "region": MB_REGION,
        "timezone": MB_TIMEZONE,
        "sp_code": "",
    }
    return json.dumps(info, separators=(',', ':'))


def _sorted_query(query_str):
    """Sort query params alphabetically by key (HttpSigner.f/c)."""
    if not query_str:
        return ""
    pairs = parse_qsl(query_str, keep_blank_values=True)
    pairs.sort(key=lambda kv: kv[0])
    return "&".join(f"{k}={v}" for k, v in pairs)


def _x_tr_signature(method, path_with_query, body):
    """Build x-tr-signature = {ts}|{keyVersion}|{HmacMD5 base64}."""
    ts = int(time.time() * 1000)
    accept = "*/*"
    content_type = "application/json"
    body_len = str(len(body)) if body else ""
    body_hash = _md5_hex(body) if body else ""

    parsed = urlparse(path_with_query)
    norm_path = parsed.path
    sq = _sorted_query(parsed.query)
    if sq:
        norm_path = f"{norm_path}?{sq}"

    sign_string = "\n".join([
        method.upper(), accept, content_type, body_len,
        str(ts), body_hash, norm_path
    ])
    key = base64.b64decode(MB_SIGN_SECRET)
    mac = hmac.new(key, sign_string.encode('utf-8'), hashlib.md5)
    sig = base64.b64encode(mac.digest()).decode('utf-8')
    return f"{ts}|{MB_KEY_VERSION}|{sig}"


# ─── Auth / token ────────────────────────────────────────────────────

def _get_token(force=False):
    """Get a cached visitor JWT, refreshing if expired/forced."""
    with _token_lock:
        now = int(time.time())
        if not force and _token_cache["token"] and _token_cache["exp"] - 60 > now:
            return _token_cache["token"], _token_cache["device_id"]

        device_id = _token_cache["device_id"] or uuid.uuid4().hex
        path = f"{MB_BFF}/user-api/visitor-login"
        body = json.dumps({"deviceId": device_id}, separators=(',', ':'))
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-tr-signature": _x_tr_signature("POST", path, body),
            "X-Client-Token": _client_token(),
            "X-Client-Info": _client_info(device_id),
            "X-Client-Status": "1",
            "User-Agent": MB_UA,
        }
        r = requests.post(MB_HOST + path, headers=headers, data=body, timeout=MB_TIMEOUT)
        data = r.json()
        if data.get("code") != 0 or not data.get("data", {}).get("token"):
            raise RuntimeError(f"visitor-login failed: {data.get('message')}")

        token = data["data"]["token"]
        exp = now + 3600 * 24
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            if claims.get("exp"):
                exp = int(claims["exp"])
        except Exception:
            pass

        _token_cache.update({"token": token, "device_id": device_id, "exp": exp})
        return token, device_id


# ─── Core request ────────────────────────────────────────────────────

def _mb_request(method, path, query=None, payload=None, retry=True):
    """Signed request to MovieBox BFF. Returns parsed JSON dict."""
    token, device_id = _get_token()

    query_str = urlencode(query) if query else ""
    full_path = path + (f"?{query_str}" if query_str else "")
    body = json.dumps(payload, separators=(',', ':')) if payload is not None else None

    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "x-tr-signature": _x_tr_signature(method, full_path, body),
        "X-Client-Token": _client_token(),
        "X-Client-Info": _client_info(device_id),
        "X-Client-Status": "1",
        "Authorization": "Bearer " + token,
        "User-Agent": MB_UA,
    }

    url = MB_HOST + full_path
    if method.upper() == "GET":
        r = requests.get(url, headers=headers, timeout=MB_TIMEOUT)
    else:
        r = requests.post(url, headers=headers, data=body, timeout=MB_TIMEOUT)

    try:
        data = r.json()
    except Exception:
        return {"code": -1, "message": "invalid json", "raw": r.text[:300]}

    if retry and (r.status_code in (401, 403) or (isinstance(data, dict) and data.get("code") in (401, 403))):
        _get_token(force=True)
        return _mb_request(method, path, query, payload, retry=False)

    return data


def _ranking(cat_key, categories=None, default_list_id=None):
    """Ranking list for a named category. Defaults to region categories."""
    categories = categories or MB_RANKING_CATEGORIES
    default_list_id = default_list_id or MB_RANKING_LIST_ID
    cat = categories[cat_key]
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('perPage', 10))
    tab_id = int(request.args.get('tabId', 0))
    ranking_list_id = request.args.get('rankingListId', '') or default_list_id
    data = _mb_request("GET", f"{MB_BFF}/tab/ranking-list", query={
        "tabId": tab_id, "categoryType": cat["type"], "page": page,
        "perPage": per_page, "rankingListId": ranking_list_id
    })
    if isinstance(data, dict):
        data["category"] = {"key": cat_key, "name": cat["name"], "type": cat["type"]}
    return data


# ─── Routes ──────────────────────────────────────────────────────────

@moviebox_bp.route('/', methods=['GET'])
def moviebox_index():
    return json_response({
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "status": "online",
        "service": "MovieBox Ranking API",
        "source": "aoneroom / wefeed",
        "region": MB_REGION,
        "version": "2.0.0",
        "endpoints": {
            "homepage": "/moviebox/homepage?tabId=0",
            "search": "/moviebox/search?q=KEYWORD&page=1&perPage=10",
            "detail": "/moviebox/detail?subjectId=ID",
            "download_movie": "/moviebox/download-movie?subjectId=ID",
            "download_series": "/moviebox/download-series?subjectId=ID&se=1&resolution=0",
            "indonesia": "/moviebox/indonesia?page=1&perPage=10",
            "global": "/moviebox/global?page=1&perPage=10",
            "hollywood": "/moviebox/hollywood?page=1&perPage=10",
            "asia": "/moviebox/asia?page=1&perPage=10",
            "horror": "/moviebox/horror?page=1&perPage=10",
            "animasi": "/moviebox/animasi?page=1&perPage=10",
            "series_categories": "/moviebox/series",
            "series": "/moviebox/series/{kdrama|indo|anime|barat|cdrama|thai|reality}?page=1&perPage=10",
        }
    })


@moviebox_bp.route('/homepage', methods=['GET'])
def moviebox_homepage():
    tab_id = request.args.get('tabId', '0')
    version = request.args.get('version', '')
    try:
        data = _mb_request("GET", f"{MB_BFF}/tab-operating", query={
            "tabId": tab_id, "version": version
        })
        return json_response(data)
    except Exception as e:
        return error_response(500, f"homepage failed: {e}")


@moviebox_bp.route('/search', methods=['GET'])
def moviebox_search():
    keyword = request.args.get('q') or request.args.get('keyword')
    if not keyword:
        return error_response(400, "missing 'q' (keyword)")
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('perPage', 10))
    try:
        data = _mb_request("POST", f"{MB_BFF}/subject-api/search/v2",
                           payload={"page": page, "perPage": per_page, "keyword": keyword})
        return json_response(data)
    except Exception as e:
        return error_response(500, f"search failed: {e}")


@moviebox_bp.route('/detail', methods=['GET'])
def moviebox_detail():
    """Subject detail (title, genre, episodes meta)."""
    subject_id = request.args.get('subjectId') or request.args.get('id')
    if not subject_id:
        return error_response(400, "missing 'subjectId'")
    query = {"subjectId": subject_id}
    se = request.args.get('se')
    if se is not None:
        query["se"] = se
    try:
        data = _mb_request("GET", f"{MB_BFF}/subject-api/get", query=query)
        return json_response(data)
    except Exception as e:
        return error_response(500, f"detail failed: {e}")


def _indo_caption(sid, stream_id):
    """Return the Indonesian caption dict for a subjectId + streamId, or None."""
    try:
        caps = _mb_request("GET", f"{MB_BFF}/subject-api/get-stream-captions",
                          query={"subjectId": sid, "streamId": stream_id})
        ext = caps.get("data", {}).get("extCaptions", []) if isinstance(caps, dict) else []
        for c in ext:
            if c.get("lan") in ("in_id", "id", "in") or c.get("lanName") == "Indonesian":
                return c
    except Exception:
        pass
    return None


def _original_dub_sid(subject_id):
    """Resolve the 'Original Audio' subjectId for a title (via dub-info)."""
    try:
        di = _mb_request("GET", f"{MB_BFF}/subject-api/dub-info", query={"subjectId": subject_id})
        dubs = di.get("data", {}).get("dubs", []) if isinstance(di, dict) else []
        for d in dubs:
            if d.get("original") and d.get("subjectId"):
                return d["subjectId"]
        if dubs and dubs[0].get("subjectId"):
            return dubs[0]["subjectId"]
    except Exception:
        pass
    return subject_id


def _fetch_resource(sid, se, ep_from, ep_to, resolution, per_page, pager_mode=0):
    res = _mb_request("GET", f"{MB_BFF}/subject-api/resource", query={
        "subjectId": sid, "page": 1, "perPage": per_page,
        "all": 0, "startPosition": ep_from, "endPosition": ep_to, "pagerMode": pager_mode,
        "resolution": resolution, "se": se, "epFrom": ep_from, "epTo": ep_to
    })
    data = res.get("data", {}) if isinstance(res, dict) else {}
    return data.get("list", []), data


@moviebox_bp.route('/download-movie', methods=['GET'])
def moviebox_download_movie():
    """Movie download (Original Audio only): resolution options + Indonesian subtitle."""
    subject_id = request.args.get('subjectId') or request.args.get('id')
    if not subject_id:
        return error_response(400, "missing 'subjectId'")
    se = int(request.args.get('se', 1))
    ep = int(request.args.get('ep', 1))
    per_page = int(request.args.get('perPage', 20))
    resolution = int(request.args.get('resolution', 0))
    try:
        sid = _original_dub_sid(subject_id)
        files, meta = _fetch_resource(sid, se, ep, ep, resolution, per_page)

        # subtitle: prefer play-info streamId (reliable), fall back to file resourceId
        subtitle = None
        try:
            for q in ({"subjectId": sid, "se": se, "ep": ep}, {"subjectId": sid, "se": 0, "ep": 0}):
                play = _mb_request("GET", f"{MB_BFF}/subject-api/play-info", query=q)
                streams = play.get("data", {}).get("streams", []) if isinstance(play, dict) else []
                if streams and streams[0].get("id"):
                    subtitle = _indo_caption(sid, streams[0]["id"])
                    break
        except Exception:
            pass
        if not subtitle:
            for f in files:
                if f.get("resourceId"):
                    subtitle = _indo_caption(sid, f["resourceId"])
                    if subtitle:
                        break

        return json_response({
            "code": 0, "message": "ok",
            "data": {
                "subjectId": sid,
                "title": meta.get("subjectTitle"),
                "totalSize": meta.get("totalSize"),
                "subtitle": subtitle,
                "files": [
                    {
                        "resolution": f.get("resolution"),
                        "size": f.get("size"),
                        "codecName": f.get("codecName"),
                        "duration": f.get("duration"),
                        "resourceLink": f.get("resourceLink"),
                        "resourceId": f.get("resourceId"),
                    } for f in files
                ],
            }
        })
    except Exception as e:
        return error_response(500, f"download-movie failed: {e}")


@moviebox_bp.route('/download-series', methods=['GET'])
def moviebox_download_series():
    """Series download (Original Audio only): every episode + per-episode Indonesian subtitle.
    Optional ?resolution=360|480|1080 (0=auto). Each episode's subtitle via play-info streamId."""
    subject_id = request.args.get('subjectId') or request.args.get('id')
    if not subject_id:
        return error_response(400, "missing 'subjectId'")
    se = int(request.args.get('se', 1))
    per_page = int(request.args.get('perPage', 20))
    resolution = int(request.args.get('resolution', 0))
    ep_to = int(request.args.get('epTo', 10))
    try:
        sid = _original_dub_sid(subject_id)
        # pagerMode=1 + endPosition=N + resolution → full episode list at chosen resolution
        files, meta = _fetch_resource(sid, se, 1, ep_to, resolution, per_page, pager_mode=1)
        if not files:
            # fallback: pagerMode=0, single position returns whole list (auto resolution)
            files, meta = _fetch_resource(sid, se, 1, 1, resolution, per_page, pager_mode=0)

        episodes = []
        for idx, f in enumerate(files, start=1):
            ep_no = f.get("ep") if f.get("ep") else idx
            rid = f.get("resourceId")
            # subtitle: play-info(se, ep) → streamId → captions (reliable per episode)
            subtitle = None
            try:
                play = _mb_request("GET", f"{MB_BFF}/subject-api/play-info",
                                   query={"subjectId": sid, "se": se, "ep": ep_no})
                streams = play.get("data", {}).get("streams", []) if isinstance(play, dict) else []
                if streams and streams[0].get("id"):
                    subtitle = _indo_caption(sid, streams[0]["id"])
            except Exception:
                pass
            if not subtitle and rid:
                subtitle = _indo_caption(sid, rid)
            episodes.append({
                "se": f.get("se"),
                "ep": ep_no,
                "title": f.get("title"),
                "resolution": f.get("resolution"),
                "size": f.get("size"),
                "codecName": f.get("codecName"),
                "duration": f.get("duration"),
                "resourceLink": f.get("resourceLink"),
                "resourceId": rid,
                "subtitle": subtitle,
            })

        return json_response({
            "code": 0, "message": "ok",
            "data": {
                "subjectId": sid,
                "title": meta.get("subjectTitle"),
                "totalEpisode": meta.get("totalEpisode") or len(episodes),
                "totalSize": meta.get("totalSize"),
                "episodes": episodes,
            }
        })
    except Exception as e:
        return error_response(500, f"download-series failed: {e}")


@moviebox_bp.route('/indonesia', methods=['GET'])
def moviebox_indonesia():
    try:
        return json_response(_ranking("indonesia"))
    except Exception as e:
        return error_response(500, f"indonesia ranking failed: {e}")


@moviebox_bp.route('/global', methods=['GET'])
def moviebox_global():
    try:
        return json_response(_ranking("global"))
    except Exception as e:
        return error_response(500, f"global ranking failed: {e}")


@moviebox_bp.route('/hollywood', methods=['GET'])
def moviebox_hollywood():
    try:
        return json_response(_ranking("hollywood"))
    except Exception as e:
        return error_response(500, f"hollywood ranking failed: {e}")


@moviebox_bp.route('/asia', methods=['GET'])
def moviebox_asia():
    try:
        return json_response(_ranking("asia"))
    except Exception as e:
        return error_response(500, f"asia ranking failed: {e}")


@moviebox_bp.route('/horror', methods=['GET'])
def moviebox_horror():
    try:
        return json_response(_ranking("horror"))
    except Exception as e:
        return error_response(500, f"horror ranking failed: {e}")


@moviebox_bp.route('/animasi', methods=['GET'])
def moviebox_animasi():
    try:
        return json_response(_ranking("animasi"))
    except Exception as e:
        return error_response(500, f"animasi ranking failed: {e}")


@moviebox_bp.route('/series', methods=['GET'])
def moviebox_series_index():
    """List available series categories."""
    return json_response({
        "code": 0,
        "rankingListId": MB_DRAMA_LIST_ID,
        "categories": [
            {"key": k, "name": v["name"], "type": v["type"], "path": f"/moviebox/series/{k}"}
            for k, v in MB_DRAMA_CATEGORIES.items()
        ],
    })


@moviebox_bp.route('/series/<category>', methods=['GET'])
def moviebox_series(category):
    """Series ranking by category: kdrama/indo/anime/barat/cdrama/thai/reality."""
    key = category.lower()
    if key not in MB_DRAMA_CATEGORIES:
        return error_response(404, f"unknown series category '{category}'. "
                                   f"Available: {', '.join(MB_DRAMA_CATEGORIES.keys())}")
    try:
        data = _ranking(key, categories=MB_DRAMA_CATEGORIES, default_list_id=MB_DRAMA_LIST_ID)
        return json_response(data)
    except Exception as e:
        return error_response(500, f"series ranking failed: {e}")
