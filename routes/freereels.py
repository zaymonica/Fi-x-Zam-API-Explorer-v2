"""
routes/freereels.py — FreeReels Short Drama
"""
from flask import Blueprint, request, Response
import requests
import time
import uuid
import re
from urllib.parse import urlparse
from utils import json_response, error_response

freereels_bp = Blueprint('freereels', __name__, url_prefix='/freereels')

UPSTREAM_BASE = "https://apiv2.free-reels.com/frv2-api"

FREEREELS_LANGS = {
    "id": {"code": "id-ID", "name": "Indonesia"},
    "en": {"code": "en-US", "name": "English"},
    "es": {"code": "es-MX", "name": "Español"},
    "pt": {"code": "pt-PT", "name": "Português"},
    "de": {"code": "de-DE", "name": "Deutsch"},
    "fr": {"code": "fr-FR", "name": "Français"},
    "ru": {"code": "ru-RU", "name": "Русский"},
    "it": {"code": "it-IT", "name": "Italiano"},
    "tr": {"code": "tr-TR", "name": "Türkçe"},
    "ja": {"code": "ja-JP", "name": "日本語"},
    "ko": {"code": "ko-KR", "name": "한국어"},
    "th": {"code": "th-TH", "name": "ไทย"},
    "vi": {"code": "vi-VN", "name": "Tiếng Việt"},
    "tl": {"code": "tl-PH", "name": "Filipino"},
    "ms": {"code": "ms-MY", "name": "Melayu"},
    "zh": {"code": "zh-TW", "name": "中文"},
    "hi": {"code": "hi-IN", "name": "हिन्दी"},
    "ta": {"code": "ta-IN", "name": "தமிழ்"},
    "te": {"code": "te-IN", "name": "తెలుగు"},
    "bn": {"code": "bn-BD", "name": "বাংলা"},
    "pl": {"code": "pl-PL", "name": "Polski"},
    "ar": {"code": "ar-SA", "name": "العربية"},
}

def get_lang_code():
    lang = request.args.get('lang', 'id').lower()
    return FREEREELS_LANGS.get(lang, FREEREELS_LANGS["id"])["code"]

def upstream_headers(content_type="application/json", lang_code="id-ID"):
    return {
        "User-Agent": "okhttp/4.12.0",
        "Accept": "application/json",
        "country": "US",
        "timezone": "+7",
        "device-country": "US",
        "language": lang_code,
        "device-id": "494f766ec3cf85ce",
        "Authorization": "oauth_signature=05723f14833e7725c2fce460660f689f,oauth_token=vpY7pH4RaPkryly1n3Gxsvd7O7Uvv2dW,ts=1777926144758",
        "device-version": "32",
        "app-name": "com.freereels.app",
        "app-version": "2.2.81",
        "device": "android",
        "session-id": "545957fe-65f0-480f-991b-b847bbb31ca2",
        "Content-Type": content_type,
        "x-appsflyer_id": "1777924814767-4458621609014671597",
        "gaid": "ccd3aa81-5be0-44ab-9ad3-65ab8b15d3ea",
        "firebase-id": "5350f0af4d2d1efdfd1ce544c9ba2bf8",
    }

def format_drama(item):
    tags_list = item.get("tag", []) or []
    content_tags = item.get("content_tags", []) or []
    series_tags = item.get("series_tag", []) or []
    
    tags = []
    for t in (tags_list + content_tags + series_tags):
        if t and str(t).strip() and str(t).strip() not in tags:
            tags.append(str(t).strip())
            
    return {
        "drama_name": item.get("title") or item.get("name") or "",
        "drama_id": item.get("key") or item.get("id") or "",
        "description": item.get("desc") or "",
        "episode_count": item.get("episode_count") or 0,
        "watch_value": str(item.get("follow_count") or item.get("view_count") or "0"),
        "thumb_url": item.get("cover") or "",
        "tags": tags,
        "free": item.get("free", False),
    }

def convert_srt_to_vtt(srt):
    vtt = "WEBVTT\n\n"
    lines = srt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.isdigit():
            i += 1
            continue
        if " --> " in line:
            vtt += line.replace(",", ".") + "\n"
            i += 1
            while i < len(lines) and lines[i].strip() != "" and " --> " not in lines[i] and not lines[i].strip().isdigit():
                vtt += lines[i] + "\n"
                i += 1
            vtt += "\n"
        else:
            i += 1
    return vtt

