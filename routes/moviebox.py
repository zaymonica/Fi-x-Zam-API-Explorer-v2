"""
routes/moviebox.py — MovieBox (aoneroom / wefeed) ranking API
Proxy ke Supabase Edge Function milik user.
"""
import requests as http_requests
from flask import Blueprint, request

from utils import json_response

moviebox_bp = Blueprint('moviebox', __name__, url_prefix='/moviebox')

SUPABASE_BASE = "https://ovxlfhukkravtmoamjul.supabase.co/functions/v1/moviebox"

SUPABASE_HEADERS = {
    "User-Agent": "SonzaiX-API/1.0",
    "Accept": "application/json",
}

def _proxy(path: str = ""):
    """Forward request ke Supabase Edge Function."""
    url = f"{SUPABASE_BASE}{path}"
    try:
        if request.method == "POST":
            resp = http_requests.post(url, params=request.args, json=request.json, headers=SUPABASE_HEADERS, timeout=30)
        else:
            resp = http_requests.get(url, params=request.args, headers=SUPABASE_HEADERS, timeout=30)
            
        try:
            return json_response(resp.json(), resp.status_code)
        except Exception:
            return json_response({"error": "Invalid response from upstream", "detail": resp.text[:200]}, 502)
    except Exception as e:
        return json_response({"error": "Upstream request failed", "detail": str(e)}, 502)


@moviebox_bp.route('/', methods=['GET', 'POST'])
def moviebox_index():
    return _proxy("/")

@moviebox_bp.route('/<path:subpath>', methods=['GET', 'POST'])
def moviebox_proxy(subpath):
    return _proxy(f"/{subpath}")
