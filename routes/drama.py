"""
routes/drama.py — Drama (Drakor) handler
Proxy ke api.drakor.la v2 REST API — raw response (tanpa parsing).
"""
import requests as http_requests
from flask import Blueprint, request

from utils import json_response, error_response

drama_bp = Blueprint('drama', __name__)

API_BASE = "https://api.drakor.la/v2"
AUTH_TOKEN = (
    "QJxcWdaEayEePQyIk51TnoTBBqB-I3MFfDry-81U_3SOwvHzFzhVHv_PhE4hpGK4"
    "_p3hJ32r-Lj1DPaeB7ZOslz_2AeyG1BjsziQH0kSrZJ6S3adzJCwoWf6qvROrXreB"
    "k5qs39dzlrHnDJe2KwEVS7j7Ml7qFf_fbJpw_-MRD7ilFkK_v0Ql5sI3OQb3pG3Aw"
    "FZ6eR64RbB4tMEq9TYscXrFpHChx3qvyS5RYx3pS9EB02x9xXGeAoUIhiJzhuggXR"
    "ZDpVXGSAdNbmwXr8It3Od1lVfDWmTykZf"
)

API_HEADERS = {
    "User-Agent": "Dart/3.9 (dart:io)",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "authorization": AUTH_TOKEN,
    "content-type": "application/json",
    "x-app-package": "net.drakorid.app",
    "x-app-version": "7.2",
    "platform": "Mobile",
}

TIMEOUT = 30


def _api_get(path, params=None):
    """GET request ke api.drakor.la."""
    url = f"{API_BASE}{path}"
    resp = http_requests.get(url, params=params, headers=API_HEADERS, timeout=TIMEOUT)
    return resp


def _raw_proxy(resp):
    """Return upstream response as-is (raw JSON)."""
    try:
        return json_response(resp.json(), resp.status_code)
    except Exception:
        return json_response({"error": "Invalid response from upstream", "detail": resp.text[:200]}, 502)


# ─── Routes ──────────────────────────────────────────────────────────────

@drama_bp.route('/drama', defaults={'subpath': ''}, methods=['GET'])
@drama_bp.route('/drama/<path:subpath>', methods=['GET'])
def handle_drama(subpath):
    path = f'/{subpath}' if subpath else ''
    try:
        # ── Home China ──────────────────────────────────────────────────
        if path == '/home/china':
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            sort = request.args.get('sort', 'LATEST')
            resp = _api_get('/movies/category', params={
                'page': page, 'limit': limit,
                'category_name': 'Drama China', 'sort': sort,
            })
            return _raw_proxy(resp)

        # ── Home Korea ──────────────────────────────────────────────────
        if path == '/home/korea':
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            sort = request.args.get('sort', 'LATEST')
            resp = _api_get('/movies/category', params={
                'page': page, 'limit': limit,
                'category_name': 'Drama Korea', 'sort': sort,
            })
            return _raw_proxy(resp)

        # ── Terbaru ─────────────────────────────────────────────────────
        if path == '/terbaru':
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            resp = _api_get('/movies/latest-on1', params={
                'page': page, 'limit': limit,
            })
            return _raw_proxy(resp)

        # ── Trending ────────────────────────────────────────────────────
        if path == '/trending':
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            days = request.args.get('days', '30')
            resp = _api_get('/movies/trending', params={
                'page': page, 'limit': limit, 'days': days,
            })
            return _raw_proxy(resp)

        # ── Ongoing ─────────────────────────────────────────────────────
        if path == '/ongoing':
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            resp = _api_get('/movies/ongoing', params={
                'page': page, 'limit': limit,
            })
            return _raw_proxy(resp)

        # ── Category List ───────────────────────────────────────────────
        if path == '/category-list':
            resp = _api_get('/category/get-with-stats')
            return _raw_proxy(resp)

        # ── Category ────────────────────────────────────────────────────
        if path == '/category' or path.startswith('/category'):
            category_name = request.args.get('category_name') or request.args.get('kategori') or request.args.get('q')
            if not category_name:
                return json_response({"status": False, "message": "Parameter 'category_name' wajib diisi"}, 400)
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            sort = request.args.get('sort', 'LATEST')
            resp = _api_get('/movies/category', params={
                'page': page, 'limit': limit,
                'category_name': category_name, 'sort': sort,
            })
            return _raw_proxy(resp)

        # ── Search ──────────────────────────────────────────────────────
        if path == '/search' or path.startswith('/search'):
            q = request.args.get('q')
            if not q:
                return json_response({"status": False, "message": "Parameter 'q' wajib diisi"}, 400)
            page = request.args.get('page', '1')
            limit = request.args.get('limit', '30')
            type_ = request.args.get('type', '1')
            order = request.args.get('order', '1')
            resp = _api_get('/movies/search', params={
                'page': page, 'q': q, 'limit': limit,
                'type': type_, 'order': order,
            })
            return _raw_proxy(resp)

        # ── Detail ──────────────────────────────────────────────────────
        if path == '/detail' or path.startswith('/detail'):
            id_ = request.args.get('id')
            if not id_:
                return json_response({"status": False, "message": "Parameter 'id' wajib diisi"}, 400)

            # Fetch info, artists, episodes
            info_resp = _api_get('/movies/get-info', params={'id': id_})
            artist_resp = _api_get('/artist/get-list', params={'movie_id': id_})
            episodes_resp = _api_get('/movies/get-episodes', params={'id': id_})

            try:
                info_data = info_resp.json()
            except Exception:
                info_data = {"error": "Invalid response"}
            try:
                artist_data = artist_resp.json()
            except Exception:
                artist_data = {"error": "Invalid response"}
            try:
                episodes_data = episodes_resp.json()
            except Exception:
                episodes_data = {"error": "Invalid response"}

            return json_response({
                "info": info_data,
                "artists": artist_data,
                "episodes": episodes_data,
            })

        # ── Stream ──────────────────────────────────────────────────────
        if path == '/stream' or path.startswith('/stream'):
            streaming_id = request.args.get('streaming') or request.args.get('id')
            if not streaming_id:
                return json_response({"status": False, "message": "Parameter 'streaming' wajib diisi"}, 400)

            resp = _api_get('/generate-link/play-lite', params={
                'streaming': streaming_id,
            })
            return _raw_proxy(resp)

    except http_requests.RequestException as e:
        return json_response({"status": False, "error": f"Network error: {e}"}, 502)
    except Exception as e:
        return json_response({"status": False, "error": str(e)}, 500)

    return error_response(404, 'Drama Endpoint Not Found')