def extract_items(data):
    items = data.get("data", {}).get("items", [])
    if not items:
        return []
    
    if items[0].get("module_key") or items[0].get("module_type") is not None:
        flat_items = []
        for m in items:
            flat_items.extend(m.get("items", []))
        return flat_items
    
    return items


@freereels_bp.route('/languages', methods=['GET'])
def languages():
    return json_response({
        "type": "languages",
        "total": len(FREEREELS_LANGS),
        "data": [{"code": k, "name": v["name"]} for k, v in FREEREELS_LANGS.items()]
    })

@freereels_bp.route('/home', methods=['GET'])
def home():
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)
    lang_code = get_lang_code()
    
    page_size = 10
    offset = (page - 1) * page_size
    next_param = "" if page == 1 else f"offset={offset}"
    
    url = f"{UPSTREAM_BASE}/foryou/feed?next={requests.utils.quote(next_param)}"
    try:
        r = requests.get(url, headers=upstream_headers("application/json", lang_code), timeout=10)
        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")
        data = r.json()
        if data.get("code") != 200:
            return error_response(502, data.get("message", "Upstream Error"))
            
        items = data.get("data", {}).get("items", [])
        has_more = data.get("data", {}).get("page_info", {}).get("has_more", False)
        books = [format_drama(item) for item in items]
        
        return json_response({
            "type": "home",
            "has_more": has_more,
            "page": page,
            "data": [{"books": books}] if books else []
        })
    except Exception as e:
        return error_response(500, str(e))


def handle_tab(type_str, tab_key, module_key, page, lang_code):
    page_size = 10
    offset = (page - 1) * page_size
    
    try:
        if page == 1:
            url = f"{UPSTREAM_BASE}/homepage/v2/tab/index?tab_key={tab_key}&position_index=10000&rec_trigger=1"
            r = requests.get(url, headers=upstream_headers("application/json", lang_code), timeout=10)
        else:
            if type_str == "new":
                next_param = f"last_quality=0&offset={offset}&position_index=10000&timestamp="
            else:
                next_param = f"offset={offset}&position_index=10000"
            
            body = {
                "next": next_param,
                "module_key": module_key
            }
            r = requests.post(f"{UPSTREAM_BASE}/homepage/v2/tab/feed", 
                              headers=upstream_headers("application/json; charset=UTF-8", lang_code),
                              json=body, timeout=10)
        
        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")
            
        data = r.json()
        if data.get("code") != 200:
            return error_response(502, data.get("message", "Upstream Error"))
            
        items = extract_items(data)
        page_info = data.get("data", {}).get("page_info", {})
        has_more = page_info.get("has_more") if page_info.get("has_more") is not None else (len(items) >= page_size)
        
        books = [format_drama(item) for item in items]
        return json_response({
            "type": type_str,
            "has_more": has_more,
            "page": page,
            "data": [{"books": books}] if books else []
        })
    except Exception as e:
        return error_response(500, str(e))

@freereels_bp.route('/populer', methods=['GET'])
def populer():
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)
    return handle_tab("populer", "503", "1036", page, get_lang_code())

@freereels_bp.route('/new', methods=['GET'])
def new():
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)
    return handle_tab("new", "505", "1040", page, get_lang_code())

@freereels_bp.route('/search', methods=['GET'])
def search():
    keyword = request.args.get('q', request.args.get('query', ''))
    page = request.args.get('page', 1, type=int)
    page = max(page, 1)
    if not keyword:
        return error_response(400, "Query Missing")
        
    lang_code = get_lang_code()
    page_size = 20
    offset = (page - 1) * page_size
    next_param = "" if page == 1 else f"offset={offset}&page_size={page_size}"
    
    body = {
        "next": next_param,
        "keyword": keyword,
        "timestamp": str(int(time.time() * 1000))
    }
    
    url = f"{UPSTREAM_BASE}/search/drama"
    try:
        r = requests.post(url, headers=upstream_headers("application/json; charset=UTF-8", lang_code), json=body, timeout=10)
        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")
        
        data = r.json()
        if data.get("code") != 200:
            return error_response(502, data.get("message", "Upstream Error"))
            
        items = data.get("data", {}).get("items", [])
        has_more = data.get("data", {}).get("page_info", {}).get("has_more", False)
        
        books = [format_drama(item) for item in items]
        return json_response({
            "type": "search",
            "has_more": has_more,
            "page": page,
            "data": [{"books": books}] if books else []
        })
    except Exception as e:
        return error_response(500, str(e))

