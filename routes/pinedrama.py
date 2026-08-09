"""
routes/pinedrama.py — PineDrama (TikTok Mini Drama) API
Reverse-engineered from PineDrama_45.2.1.apks via DEX analysis + network capture

Tech notes:
  - Base URL    : https://api16-normal-c-alisg.tiktokv.com
  - Package     : com.ss.android.ttmd.video (ByteDance TikTok Mini Drama)
  - App Version : 45.2.1 (version_code: 450201)
  - Auth        : Uses ByteDance request signing (x-argus, x-gorgon, x-ladon)
  - Note        : Signatures are time/device-specific; may need regeneration

Discovered API paths from DEX reverse engineering:
  /tiktok/md/mini_drama_center/v1/              — Home / trending / category
  /tiktok/md/collection/video/v1/               — Episode list + video URLs (protobuf)
  /tiktok/md/collection/search/v1/              — Search dramas
  /tiktok/md/collection/recommend/v1/           — Recommended dramas
  /tiktok/md/collection/episode_panel/v1/       — Episode panel
  /tiktok/md/collection/list/v1/                — Collection listing
  /tiktok/md/collection/mini_drama_list/v1/     — Mini drama list
  /tiktok/md/mini_drama/feed/v1/                — Drama feed
  /tiktok/md/mini_drama/video/v1/               — Single video info
  /tiktok/md/mini_drama/resume/v1/              — Resume watching
  /tiktok/md/mini_drama/watch_history/v1/       — Watch history
  /tiktok/md/mini_drama/skylight/v1/            — Featured/skylight
  /tiktok/feed/mini_drama/v1                    — Main mini drama feed
  /tiktok/v1/paid_content/mini_drama_center     — Paid content center
  /tiktok/v1/paid_content/collection/video      — Paid video
  /tiktok/v3/paid_content/collection/video      — V3 paid video

Public endpoints:
  GET  /pinedrama/home?page=1&count=15            — Home feed (all dramas)
  GET  /pinedrama/trending?page=1&count=15        — Trending dramas
  GET  /pinedrama/search?q=ceo&page=1&count=20    — Search dramas
  GET  /pinedrama/category?id=...&page=1          — Dramas by category
  GET  /pinedrama/category-list                   — Available categories/scenes
  GET  /pinedrama/detail?id=...&count=10          — Drama detail + episodes
  GET  /pinedrama/stream?id=...&ep=1              — Stream video URLs for episode
  GET  /pinedrama/watch?url=...                   — Video proxy (Range-aware)
  GET  /pinedrama/recommend?page=1&count=15       — Recommended dramas
  GET  /pinedrama/ranking?page=1&count=15         — Ranking/popular dramas
  GET  /pinedrama/feed?count=10                   — Mini drama video feed
  GET  /pinedrama/episode-panel?id=...            — Episode panel data
  GET  /pinedrama/info                            — API information
"""
import json
import re
import time
import urllib.parse
import requests as http_requests
from flask import Blueprint, request, Response
from utils import json_response, error_response
from config import API_AUTHOR, API_CONTACT

pinedrama_bp = Blueprint('pinedrama', __name__, url_prefix='/pinedrama')

# ── TikTok API Endpoints ────────────────────────────────────────────
TIKTOK_API_BASE = "https://api16-normal-c-alisg.tiktokv.com"

PINEDRAMA_BASE = f"{TIKTOK_API_BASE}/tiktok/md/mini_drama_center/v1/"
PINEDRAMA_SEARCH_BASE = f"{TIKTOK_API_BASE}/tiktok/md/collection/search/v1/"
PINEDRAMA_VIDEO_BASE = f"{TIKTOK_API_BASE}/tiktok/md/collection/video/v1/"
PINEDRAMA_RECOMMEND_BASE = f"{TIKTOK_API_BASE}/tiktok/md/collection/recommend/v1/"
PINEDRAMA_EPISODE_PANEL_BASE = f"{TIKTOK_API_BASE}/tiktok/md/collection/episode_panel/v1/"
PINEDRAMA_LIST_BASE = f"{TIKTOK_API_BASE}/tiktok/md/collection/list/v1/"
PINEDRAMA_FEED_BASE = f"{TIKTOK_API_BASE}/tiktok/feed/mini_drama/v1"
PINEDRAMA_DRAMA_FEED_BASE = f"{TIKTOK_API_BASE}/tiktok/md/mini_drama/feed/v1/"
PINEDRAMA_VIDEO_SINGLE_BASE = f"{TIKTOK_API_BASE}/tiktok/md/mini_drama/video/v1/"
PINEDRAMA_PAID_CENTER_BASE = f"{TIKTOK_API_BASE}/tiktok/v2/paid_content/mini_drama_center"
PINEDRAMA_PAID_VIDEO_BASE = f"{TIKTOK_API_BASE}/tiktok/v3/paid_content/collection/video"

