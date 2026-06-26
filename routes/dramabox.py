"""
routes/dramabox.py — DramaBox Short Drama API
Proxy ke Supabase Edge Function milik user.
"""
import requests as http_requests
from flask import Blueprint, request

from utils import json_response

dramabox_bp = Blueprint('dramabox', __name__)

SUPABASE_BASE = "https://snyvkmitfyayceevxfje.supabase.co/functions/v1/dramabox"

SUPABASE_HEADERS = {
    "User-Agent": "SonzaiX-API/1.0",
    "Accept": "application/json",
}


def _proxy(path: str = "", params: dict = None):
    """Forward request ke Supabase Edge Function."""
    url = f"{SUPABASE_BASE}{path}"
    try:
        resp = http_requests.get(url, params=params, headers=SUPABASE_HEADERS, timeout=30)
        try:
            return json_response(resp.json(), resp.status_code)
        except Exception:
            return json_response({"error": "Invalid response from upstream", "detail": resp.text[:200]}, 502)
    except Exception as e:
        return json_response({"error": "Upstream request failed", "detail": str(e)}, 502)


# ── Normalization → SonzaiXBox app shape ──────────────────────────────
# The app expects list endpoints to return data: [{ "books": [<MeloloBook>] }]
# (drama_id / drama_name / thumb_url / episode_count(str) / description /
# watch_value / tags). DramaBox's upstream wraps books in many container
# shapes (columnVoList[].bookList, *.records, searchList, tagBooks, ...).
# These helpers flatten any of them.
def _norm_book(b):
    tags = b.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    flat = []
    for t in tags:
        if isinstance(t, dict):
            n = t.get("tagName") or t.get("name") or t.get("labelName")
            if n:
                flat.append(n)
        elif t:
            flat.append(str(t))
    return {
        "drama_id": str(b.get("bookId") or ""),
        "drama_name": b.get("bookName") or "",
        "description": b.get("introduction") or "",
        "episode_count": str(b.get("chapterCount") or 0),
        "watch_value": str(b.get("playCount") or b.get("inLibraryCount") or ""),
        "is_new_book": "0",
        "language": "in",
        "thumb_url": b.get("coverWap") or b.get("cover") or b.get("image") or "",
        "tags": flat,
    }


def _collect_books(node, seen=None):
    """Recursively pull every dramabox book (has bookId + bookName) from any shape."""
    if seen is None:
        seen = set()
    out = []
    if isinstance(node, dict):
        if node.get("bookId") and node.get("bookName"):
            key = str(node.get("bookId"))
            if key not in seen:
                seen.add(key)
                out.append(node)
        else:
            for v in node.values():
                out.extend(_collect_books(v, seen))
    elif isinstance(node, list):
        for v in node:
            out.extend(_collect_books(v, seen))
    return out


def _proxy_list(params):
    """Proxy a list endpoint and reshape its data into the app's [{books:[...]}]."""
    url = SUPABASE_BASE
    try:
        resp = http_requests.get(url, params=params, headers=SUPABASE_HEADERS, timeout=30)
        try:
            body = resp.json()
        except Exception:
            return json_response({"error": "Invalid response from upstream", "detail": resp.text[:200]}, 502)
    except Exception as e:
        return json_response({"error": "Upstream request failed", "detail": str(e)}, 502)

    raw = body.get("data") if isinstance(body, dict) else body
    books = [_norm_book(b) for b in _collect_books(raw)]
    return json_response({
        "author": "Sonzai X シ",
        "contact": "https://t.me/November2k",
        "data": [{"books": books}],
    })


# ─── Routes ───────────────────────────────────────────────────────────

@dramabox_bp.route('/dramabox/home', methods=['GET'])
def dramabox_home():
    page = request.args.get('page', '1')
    lang = request.args.get('lang', 'in')
    return _proxy_list(params={'home': '', 'page': page, 'lang': lang})


@dramabox_bp.route('/dramabox/new', methods=['GET'])
def dramabox_new():
    page = request.args.get('page', '1')
    lang = request.args.get('lang', 'in')
    return _proxy_list(params={'new': '', 'page': page, 'lang': lang})


@dramabox_bp.route('/dramabox/populer', methods=['GET'])
def dramabox_populer():
    page = request.args.get('page', '1')
    lang = request.args.get('lang', 'in')
    return _proxy_list(params={'populer': '', 'page': page, 'lang': lang})


@dramabox_bp.route('/dramabox/rank', methods=['GET'])
def dramabox_rank():
    lang = request.args.get('lang', 'in')
    return _proxy(params={'rank': '', 'lang': lang})