@freereels_bp.route('/detail', methods=['GET'])
def detail():
    drama_id = request.args.get('dramaId', request.args.get('id', ''))
    if not drama_id:
        return error_response(400, "dramaId Missing")
        
    lang_code = get_lang_code()
    # Use the upstream API directly
    url = f"{UPSTREAM_BASE}/drama/info_v2?series_id={requests.utils.quote(drama_id)}&scene=&clip_content=&campaign="
    
    try:
        r = requests.get(url, headers=upstream_headers("application/json", lang_code), timeout=10)
        if r.status_code != 200:
            return error_response(r.status_code, "Upstream Error")
            
        data = r.json()
        if data.get("code") != 200:
            return error_response(502, data.get("message", "Upstream Error"))
            
        drama = data.get("data", {}).get("info", {})
        if not drama:
            # Fallback if the structure is different
            drama = data.get("data", {})
            
        ep_list = drama.get("episode_list", [])
        
        tags_list = drama.get("tag", []) or []
        content_tags = drama.get("content_tags", []) or []
        
        tags = []
        for t in (tags_list + content_tags):
            if t and str(t).strip() and str(t).strip() not in tags:
                tags.append(str(t).strip())
                
        episode_list = []
        for ep in ep_list:
            episode_list.append({
                "episode": ep.get("index", ep.get("episode_num", 0)),
                "episode_id": ep.get("id", ep.get("key", "")),
                "name": ep.get("name", ""),
                "unlock": ep.get("unlock", False),
            })
            
        return json_response({
            "type": "detail",
            "data": {
                "drama_id": drama.get("id") or drama.get("key") or drama_id,
                "drama_name": drama.get("name") or drama.get("title", ""),
                "description": drama.get("desc", ""),
                "episode_count": drama.get("episode_count") or len(ep_list),
                "watch_value": str(drama.get("follow_count", "0")),
                "thumb_url": drama.get("cover", ""),
                "tags": tags,
                "free": drama.get("free", False),
                "episode_list": episode_list,
            }
        })
    except Exception as e:
        return error_response(500, str(e))

@freereels_bp.route('/stream', methods=['GET'])
def stream():
    drama_id = request.args.get('dramaId', request.args.get('id', ''))
    episode = request.args.get('episode', '')
    if not drama_id:
        return error_response(400, "dramaId Missing")
    if not episode:
        return error_response(400, "episode Missing")
        
    lang_code = get_lang_code()
    
    try:
        # 1. Fetch info_v2 to map numeric episode to actual episode_id and check if already unlocked
        info_url = f"{UPSTREAM_BASE}/drama/info_v2?series_id={requests.utils.quote(drama_id)}&scene=&clip_content=&campaign="
        info_r = requests.get(info_url, headers=upstream_headers("application/json", lang_code), timeout=10)
        
        ep_data = {}
        target_ep_id = episode
        if info_r.status_code == 200:
            info_json = info_r.json()
            if info_json.get("code") == 200:
                ep_list = info_json.get("data", {}).get("info", {}).get("episode_list", [])
                for ep in ep_list:
                    if str(ep.get("index")) == str(episode) or str(ep.get("episode_num")) == str(episode) or str(ep.get("id")) == str(episode):
                        target_ep_id = ep.get("id", episode)
                        ep_data = ep
                        break
                        
        stream_url = ep_data.get("m3u8_url") or ep_data.get("video_url") or ep_data.get("external_audio_h264_m3u8")
        
        # 2. If it's locked or missing URL, call unlock_episode
        if not stream_url:
            url = f"{UPSTREAM_BASE}/drama/unlock_episode"
            body = {
                "series_id": drama_id,
                "episode_id": target_ep_id,
                "auto_unlock": 1,
                "check_auto_unlock": False,
                "diamond_auto_unlock": False,
                "check_diamond_auto_unlock": False
            }
            r = requests.post(url, headers=upstream_headers("application/json; charset=UTF-8", lang_code), json=body, timeout=10)
            if r.status_code != 200:
                return error_response(r.status_code, "Upstream Error")
                
            data = r.json()
            if data.get("code") != 200:
                return error_response(502, data.get("message", "Upstream Error"))
                
            ep_data = data.get("data", {})
            
        subtitles = []
        for s in ep_data.get("subtitle_list", []):
            subtitles.append({
                "language": s.get("language", ""),
                "type": s.get("type", ""),
                "url": s.get("url", s.get("subtitle", s.get("vtt", ""))),
                "display_name": s.get("display_name", "")
            })
            
        stream_url = ep_data.get("m3u8_url") or ep_data.get("video_url") or ep_data.get("external_audio_h264_m3u8") or ep_data.get("playload", {}).get("m3u8_url")
            
        return json_response({
            "type": "stream",
            "data": {
                "episode_id": ep_data.get("id", target_ep_id),
                "name": ep_data.get("name", ""),
                "cover": ep_data.get("cover", ""),
                "video_url": stream_url,
                "m3u8_url": stream_url,
                "h264_m3u8": ep_data.get("external_audio_h264_m3u8", ""),
                "h265_m3u8": ep_data.get("external_audio_h265_m3u8", ""),
                "subtitles": subtitles
            }
        })
    except Exception as e:
        return error_response(500, str(e))

