"""
routes/anime.py — Anime Lover V3 (migrated from backend/anime.js)
"""
import json
import requests as http_requests
from flask import Blueprint, request
from urllib.parse import quote

from utils import json_response, error_response

anime_bp = Blueprint('anime', __name__)

API_BASE = 'https://apps.animekita.org/api/v1.2.5'
H = {'User-Agent':'Dart/3.9 (dart:io)','Accept':'application/json','Accept-Encoding':'gzip'}
HP = {**H,'Content-Type':'text/plain; charset=utf-8'}
HS = {'User-Agent':'Flutter/2.5.3','Accept':'application/json','Accept-Encoding':'gzip','Content-Type':'text/plain; charset=utf-8'}

def fa(url, **kw):
    r = http_requests.request(kw.get('method','GET'), url, headers=kw.get('headers',H), data=kw.get('data'), timeout=15)
    return r.json()

@anime_bp.route('/anime', defaults={'subpath':''}, methods=['GET','POST'])
@anime_bp.route('/anime/<path:subpath>', methods=['GET','POST'])
def handle_anime(subpath):
    path = f'/{subpath}' if subpath else ''
    try:
        if path == '/home':
            pg = request.args.get('page','1')
            return json_response(fa(f"{API_BASE}/baruupload.php?page={pg}", headers=H))
        if path == '/ongoing':
            return json_response(fa(f"{API_BASE}/home/ongoing.php?type=anime", headers=H))
        if path == '/jadwal':
            return json_response(fa(f"{API_BASE}/jadwal.php", method='POST', headers=H))
        if path == '/anime-list':
            return json_response(fa(f"{API_BASE}/anime-list.php", headers=H))
        if path == '/search':
            q = request.args.get('query') or request.args.get('q')
            pg = request.args.get('page','1')
            if not q: return json_response({'status':False,'message':"Parameter 'query' wajib diisi"},400)
            return json_response(fa(f"{API_BASE}/search.php?keyword={quote(q)}&page={pg}&per_page=20", headers=H))
        if path == '/detail':
            series = request.args.get('series')
            if not series: return json_response({'status':False,'message':"Parameter 'series' wajib diisi"},400)
            body = json.dumps({"get":"top","post_type":"1","post_id":series,"token":""})
            return json_response(fa(f"{API_BASE}/series.php?url={quote(series)}", method='POST', headers=HP, data=body))
        if path == '/stream':
            slug = request.args.get('slug')
            series = request.args.get('series','')
            episode = request.args.get('episode','1')
            if not slug: return json_response({'status':False,'message':"Parameter 'slug' wajib diisi"},400)
            body = json.dumps({"post_type":"2","post_id":slug,"series_id":series,"series_url":series,"episode":episode,"token":""})
            return json_response(fa(f"{API_BASE}/series/episode/data.php?url={quote(slug)}", method='POST', headers=HS, data=body))
    except Exception as e:
        return json_response({'status':False,'error':str(e)},500)
    return error_response(404,'Anime Endpoint Not Found')