@dramabox_bp.route('/dramabox/category', methods=['GET'])
def dramabox_category():
    page     = request.args.get('page', '1')
    lang     = request.args.get('lang', 'in')
    category = request.args.get('category', 'cina')
    return _proxy(params={'category': category, 'page': page, 'lang': lang})


@dramabox_bp.route('/dramabox/search', methods=['GET'])
def dramabox_search():
    q    = request.args.get('q', '') or request.args.get('query', '')
    page = request.args.get('page', '1')
    lang = request.args.get('lang', 'in')
    if not q:
        return json_response({"error": "Provide ?q=keyword"}, 400)
    return _proxy_list(params={'search': q, 'page': page, 'lang': lang})


@dramabox_bp.route('/dramabox/detail', methods=['GET'])
@dramabox_bp.route('/dramabox/detail/<path:book_id_path>', methods=['GET'])
def dramabox_detail(book_id_path=None):
    book_id = book_id_path or request.args.get('bookId') or request.args.get('id') or ''
    lang    = request.args.get('lang', 'in')
    if not book_id:
        return json_response({"error": "Provide bookId"}, 400)
    try:
        resp = http_requests.get(f"{SUPABASE_BASE}/detail",
                                 params={'bookId': book_id, 'lang': lang},
                                 headers=SUPABASE_HEADERS, timeout=30)
        body = resp.json()
    except Exception as e:
        return json_response({"error": "Upstream request failed", "detail": str(e)}, 502)

    raw = body.get("data") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return json_response(body, resp.status_code)

    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    flat = [t.get("tagName") if isinstance(t, dict) else str(t) for t in tags]
    flat = [t for t in flat if t]

    # Upstream detail has no chapter list; the app's stream call addresses
    # episodes by index, so synthesize a 0..N-1 chapter list from chapterCount.
    count = raw.get("chapterCount") or 0
    chapter_list = [{"chapterId": str(i), "chapterIndex": i} for i in range(count)]

    merged = {
        "drama_id": str(raw.get("bookId") or book_id),
        "drama_name": raw.get("bookName") or "",
        "description": raw.get("introduction") or "",
        "episode_count": count,
        "chapterList": chapter_list,
        "tags": flat,
    }
    merged.update({k: v for k, v in raw.items() if k not in merged})

    return json_response({
        "author": "Sonzai X シ",
        "contact": "https://t.me/November2k",
        "data": merged,
    })


@dramabox_bp.route('/dramabox/stream', methods=['GET'])
def dramabox_stream():
    book_id       = request.args.get('bookId') or request.args.get('id') or ''
    chapter_index = request.args.get('chapterIndex', '0')
    lang          = request.args.get('lang', 'in')
    if not book_id:
        return json_response({"error": "Provide bookId"}, 400)
    try:
        idx = int(chapter_index)
    except ValueError:
        idx = 0
    try:
        resp = http_requests.get(f"{SUPABASE_BASE}/stream",
                                 params={'bookId': book_id, 'chapterIndex': chapter_index, 'lang': lang},
                                 headers=SUPABASE_HEADERS, timeout=30)
        body = resp.json()
    except Exception as e:
        return json_response({"error": "Upstream request failed", "detail": str(e)}, 502)

    raw = body.get("data") if isinstance(body, dict) else None
    if not isinstance(raw, dict):
        return json_response(body, resp.status_code)

    # Pick the requested chapter, then flatten cdnList[].videoPathList into the
    # app's flat qualities[{quality, videoPath, isDefault}].
    chapters = raw.get("chapterList") or []
    chapter = next((c for c in chapters if c.get("chapterIndex") == idx), None) \
        or (chapters[0] if chapters else {})

    qualities = []
    for cdn in chapter.get("cdnList") or []:
        cdn_default = cdn.get("isDefault", 0)
        for vp in cdn.get("videoPathList") or []:
            url = vp.get("videoPath")
            if not url:
                continue
            qualities.append({
                "quality": vp.get("quality") or 0,
                "videoPath": url,
                "isDefault": vp.get("isDefault") or cdn_default or 0,
            })
        if qualities:
            break  # first (usually default) cdn is enough

    video_url = ""
    if qualities:
        default = next((q for q in qualities if q["isDefault"]), None)
        video_url = (default or qualities[0])["videoPath"]

    return json_response({
        "author": "Sonzai X シ",
        "contact": "https://t.me/November2k",
        "data": {
            "bookId": book_id,
            "chapterIndex": idx,
            "videoUrl": video_url,
            "cover": chapter.get("chapterImg"),
            "qualities": qualities,
        },
    })


@dramabox_bp.route('/dramabox/languages', methods=['GET'])
def dramabox_languages():
    return _proxy(params={'languages': ''})
