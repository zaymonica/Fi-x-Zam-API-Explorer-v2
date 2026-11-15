"""sonzai_bridge.py — Bridge blueprint: proxy endpoint Sonzai Aggregator.

Tujuan: bikin SEMUA provider di Fi-x-Zam hijau. Provider yang di Fi-x-Zam error
(atasan upstream mati / video locked / belum ada) di-bridge ke backend Sonzai
Aggregator (FastAPI di :8585) yang udah terbukti hijau.

Alur tetap gaya Fi-x-Zam (Flask + API Explorer), tapi sumber data = Sonzai.
Endpoint: /api/<provider>/<resource>  ->  proxy ke  SONZAI/api/<provider>/<resource>

Catatan:
- Sonzai pakai prefix /api/<provider>/...
- Semua method (GET) di-forward utuh (path + query string).
- Respons dibungkus gaya Fi-x-Zam (author/contact) biar konsisten.
"""
import os
import requests
from flask import Blueprint, request, Response
from utils import json_response

SONZAI_BASE = os.getenv("SONZAI_BASE", "http://127.0.0.1:8585")

sonzai_bp = Blueprint("sonzai_bridge", __name__)

# Provider yang di-bridge ke Sonzai (yang hijau di Sonzai)
BRIDGED = {
    "reelshort", "melolo", "goodshort", "cashdrama",
    "dramabox", "dramanova", "shortmax", "rapidtv",
}

# Host CDN gambar yang di-whitelist Sonzai (biar /img tetap lewat Sonzai)
TIMEOUT = 60


def _wrap(data, status=200):
    """Bungkus respons gaya Fi-x-Zam."""
    if isinstance(data, dict):
        payload = {"author": "Fi x Zam シ", "source": "sonzai-aggregator"}
        payload.update(data)
        return json_response(payload, status)
    return Response(data, status=status, mimetype="application/json")


@sonzai_bp.route("/api/<provider>/<path:resource>", methods=["GET"])
def bridge(provider, resource):
    if provider not in BRIDGED:
        return json_response({"error": f"provider '{provider}' bukan bagian dari bridge Sonzai"}, 404)

    # forward query string utuh
    url = f"{SONZAI_BASE}/api/{provider}/{resource}"
    try:
        r = requests.get(url, params=request.args, headers={
            "User-Agent": "Mozilla/5.0 (Fi-x-Zam bridge)",
            "Accept": "application/json",
        }, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        return json_response({"error": f"upstream Sonzai timeout: {provider}/{resource}"}, 504)
    except Exception as e:
        return json_response({"error": f"bridge error: {type(e).__name__}: {e}"}, 502)

    ct = r.headers.get("content-type", "")
    # JSON -> bungkus; binary (gambar/video) -> teruskan mentah
    if "application/json" in ct:
        try:
            return _wrap(r.json(), r.status_code)
        except Exception:
            return Response(r.content, status=r.status_code, mimetype="application/json")
    return Response(r.content, status=r.status_code, mimetype=ct or "application/octet-stream")


@sonzai_bp.route("/api/<provider>", methods=["GET"])
def bridge_root(provider):
    """List provider tanpa resource -> arahkan ke home."""
    return bridge(provider, "home")


@sonzai_bp.route("/img", methods=["GET"])
def bridge_img():
    """Proxy gambar lewat Sonzai (whitelist CDN ada di Sonzai)."""
    url = request.args.get("url", "")
    if not url:
        return json_response({"error": "url required"}, 400)
    try:
        r = requests.get(f"{SONZAI_BASE}/img", params={"url": url}, headers={
            "User-Agent": "Mozilla/5.0 (Fi-x-Zam bridge)",
        }, timeout=TIMEOUT)
    except Exception as e:
        return json_response({"error": f"bridge img error: {e}"}, 502)
    return Response(r.content, status=r.status_code,
                    mimetype=r.headers.get("content-type", "image/jpeg"))