# ── Static device/app parameters (from captured request) ────────────
DEVICE_PARAMS = {
    "device_platform": "android",
    "os": "android",
    "ssmix": "a",
    "channel": "googleplay",
    "aid": "845221",
    "app_name": "tiktok_drama",
    "version_code": "450201",
    "version_name": "45.2.1",
    "manifest_version_code": "2024502010",
    "update_version_code": "2024502010",
    "ab_version": "45.2.1",
    "resolution": "960*540",
    "dpi": "186",
    "device_type": "SM-A528B",
    "device_brand": "Samsung",
    "language": "en",
    "os_api": "32",
    "os_version": "12",
    "ac": "wifi",
    "is_pad": "0",
    "app_type": "normal",
    "sys_region": "US",
    "last_install_time": "1781430063",
    "mcc_mnc": "302780",
    "timezone_name": "Asia/Jakarta",
    "carrier_region_v2": "302",
    "app_language": "id",
    "carrier_region": "CA",
    "app_package": "com.ss.android.ugc.tiktok.lite",
    "timezone_offset": "25200",
    "host_abi": "arm64-v8a",
    "locale": "id-ID",
    "ac2": "wifi5g",
    "uoo": "0",
    "op_region": "CA",
    "build_number": "45.2.1",
    "app_package_type": "pro",
    "region": "ID",
    # Device identifiers — required for signed endpoints
    "iid": "7651183755453007624",
    "device_id": "7649780290684864005",
    "openudid": "c73e07d28f007c8c",
    "cdid": "950fb60c-ae1f-4a55-99b0-f7f4a91218e8",
}

# Cookie for authenticated requests
DEVICE_COOKIE = (
    "store-idc=alisg; store-country-code=ca; store-country-code-src=did; "
    "install_id=7651183755453007624; "
    "ttreq=1$693e3944e26ca0e0af9a0fb1754d025299f322cf; "
    "odin_tt=c27249c8e0429443e2ec3540457c725d24696236026dbe554b55119379963e22b55be07f3fb3754839e7c5689d2f26b4aa7f1220fb1f63e5d69bc54660f274976b907a1778aa7da8451252209f4da6c2"
)


def _get_headers(signed=False):
    """Generate headers for PineDrama API requests"""
    h = {
        "User-Agent": "com.ss.android.ttmd.video/2024502010 (Linux; U; Android 12; en; SM-A528B; Build/V417IR;tt-ok/3.12.13.21)",
        "Accept-Encoding": "gzip",
        "sdk-version": "2",
        "passport-sdk-version": "1",
    }
    if signed:
        h.update({
            "x-ss-req-ticket": str(int(time.time() * 1000)),
            "x-vc-bdturing-sdk-version": "2.4.2.i18n",
            "x-tt-store-region": "ca",
            "x-tt-store-region-src": "did",
            "rpc-persist-pyxis-policy-v-tnc": "1",
            "cookie": DEVICE_COOKIE,
        })
    return h


def _ts_params():
    """Return timestamp params"""
    return {
        "ts": str(int(time.time())),
        "_rticket": str(int(time.time() * 1000)),
    }


