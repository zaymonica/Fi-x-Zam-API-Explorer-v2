#!/usr/bin/env python3
"""GGReels blueprint — provider drama Sub Indo (tanpa proxy sonzaix).
Endpoints:
  GET /ggreels/home                → katalog
  GET /ggreels/detail?id=<ID>      → detail + episode list
  GET /ggreels/download?id=<ID>    → download/serve video MP4 (cache)
  GET /ggreels/search?q=<keyword>  → cari drama
"""
import os
from flask import Blueprint, request, send_file
from utils import json_response
import ggreels_core as g

ggreels_bp = Blueprint("ggreels_bp", __name__)

AUTHOR = "Fi x Zam シ"


def _wrap(data):
    return json_response({"author": AUTHOR, "source": "ggreels", **data})


@ggreels_bp.route("/ggreels/home", methods=["GET"])
def home():
    try:
        cat = g.catalog()
        return _wrap({"type": "catalog", "count": len(cat), "items": cat})
    except Exception as e:
        return json_response({"error": f"ggreels: {type(e).__name__}: {e}"}, 502)


@ggreels_bp.route("/ggreels/detail", methods=["GET"])
@ggreels_bp.route("/ggreels/episodes", methods=["GET"])
def detail():
    did = request.args.get("id") or request.args.get("drama_id")
    if not did:
        return json_response({"error": "id required"}, 400)
    try:
        eps = g.episodes(did)
        return _wrap({"type": "detail", "data": eps})
    except Exception as e:
        return json_response({"error": f"ggreels: {type(e).__name__}: {e}"}, 502)


@ggreels_bp.route("/ggreels/search", methods=["GET"])
def search():
    q = request.args.get("q") or request.args.get("keyword") or ""
    try:
        cat = g.catalog()
        ql = q.lower()
        items = [d for d in cat if ql in (d.get("title") or "").lower()]
        return _wrap({"type": "search", "q": q, "count": len(items), "items": items})
    except Exception as e:
        return json_response({"error": f"ggreels: {type(e).__name__}: {e}"}, 502)


@ggreels_bp.route("/ggreels/download", methods=["GET"])
@ggreels_bp.route("/ggreels/video", methods=["GET"])
def download():
    did = request.args.get("id") or request.args.get("drama_id")
    if not did:
        return json_response({"error": "id required"}, 400)
    try:
        path = g.get_video(did)
        if path and os.path.exists(path):
            return send_file(path, mimetype="video/mp4", as_attachment=False)
        return json_response({"error": "no video"}, 502)
    except Exception as e:
        return json_response({"error": f"ggreels download: {type(e).__name__}: {e}"}, 502)