@freereels_bp.route('/proxy', methods=['GET'])
def proxy():
    target_url = request.args.get('url')
    if not target_url:
        return error_response(400, "url parameter missing")
        
    try:
        url_obj = urlparse(target_url)
        referer = f"{url_obj.scheme}://{url_obj.netloc}"
        
        headers = {
            "Accept": "*/*",
            "Referer": referer,
            "Origin": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0"
        }
        
        r = requests.get(target_url, headers=headers, stream=True, timeout=15)
        if r.status_code != 200:
            return error_response(r.status_code, "Failed to fetch stream")
            
        content_type = r.headers.get("content-type", "application/octet-stream")
        if target_url.endswith(".m3u8"):
            content_type = "application/vnd.apple.mpegurl"
        elif target_url.endswith(".ts"):
            content_type = "video/mp2t"
        elif ".mp4" in target_url or ".m4s" in target_url or ".fmp4" in target_url:
            content_type = "video/mp4"
        elif target_url.endswith(".srt") or target_url.endswith(".vtt"):
            content_type = "text/vtt; charset=utf-8"
            
        from flask import make_response
        
        if target_url.endswith(".m3u8"):
            text = r.text
            base = target_url[:target_url.rfind('/') + 1]
            proxy_base = f"{request.url_root.rstrip('/')}freereels/proxy?url="
            
            def wrap(u):
                if not u.startswith("http"):
                    u = base + u
                return f"{proxy_base}{requests.utils.quote(u)}"
                
            new_lines = []
            for line in text.split("\n"):
                t = line.strip()
                if not t:
                    new_lines.append(line)
                    continue
                if t.startswith("#") and 'URI="' in t:
                    # Replace URI="..."
                    new_line = re.sub(r'URI="([^"]+)"', lambda m: f'URI="{wrap(m.group(1))}"', t)
                    new_lines.append(new_line)
                elif t.startswith("#"):
                    new_lines.append(line)
                else:
                    new_lines.append(wrap(t))
                    
            resp = make_response("\n".join(new_lines))
            resp.headers["Content-Type"] = content_type
            resp.headers["Cache-Control"] = "no-cache"
            return resp
            
        elif target_url.endswith(".srt"):
            vtt = convert_srt_to_vtt(r.text)
            resp = make_response(vtt)
            resp.headers["Content-Type"] = "text/vtt; charset=utf-8"
            resp.headers["Cache-Control"] = "max-age=3600"
            return resp
            
        else:
            # For streaming bytes (.ts, .mp4, .m4s)
            def generate():
                for chunk in r.iter_content(chunk_size=8192):
                    yield chunk
            resp = Response(generate(), mimetype=content_type)
            resp.headers["Cache-Control"] = "max-age=3600"
            return resp

    except Exception as e:
        return error_response(500, str(e))