def _api_request(base_url=None, params=None, extra_headers=None):
    """Make request to PineDrama API"""
    url = base_url or PINEDRAMA_BASE

    # Merge device params with request params
    all_params = DEVICE_PARAMS.copy()
    all_params.update(_ts_params())

    if params:
        all_params.update(params)

    headers = _get_headers()
    if extra_headers:
        headers.update(extra_headers)

    try:
        resp = http_requests.get(url, headers=headers, params=all_params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except http_requests.exceptions.RequestException as e:
        return {"error": str(e), "status_code": 500}


def _api_request_binary(base_url, params=None, extra_headers=None, signing_headers=None):
    """
    Make request that returns binary/protobuf content.
    
    Args:
        signing_headers: dict with x-argus, x-gorgon, x-ladon, x-khronos
                         from the incoming Flask request. Required for
                         endpoints that need TikTok request signing.
    """
    url = base_url

    all_params = DEVICE_PARAMS.copy()
    all_params.update(_ts_params())

    if params:
        all_params.update(params)

    # Use signed headers if signing headers are available
    has_signing = signing_headers and signing_headers.get("x-argus")
    headers = _get_headers(signed=has_signing)
    if extra_headers:
        headers.update(extra_headers)
    if has_signing:
        headers.update(signing_headers)

    resp = http_requests.get(url, headers=headers, params=all_params, timeout=30)
    resp.raise_for_status()
    return resp.content


def _transform_collections(result):
    """Transform raw API response collections into clean format"""
    dramas = []
    if "collections" in result:
        for item in result["collections"]:
            drama = {
                "id": str(item.get("collection_id", "")),
                "title": item.get("title", ""),
                "cover": item.get("cover", {}).get("url_list", [None])[0],
                "categories": item.get("categories", ""),
                "num_episodes": item.get("num_videos", 0),
                "num_watched": item.get("num_watched", 0),
                "is_free": item.get("is_limited_free", False),
                "tags": [tag.get("name") for tag in item.get("theme_tag_list", [])],
            }
            dramas.append(drama)
    return dramas


# ── Normalization → Fi x Zam app shape ──────────────────────────────
# App list endpoints expect data: [{ "books": [<MeloloBook>] }]. PineDrama
# has no per-drama description; episode count comes from num_episodes.
def _pd_to_book(d):
    cats = d.get("categories")
    tags = d.get("tags") or []
    if isinstance(cats, str) and cats:
        tags = [cats] + tags
    elif isinstance(cats, list):
        tags = cats + tags
    return {
        "drama_id": str(d.get("id") or ""),
        "drama_name": d.get("title") or "",
        "description": "",
        "episode_count": str(d.get("num_episodes") or 0),
        "watch_value": str(d.get("num_watched") or ""),
        "is_new_book": "0",
        "language": "id",
        "thumb_url": d.get("cover") or "",
        "tags": [t for t in tags if t],
    }


def _pd_books_resp(type_, dramas, **extra):
    payload = {
        "author": API_AUTHOR,
        "contact": API_CONTACT,
        "type": type_,
        "data": [{"books": [_pd_to_book(d) for d in dramas]}],
    }
    payload.update(extra)
    return json_response(payload)


def _parse_feed_protobuf(content):
    """
    Parse the mini_drama/feed protobuf binary response.
    Returns a list of video items with episode metadata and CDN URLs.

    The protobuf contains per-video segments, each with:
    - Episode metadata in embedded JSON blocks
    - Video CDN URLs (regional + global)
    - Cover/thumbnail URLs
    """
    text = content.decode('utf-8', errors='ignore')

    # 1. Find all episode metadata JSON blocks
    ep_pattern = r'\{"is_highlight.*?"video_title_prefix_for_episodes":null\}'
    ep_matches = list(re.finditer(ep_pattern, text))

    # 2. Find all video CDN URLs
    video_url_pattern = r'https://v[\w-]+\.tiktokcdn\.com/[^\s\'"<>\x00-\x1f]+'
    all_video_urls = list(re.finditer(video_url_pattern, text))

    # 3. Find cover/thumbnail URLs
    cover_url_pattern = r'https://p\d+-common-sign\.tiktokcdn\.com/[^\s\'"<>\x00-\x1f]+'
    all_cover_urls = re.findall(cover_url_pattern, text)

    items = []

    for i, ep_match in enumerate(ep_matches):
        try:
            ep_data = json.loads(ep_match.group(0))
        except json.JSONDecodeError:
            continue

        group_id = str((ep_data.get("log_extra") or {}).get("group_id", ""))
        ep_num = ep_data.get("episode_num_in_list", 0)
        total_eps = ep_data.get("video_cnt_in_list", 0)
        lang = (ep_data.get("log_extra") or {}).get("language_code", "")

        # Find video URLs in the segment BEFORE this episode JSON
        seg_start = ep_matches[i - 1].end() if i > 0 else 0
        seg_end = ep_match.start()

        # Collect video URLs in this segment
        segment_urls = []
        seen_paths = set()
        for url_match in all_video_urls:
            if seg_start <= url_match.start() < seg_end:
                url = url_match.group(0)
                path_m = re.search(r'/video/tos/[^?]+', url)
                path_key = path_m.group(0) if path_m else url
                if path_key not in seen_paths:
                    seen_paths.add(path_key)
                    segment_urls.append(url)

        # Separate regional and global CDN
        regional = [u for u in segment_urls if re.match(r'https://v\d+-', u)]
        global_cdn = [u for u in segment_urls if u.startswith('https://v3.')]

        video_url = regional[0] if regional else (global_cdn[0] if global_cdn else (segment_urls[0] if segment_urls else ""))
        backup_url = global_cdn[0] if global_cdn else ""

        # Find cover images near this episode
        covers = {}
        for curl in all_cover_urls:
            if '1080:1080' in curl or '540:720' in curl:
                covers.setdefault("large", curl)
            elif '720:720' in curl:
                covers.setdefault("medium", curl)
            elif '300:300' in curl:
                covers.setdefault("small", curl)
            elif '168:168' in curl:
                covers.setdefault("thumb", curl)
            elif '100:100' in curl:
                covers.setdefault("icon", curl)

        item = {
            "episode": ep_num,
            "group_id": group_id,
            "total_episodes": total_eps,
            "language": lang,
            "video_url": video_url,
            "video_url_backup": backup_url,
            "all_urls": segment_urls[:4],
            "covers": covers,
        }

        if video_url:
            item["watch"] = f"/pinedrama/watch?url={urllib.parse.quote(video_url, safe='')}"

        items.append(item)

    return items


def _parse_protobuf_episodes(content):
    """
    Parse protobuf binary response from collection/video endpoint.
    Used when signed requests are available.
    """
    text = content.decode('utf-8', errors='ignore')

    # Extract episode metadata
    ep_pattern = r'\{"is_highlight.*?"video_title_prefix_for_episodes":null\}'
    ep_matches = list(re.finditer(ep_pattern, text))

    # Extract video URLs
    video_url_pattern = r'https://v[\w-]+\.tiktokcdn\.com/[^\s\'"<>\x00-\x1f]+'
    all_video_urls = list(re.finditer(video_url_pattern, text))

    # Extract cover URLs
    cover_url_pattern = r'https://p\d+-common-sign\.tiktokcdn\.com/[^\s\'"<>\x00-\x1f]+'
    cover_urls = list(set(re.findall(cover_url_pattern, text)))

    # Extract title
    title = ""
    title_search = re.search(
        r'\d{19,20}.{1,5}([A-Za-z\u00C0-\u024F\u0400-\u04FF\u4e00-\u9fff][^\x00-\x08\x0e-\x1f]{5,200})',
        text[:500]
    )
    if title_search:
        title = title_search.group(1).strip()

    # Collection ID
    id_matches = re.findall(r'(\d{19,20})', text[:200])
    collection_id = id_matches[0] if id_matches else ""

    # Total episode count
    ep_count_match = re.search(r'(\d+)\s*Episode', text)
    total_ep = int(ep_count_match.group(1)) if ep_count_match else 0

    # Build URL groups
    url_groups = []
    seen_paths = set()
    for url_match in all_video_urls:
        url = url_match.group(0)
        path_m = re.search(r'/video/tos/[^?]+', url)
        if path_m:
            path = path_m.group(0)
            if path not in seen_paths:
                seen_paths.add(path)
                matching = [um.group(0) for um in all_video_urls if path in um.group(0)]
                url_groups.append(matching)

    # Build episodes
    episodes = []
    for i, ep_match in enumerate(ep_matches):
        try:
            meta = json.loads(ep_match.group(0))
        except json.JSONDecodeError:
            continue

        ep = {
            "episode": meta.get("episode_num_in_list", 0),
            "group_id": str((meta.get("log_extra") or {}).get("group_id", "")),
            "total_episodes": meta.get("video_cnt_in_list", 0),
            "language": (meta.get("log_extra") or {}).get("language_code", ""),
        }

        if i < len(url_groups):
            urls = url_groups[i]
            regional = [u for u in urls if re.match(r'https://v\d+-', u)]
            global_cdn = [u for u in urls if u.startswith('https://v3.')]
            ep["video_url"] = regional[0] if regional else (global_cdn[0] if global_cdn else (urls[0] if urls else ""))
            ep["video_url_backup"] = global_cdn[0] if global_cdn else ""
            ep["all_urls"] = urls[:4]
        else:
            ep["video_url"] = ""
            ep["video_url_backup"] = ""
            ep["all_urls"] = []

        if ep.get("video_url"):
            ep["watch"] = f"/pinedrama/watch?url={urllib.parse.quote(ep['video_url'], safe='')}"

        episodes.append(ep)

    if not total_ep and episodes:
        total_ep = episodes[0].get("total_episodes", 0)

    # Build covers dict
    covers = {}
    for curl in cover_urls:
        if '1080:1080' in curl or '540:720' in curl:
            covers.setdefault("large", curl)
        elif '720:720' in curl:
            covers.setdefault("medium", curl)
        elif '300:300' in curl:
            covers.setdefault("small", curl)
        elif '168:168' in curl:
            covers.setdefault("thumb", curl)
        elif '100:100' in curl:
            covers.setdefault("icon", curl)

    return {
        "collection_id": collection_id,
        "title": title,
        "total_episodes": total_ep,
        "covers": covers,
        "episodes": episodes,
    }


def _get_feed_videos(count=10):
    """
    Fetch videos from the mini drama feed.
    This works WITHOUT request signing and returns real video CDN URLs.
    """
    params = {
        "count": count,
        "is_preload": "0",
    }

    content = _api_request_binary(PINEDRAMA_DRAMA_FEED_BASE, params=params)
    return _parse_feed_protobuf(content)


# ═══════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ═══════════════════════════════════════════════════════════════════


@pinedrama_bp.route('/proxy', methods=['GET', 'POST'])
def proxy():
    """
    Proxy a pre-signed TikTok API request and parse the protobuf response.

    This endpoint allows you to forward a captured signed request from
    PineDrama app to TikTok's collection/video API and get parsed JSON back.

    Usage (GET): Pass the full TikTok API URL as 'url' parameter:
      GET /pinedrama/proxy?url=https://api16-normal-c-alisg.tiktokv.com/tiktok/md/collection/video/v1/?collection_id=...

    Usage (POST): Send JSON body with 'url' and optional 'headers':
      POST /pinedrama/proxy
      {
        "url": "https://api16-normal-c-alisg.tiktokv.com/tiktok/md/collection/video/v1/?collection_id=...",
        "headers": {
          "x-argus": "...",
          "x-gorgon": "...",
          "x-ladon": "...",
          "x-khronos": "..."
        }
      }

    The response is the protobuf binary parsed into structured JSON with
    episodes, video URLs, cover images, etc.
    """
    try:
        if request.method == 'POST':
            body = request.get_json(force=True, silent=True) or {}
            target_url = body.get('url', '')
            custom_headers = body.get('headers', {})
        else:
            target_url = request.args.get('url', '')
            custom_headers = {}

        if not target_url:
            return error_response(400, "Missing 'url' parameter")

        # Build headers — use provided or extract from incoming request
        headers = _get_headers(signed=True)

        # Forward signing headers from the incoming request
        for h in ["x-argus", "x-gorgon", "x-ladon", "x-khronos", "cookie"]:
            val = custom_headers.get(h) or request.headers.get(h, "")
            if val:
                headers[h] = val

        headers["check_preload"] = "true"

        resp = http_requests.get(target_url, headers=headers, timeout=30)

        if len(resp.content) < 20:
            # Minimal response = error
            text = resp.content.decode('utf-8', errors='ignore')
            return error_response(502, f"TikTok API returned minimal response ({len(resp.content)} bytes): {text}")

        parsed = _parse_protobuf_episodes(resp.content)

        if not parsed["episodes"]:
            return error_response(502, f"No episodes found in response ({len(resp.content)} bytes). Signing headers may be expired.")

        # Build watch URLs
        for ep in parsed["episodes"]:
            if ep.get("video_url"):
                ep["watch"] = f"/pinedrama/watch?url={urllib.parse.quote(ep['video_url'], safe='')}"

        return json_response({
            "status": "success",
            "type": "proxy",
            "source": "collection_video",
            "collection_id": parsed["collection_id"],
            "title": parsed["title"],
            "total_episodes": parsed["total_episodes"],
            "episode_count": len(parsed["episodes"]),
            "covers": parsed["covers"],
            "episodes": parsed["episodes"],
        })

    except http_requests.exceptions.RequestException as e:
        return error_response(502, str(e))
    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/detail', methods=['GET'])
def detail():
    """Get drama detail + episode list via episode_panel (no signing needed).

    Query: id (collection_id), count (default 50, max 200).
    Returns: collection_id, title, cover, total_episodes, episode_list[{seq_id, num, video_id, is_paid, is_limited_free}].
    """
    collection_id = request.args.get('id', '')
    if not collection_id:
        return error_response(400, "Missing 'id' parameter")

    try:
        count = min(int(request.args.get('count', '50')), 200)
    except ValueError:
        count = 50

    try:
        panel = _api_request(PINEDRAMA_EPISODE_PANEL_BASE, {
            "collection_id": collection_id,
            "count": count,
            "cursor": 0,
        })

        if panel.get("status_code") != 0 or not panel.get("episode_list"):
            return error_response(502, panel.get("status_msg") or "Failed to fetch episode list")

        episode_list = panel["episode_list"]
        total = len(episode_list)

        # Enrich: try to find title/cover from trending/home cache
        # (episode_panel doesn't carry drama metadata)
        title = ""
        cover = ""
        try:
            home = _api_request(PINEDRAMA_BASE, {"scene": 1, "count": 50, "cursor": 0})
            for item in (home.get("collections") or []):
                if str(item.get("collection_id")) == collection_id:
                    title = item.get("title", "")
                    cover = (item.get("cover") or {}).get("url_list", [None])[0] or ""
                    break
        except Exception:
            pass

        episodes = [{
            "seq_id": ep.get("seq_id"),
            "num": ep.get("num"),
            "video_id": str(ep.get("video_id")) if ep.get("video_id") else None,
            "is_paid": ep.get("is_paid", False),
            "is_limited_free": ep.get("is_limited_free", False),
            "has_purchased": ep.get("has_purchased", False),
        } for ep in episode_list]

        return json_response({
            "type": "detail",
            "source": "episode_panel",
            "data": {
                "collection_id": collection_id,
                "title": title,
                "cover": cover,
                "total_episodes": total,
                "episodes": episodes,
            },
        })
    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/stream', methods=['GET', 'POST'])
def stream():
    """Proxy: forward signed collection/video request to TikTok, parse binary response.

    Query (GET): id (collection_id), ep (episode number, default 1).
    Headers (REQUIRED): x-argus, x-gorgon, x-ladon, x-khronos, cookie, x-tt-token.
    Body (POST): optional — pass raw signed request details as JSON.

    Returns parsed video URL for the requested episode.
    """
    collection_id = request.args.get('id') or request.args.get('collection_id') or ''
    if not collection_id:
        return error_response(400, "Missing 'id' parameter")

    try:
        ep_num = int(request.args.get('ep', request.args.get('episode', '1')))
    except ValueError:
        return error_response(400, "Invalid episode number")

    # Collect signing credentials from incoming request
    signing = {}
    for h in ("x-argus", "x-gorgon", "x-ladon", "x-khronos", "x-tt-token", "cookie"):
        val = request.headers.get(h) or request.args.get(h, "")
        if val:
            signing[h] = val

    # POST body can override
    if request.method == 'POST':
        body = request.get_json(force=True, silent=True) or {}
        for h in ("x-argus", "x-gorgon", "x-ladon", "x-khronos", "x-tt-token", "cookie"):
            if body.get(h):
                signing[h] = body[h]
        if body.get("collection_id"):
            collection_id = str(body["collection_id"])
        if body.get("ep"):
            ep_num = int(body["ep"])

    has_signing = signing.get("x-argus") or signing.get("x-gorgon")
    if not has_signing:
        return error_response(400,
            "Signing headers required: x-argus, x-gorgon, x-ladon, x-khronos, cookie. "
            "Capture these from a logged-in PineDrama app and forward them.")

    try:
        # Build the signed request
        base_url = PINEDRAMA_VIDEO_BASE
        params = DEVICE_PARAMS.copy()
        params.update(_ts_params())
        params.update({
            "collection_id": collection_id,
            "count": ep_num + 5,  # enough to reach the target episode
            "current_seq_id": "0",
            "current_session_ad_items": "",
            "current_session_block_ad_items": "",
            "direction": "1",
            "enter_from": "series_discover",
            "is_force_insert": "false",
            "is_trailer_paginated": "false",
            "last_feed_ad_items": "",
            "last_feed_items": "",
            "need_collection_detail": "true",
            "query_type": "last_watch",
            "query_scene": "mini_drama_container",
            "request_source": "innerfeed",
            "root_scene": "2",
            "video_id": "0",
        })

        headers = {
            "User-Agent": "com.ss.android.ttmd.video/2024502010 (Linux; U; Android 12; en_US; SM-A528B; Build/V417IR;tt-ok/3.12.13.21)",
            "Accept-Encoding": "gzip",
            "check_preload": "true",
            "sdk-version": "2",
            "x-tt-pba-enable": "1",
            "x-bd-kmsv": "0",
            "x-tt-dm-status": "login=1;ct=1;rt=1",
            "passport-sdk-version": "1",
            "x-vc-bdturing-sdk-version": "2.4.2.i18n",
            "x-tt-store-region": "id",
            "x-tt-store-region-src": "uid",
        }

        if signing.get("x-argus"):
            headers["X-Argus"] = signing["x-argus"]
        if signing.get("x-gorgon"):
            headers["X-Gorgon"] = signing["x-gorgon"]
        if signing.get("x-ladon"):
            headers["X-Ladon"] = signing["x-ladon"]
        if signing.get("x-khronos"):
            headers["X-Khronos"] = signing["x-khronos"]
        if signing.get("x-tt-token"):
            headers["X-Tt-Token"] = signing["x-tt-token"]
        if signing.get("cookie"):
            headers["Cookie"] = signing["cookie"]

        resp = http_requests.get(base_url, headers=headers, params=params, timeout=30)

        if resp.status_code != 200 or len(resp.content) < 100:
            return error_response(502, f"Upstream returned {resp.status_code} / {len(resp.content)} bytes")

        # Parse protobuf binary
        parsed = _parse_protobuf_episodes(resp.content)

        if not parsed["episodes"]:
            return error_response(502, "No episodes found in response — signing headers may be expired")

        # Find requested episode
        target_ep = None
        for ep in parsed["episodes"]:
            if ep.get("episode") == ep_num:
                target_ep = ep
                break

        if not target_ep:
            # fallback: return by index
            if ep_num <= len(parsed["episodes"]):
                target_ep = parsed["episodes"][ep_num - 1]
            else:
                target_ep = parsed["episodes"][-1]
                ep_num = len(parsed["episodes"])

        video_url = target_ep.get("video_url", "")
        watch_url = None
        if video_url:
            watch_url = f"/pinedrama/watch?url={urllib.parse.quote(video_url, safe='')}"

        return json_response({
            "type": "stream",
            "source": "proxy",
            "data": {
                "collection_id": collection_id,
                "episode": ep_num,
                "video_url": video_url,
                "watch_url": watch_url,
                "video_url_backup": target_ep.get("video_url_backup"),
                "duration": target_ep.get("duration"),
                "cover": target_ep.get("cover"),
                "title": parsed.get("title"),
                "total_available": len(parsed["episodes"]),
            },
        })
    except http_requests.exceptions.RequestException as e:
        return error_response(502, str(e))
    except Exception as e:
        return error_response(500, str(e))



@pinedrama_bp.route('/search', methods=['GET'])
def search():
    """
    Search mini dramas by keyword.

    Query params:
      - q: Search keyword (required)
      - page: Page number (default: 1)
      - count: Items per page (default: 20, max: 20)

    Example: GET /pinedrama/search?q=ceo&page=1&count=20
    """
    query = request.args.get('q', '')
    page = request.args.get('page', '1')
    count = request.args.get('count', '20')

    if not query:
        return error_response(400, "Missing 'q' parameter")

    try:
        count_int = min(int(count), 20)
        page_int = int(page)

        # Calculate cursor (0-indexed for search API)
        cursor = (page_int - 1) * count_int

        # Merge device params with search params
        all_params = DEVICE_PARAMS.copy()
        all_params.update(_ts_params())
        all_params.update({
            "cursor": str(cursor),
            "count": count_int,
            "keyword": query,
            "request_tag_from": "lynx",
        })

        headers = _get_headers()
        headers["content-type"] = "application/json"
        headers["agw-js-conv"] = "str"

        resp = http_requests.get(PINEDRAMA_SEARCH_BASE, headers=headers, params=all_params, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        # Transform response
        dramas = _transform_collections(result)

        # Fallback: If search returns empty, show home feed
        if not dramas and not result.get("has_more", False):
            fallback_params = {
                "cursor": "",
                "count": count_int,
                "category_id": "",
                "scene": "1",
                "is_validate": "0",
                "is_preload": "0",
                "is_mixed_column_page": "false",
            }
            fallback_result = _api_request(params=fallback_params)
            dramas = _transform_collections(fallback_result)

        return _pd_books_resp("search", dramas, query=query, page=page_int,
                              has_more=result.get("has_more", False),
                              cursor=result.get("cursor", 0))

    except http_requests.exceptions.RequestException as e:
        return error_response(500, str(e))
    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/home', methods=['GET'])
def home():
    """
    Get all mini dramas (home feed).

    Query params:
      - page: Page number (default: 1)
      - count: Items per page (default: 15, max: 20)

    Example: GET /pinedrama/home?page=1&count=15
    """
    page = request.args.get('page', '1')
    count = request.args.get('count', '15')

    try:
        count_int = min(int(count), 20)
        cursor = "" if page == "1" else f"page_{page}"

        params = {
            "cursor": cursor,
            "count": count_int,
            "category_id": "",
            "scene": "1",  # 1 = all/home
            "is_validate": "0",
            "is_preload": "0",
            "is_mixed_column_page": "false",
        }

        result = _api_request(params=params)

        if "error" in result:
            return error_response(500, result.get("error", "API request failed"))

        dramas = _transform_collections(result)

        return _pd_books_resp("home", dramas, page=int(page),
                              has_more=result.get("has_more", False),
                              cursor=result.get("cursor", ""))

    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/trending', methods=['GET'])
def trending():
    """
    Get trending mini dramas.

    Query params:
      - page: Page number (default: 1)
      - count: Items per page (default: 15, max: 20)

    Example: GET /pinedrama/trending?page=1&count=15
    """
    page = request.args.get('page', '1')
    count = request.args.get('count', '15')

    try:
        count_int = min(int(count), 20)
        cursor = "" if page == "1" else f"page_{page}"

        params = {
            "cursor": cursor,
            "count": count_int,
            "category_id": "",
            "scene": "2",  # 2 = trending
            "is_validate": "0",
            "is_preload": "0",
            "is_mixed_column_page": "false",
        }

        result = _api_request(params=params)

        if "error" in result:
            return error_response(500, result.get("error", "API request failed"))

        dramas = _transform_collections(result)

        return _pd_books_resp("trending", dramas, page=int(page),
                              has_more=result.get("has_more", False),
                              cursor=result.get("cursor", ""))

    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/category', methods=['GET'])
def category():
    """
    Get dramas by category.

    Query params:
      - id: Category ID (required)
      - page: Page number (default: 1)
      - count: Items per page (default: 15)

    Example: GET /pinedrama/category?id=7628991192533029889&page=1
    """
    category_id = request.args.get('id', '')
    page = request.args.get('page', '1')
    count = request.args.get('count', '15')

    if not category_id:
        return error_response(400, "Missing 'id' parameter")

    try:
        count_int = min(int(count), 20)
        cursor = "" if page == "1" else f"page_{page}"

        params = {
            "cursor": cursor,
            "count": count_int,
            "category_id": category_id,
            "scene": "3",  # 3 = category
            "is_validate": "0",
            "is_preload": "0",
            "is_mixed_column_page": "false",
        }

        result = _api_request(params=params)

        if "error" in result:
            return error_response(500, result.get("error", "API request failed"))

        dramas = _transform_collections(result)

        return json_response({
            "status": "success",
            "type": "category",
            "category_id": category_id,
            "page": int(page),
            "count": count_int,
            "has_more": result.get("has_more", False),
            "data": dramas,
        })

    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/category-list', methods=['GET'])
def category_list():
    """
    Get available categories/scenes.

    Example: GET /pinedrama/category-list
    """
    try:
        params = {
            "cursor": "",
            "count": "1",
            "category_id": "",
            "scene": "1",
            "is_validate": "0",
            "is_preload": "0",
            "is_mixed_column_page": "false",
        }

        result = _api_request(params=params)

        if "error" in result:
            return error_response(500, result.get("error", "API request failed"))

        scenes_list = result.get("scenes", [])

        return json_response({
            "status": "success",
            "type": "category-list",
            "scenes": scenes_list,
        })

    except Exception as e:
        return error_response(500, str(e))


@pinedrama_bp.route('/recommend', methods=['GET'])
def recommend():
    """
    Get recommended dramas. (Fallback to home feed since API requires signing)
    """
    return home()

@pinedrama_bp.route('/ranking', methods=['GET'])
def ranking():
    """
    Get ranked/popular mini dramas. (Fallback to trending since API requires signing)
    """
    return trending()


# App-standard aliases (Fi x Zam calls /populer and /new).
@pinedrama_bp.route('/populer', methods=['GET'])
def populer():
    return trending()


@pinedrama_bp.route('/new', methods=['GET'])
def new():
    return home()
