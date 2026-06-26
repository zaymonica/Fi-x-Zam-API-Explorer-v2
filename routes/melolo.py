import urllib.parse
import base64
import hashlib
import json as _json
import requests
from Crypto.Cipher import AES
from flask import Blueprint, request, Response
from utils import error_response, json_response, normalize_melolo_tags

melolo_bp = Blueprint('melolo', __name__, url_prefix='/melolo')

MELOLO_HEADERS = {
    "User-Agent": "com.worldance.drama/51717 (Linux; U; Android 14; in; sdk_gphone64_x86_64; Build/UE1A.230829.036.A4;tt-ok/4.12.0.2)",
    "Connection": "keep-alive",
    "Accept": "application/json; charset=utf-8,application/x-protobuf",
    "Accept-Encoding": "gzip",
    "x-xs-from-web": "false",
    "age-range": "2",
    "sdk-version": "2",
    "x-tt-token": "03bab594eaf64e48dfcad0be6522172a66029b0cea7523982cdd3ac42d80b1710561022557f81acd7eeb69271859bfa1f2785b0db96ac8cd2dc4b77a433f3c9482fa3e0fd31e625e23a6e77f6c3b53fcdce7d-1.0.0",
    "passport-sdk-version": "50357",
    "x-vc-bdturing-sdk-version": "2.2.1.i18n",
    "x-tt-store-region": "id",
    "x-tt-store-region-src": "uid",
    "x-ladon": "FiQIdkYHqY/8WOn0bRJ8YnE8SGA7ciHrceNGABdw69jwinFg",
    "x-khronos": "1771059733",
    "x-argus": "aKkZmftg4iewBS8/c4mp8FeNyZxFoUzz7LKPUe+r3INtxNon9oX6+IrMuZKBkIegT8dsOqSr32tbOMr4hD0i4Ey36DCf0kyEwYg0nCD9iyShLl9c6deJgNdcnKMq0K6i6oVNiuEau2ZUm0PYDJdRVo1OcBnoROSxTmbW+OXm9cRDE+19bJH4IA+dqjgHKLMYlVdHHZEXKBeK8XKKGkfdLdD82xBJ8SzYF0cPc5mTJgJQ8egnSlv91Z7MoiLoPwSObAQYoFzEfRjw7k8J4088Pog0hraOK4rGjEO4q28tnNPv6RjHX/qUlqRnJ2r1SSMqFMMLgkchfffayhwTMJJYA+3WFVdQvkmNpXCnHJ7ffdJSFxRWl2wO8N8Hp9kaiwnjXN7S8s7OWLRrd89bKbK9tOULb8BGHm3nnwarPXZ+R0cd2qTJ6aZVWC6UWM4KK8aN+rjmjChw+/lIUivOVYbCsLoz4cnccbCYuI9r9u878OQDiESPNhCLtIoTIw27phwr/+/cMYaJGbu4f2ZSc/6IYNepAtkWoGDqgcKxxlY5egjs5g==",
    "x-gorgon": "8404303f400023196736f6278d68040fa57cbbcc6b75a9a30e5e",
    "Cookie": "passport_csrf_token=be53aa2055109ce1157d666532faa783; passport_csrf_token_default=be53aa2055109ce1157d666532faa783; odin_tt=207596ee884100e9cab888247ed94ef232234d7389d1925907509fd6e76886e10800db33d362e7271795024cc59a3de13f136aa1988ac48120fce80c7b20363e5a320ce2c912d43a79ca0cd68483842a; passport_mfa_token=Cjln%2BcejuuhGkrHJ45k%2BUNRd2LSi2yuAtcBp9lgXT3DGlbWKEDAqV0sn6cAPkKHJ2IzMuxZjhpk4PnAaSQo8AAAAAAAAAAAAAFASiPAZZtbmBb68vCHAFUiHtwJng%2BjgjjvIB3RTOGnWrqwUeO3B%2F8z0BYHbI2W2FIapEPXLiQ4Y16mI7w4iAQQXIKZu; d_ticket=ca063796bfe7760c08402e3c24220f442aa03; store-idc=mya; store-country-code=id; sid_guard=bab594eaf64e48dfcad0be6522172a66%7C1771057595%7C5184000%7CWed%2C+15-Apr-2026+08%3A26%3A35+GMT; store-country-code-src=uid; uid_tt=9d234bdc2ef267fccfbffb3396d52d5ab9842c11fb34b496eeb0b9c8158b22e6; uid_tt_ss=9d234bdc2ef267fccfbffb3396d52d5ab9842c11fb34b496eeb0b9c8158b22e6; sid_tt=bab594eaf64e48dfcad0be6522172a66; sessionid=bab594eaf64e48dfcad0be6522172a66; sessionid_ss=bab594eaf64e48dfcad0be6522172a66; install_id=7606637015534520081; ttreq=1$18eaec2961146e9d7cfcae3d7674b4978fa09073; msToken=a-mDiK1vxEACcYPjEvtifTEJyvNHmz7tL7fuJ7oW82DYqVKl12Z0yYi1XnVlB328MYQ0kS0iqYfNeTu09ZssypZ6GuW5065dDiWRZkJ-d40="
}

MELOLO_LANGS = {
    "id": "Bahasa Indonesia",
    "en": "English",
    "es": "Español",
    "th": "ภาษาไทย",
    "pt": "Português",
    "vi": "Tiếng Việt",
    "ja": "日本語",
    "ko": "한국어",
}

def get_melolo_lang():
    lang = request.args.get("lang", "id").lower()
    return lang if lang in MELOLO_LANGS else "id"

def inject_lang(url_str, lang):
    import re
    url_str = re.sub(r'user_language=[^&]*', f'user_language={lang}', url_str)
    url_str = re.sub(r'language=[^&]*', f'language={lang}', url_str)
    return url_str

def fetch_melolo_tags_by_search(series_id, series_title, lang="id"):
    if not series_title and not series_id:
        return []
        
    query = series_title if series_title else "a"
    target_url = f"https://api.tmtreader.com/i18n_novel/search/page/v1/?query={urllib.parse.quote(query)}&limit=10&aid=645713&user_language={lang}&offset=0"
    
    try:
        r = requests.get(target_url, headers=MELOLO_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
            
        data = r.json()
        search_data = data.get("data", {}).get("search_data", [])
        
        books = []
        for item in search_data:
            books.extend(item.get("books", []))
            
        match = None
        for book in books:
            if series_id and str(book.get("book_id")) == str(series_id):
                match = book
                break
            elif series_title and book.get("book_name") == series_title:
                match = book
                break
                
        if match:
            return normalize_melolo_tags(match.get("stat_infos", []))
        return []
    except:
        return []

@melolo_bp.route('/languages', methods=['GET'])
def languages():
    data = [{"code": k, "name": v} for k, v in MELOLO_LANGS.items()]
    return json_response({
        "type": "languages",
        "total": len(data),
        "data": data
    })

@melolo_bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q')
    limit = int(request.args.get('result', request.args.get('limit', '10')))
    page = int(request.args.get('page', '1'))
    offset = (max(1, page) - 1) * limit
    lang = get_melolo_lang()
    
    if not query:
        return error_response(400, "Query Missing")
        
    target_url = f"https://api.tmtreader.com/i18n_novel/search/page/v1/?query={urllib.parse.quote(query)}&limit={limit}&aid=645713&user_language=id&offset={offset}"
    target_url = inject_lang(target_url, lang)
    
    try:
        r = requests.get(target_url, headers=MELOLO_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            search_data = data.get("data", {}).get("search_data", [])
            
            clean_data = []
            for item in search_data:
                books = []
                for book in item.get("books", []):
                    cover_stats = book.get("cover_stat_infos", [])
                    watch_val = ""
                    if isinstance(cover_stats, list) and len(cover_stats) > 0:
                        watch_val = cover_stats[0].get("stat_value", "")
                        
                    books.append({
                        "drama_name": book.get("book_name", ""),
                        "drama_id": book.get("book_id", ""),
                        "description": book.get("abstract", ""),
                        "create_time": book.get("create_time", 0),
                        "episode_count": book.get("serial_count", 0),
                        "watch_value": watch_val,
                        "is_new_book": book.get("is_new_book", 0),
                        "language": lang,
                        "thumb_url": book.get("thumb_url", ""),
                        "tags": normalize_melolo_tags(book.get("stat_infos", []))
                    })
                clean_data.append({"books": books})
                
            return json_response({
                "type": "search",
                "data": clean_data
            })
        return error_response(r.status_code, "Upstream Error")
    except Exception as e:
        return error_response(500, str(e))

@melolo_bp.route('/new', methods=['GET'])
def new_series():
    limit = 50
    page = int(request.args.get('page', '1'))
    offset = (max(1, page) - 1) * limit
    lang = get_melolo_lang()

    target_url = f"https://api.tmtreader.com/i18n_novel/search/page/v1/?query=a&limit={limit}&aid=645713&user_language=id&offset={offset}"
    target_url = inject_lang(target_url, lang)

    try:
        r = requests.get(target_url, headers=MELOLO_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            search_data = data.get("data", {}).get("search_data", [])

            # is_new_book is no longer set by the API (always 0), so the old filter
            # produced empty results. Instead, collect all books and sort by
            # create_time (ISO8601 string) descending to surface the newest titles.
            all_books = []
            for item in search_data:
                for book in item.get("books", []):
                    cover_stats = book.get("cover_stat_infos", [])
                    watch_val = ""
                    if isinstance(cover_stats, list):
                        for cs in cover_stats:
                            if cs.get("stat_value"):
                                watch_val = cs.get("stat_value")
                                break

                    all_books.append({
                        "drama_name": book.get("book_name", ""),
                        "drama_id": book.get("book_id", ""),
                        "description": book.get("abstract", ""),
                        "create_time": book.get("create_time", ""),
                        "episode_count": book.get("serial_count", 0),
                        "watch_value": watch_val,
                        "is_new_book": book.get("is_new_book", 0),
                        "language": lang,
                        "thumb_url": book.get("thumb_url", ""),
                        "tags": normalize_melolo_tags(book.get("stat_infos", []))
                    })

            all_books.sort(key=lambda b: str(b.get("create_time") or ""), reverse=True)

            return json_response({
                "type": "new",
                "data": [{"books": all_books}] if all_books else []
            })
        return error_response(r.status_code, "Upstream Error")
    except Exception as e:
        return error_response(500, str(e))

@melolo_bp.route('/populer', methods=['GET'])
def populer():
    page = int(request.args.get('page', '1'))
    offset = (max(1, page) - 1) * 18
    lang = get_melolo_lang()
    
    target_url = f"https://api.tmtreader.com/i18n_novel/bookmall/cell/change/v1/?tab_scene=3&limit=10&start_offset=0&cell_id=7450059162446200848&iid=7598566572336629512&aid=645713&app_name=Melolo&version_name=5.1.4&device_platform=android&device_type=sdk_gphone64_x86_64&language=id&update_version_code=51419&_rticket=1769253358407&current_region=US&sys_language=id&app_region=US&user_language=id&offset={offset}&session_id=2026012920165661C44D70E5B601D5C6EE"
    target_url = inject_lang(target_url, lang)
    
    try:
        r = requests.get(target_url, headers=MELOLO_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            cell_data = data.get("data", {}).get("cell", {}).get("cell_data", [])
            
            populer_data = []
            for item in cell_data:
                new_books = []
                for book in item.get("books", []):
                    cover_stats = book.get("cover_stat_infos", [])
                    watch_val = ""
                    if isinstance(cover_stats, list):
                        for cs in cover_stats:
                            if cs.get("stat_value"):
                                watch_val = cs.get("stat_value")
                                break
                                
                    new_books.append({
                        "drama_name": book.get("book_name", ""),
                        "drama_id": book.get("book_id", ""),
                        "description": book.get("abstract", ""),
                        "create_time": book.get("create_time", 0),
                        "episode_count": book.get("serial_count", 0),
                        "watch_value": watch_val,
                        "is_new_book": book.get("is_new_book", 0),
                        "language": lang,
                        "thumb_url": book.get("thumb_url", ""),
                        "tags": normalize_melolo_tags(book.get("stat_infos", []))
                    })
                if new_books:
                    populer_data.append({"books": new_books})
            return json_response({
                "type": "populer",
                "data": populer_data
            })
        return error_response(r.status_code, "Upstream Error")
    except Exception as e:
        return error_response(500, str(e))

@melolo_bp.route('/home', methods=['GET'])
def home():
    page = int(request.args.get('page', '1'))
    limit = 10
    offset = (max(1, page) - 1) * limit
    lang = get_melolo_lang()
    
    target_url = f"https://api.tmtreader.com/i18n_novel/search/page/v1/?query=a&limit={limit}&aid=645713&user_language=id&offset={offset}"
    target_url = inject_lang(target_url, lang)
    
    try:
        r = requests.get(target_url, headers=MELOLO_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            search_data = data.get("data", {}).get("search_data", [])
            
            books = []
            for item in search_data:
                for book in item.get("books", []):
                    cover_stats = book.get("cover_stat_infos", [])
                    watch_val = ""
                    if isinstance(cover_stats, list):
                        for cs in cover_stats:
                            if cs.get("stat_value"):
                                watch_val = cs.get("stat_value")
                                break
                    books.append({
                        "drama_name": book.get("book_name", ""),
                        "drama_id": book.get("book_id", ""),
                        "description": book.get("abstract", ""),
                        "create_time": book.get("create_time", 0),
                        "episode_count": book.get("serial_count", 0),
                        "watch_value": watch_val,
                        "is_new_book": book.get("is_new_book", 0),
                        "language": lang,
                        "thumb_url": book.get("thumb_url", ""),
                        "tags": normalize_melolo_tags(book.get("stat_infos", []))
                    })
            return json_response({
                "type": "home",
                "data": [{"books": books}] if books else []
            })
        return error_response(r.status_code, "Upstream Error")
    except Exception as e:
        return error_response(500, str(e))

@melolo_bp.route('/detail', methods=['GET'])
@melolo_bp.route('/detail/<path:id>', methods=['GET'])
def detail(id=None):
    series_id = id or request.args.get('id', '')
    if not series_id:
        return error_response(400, "Series ID Missing")
        
    lang = get_melolo_lang()
    target_url = "https://api.tmtreader.com/novel/player/video_detail/v1/?aid=645713"
    
    payload = {
        "biz_param": {
            "detail_page_version": 0,
            "from_video_id": "",
            "need_all_video_definition": False,
            "need_mp4_align": False,
            "source": 0,
            "use_os_player": False,
            "use_server_dns": False,
            "video_id_type": 0
        },
        "series_id": str(series_id)
    }
    
    try:
        r = requests.post(target_url, headers={**MELOLO_HEADERS, 'Content-Type': 'application/json'}, json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            video_data = data.get("data", {}).get("video_data", {})
            
            detail_tags = normalize_melolo_tags(video_data.get("stat_infos", []))
            tags = detail_tags if len(detail_tags) > 0 else fetch_melolo_tags_by_search(video_data.get("series_id_str"), video_data.get("series_title"), lang)
            
            video_list = []
            for item in video_data.get("video_list", []):
                video_list.append({
                    "episode": item.get("vid_index"),
                    "video_id": item.get("vid"),
                    "duration": item.get("duration"),
                    "cover": item.get("cover")
                })
                
            return json_response({
                "type": "detail",
                "data": {
                    "drama_id": video_data.get("series_id_str"),
                    "drama_name": video_data.get("series_title"),
                    "description": video_data.get("series_intro"),
                    "episode_count": video_data.get("episode_cnt"),
                    "video_list": video_list,
                    "tags": tags
                }
            })
        return error_response(r.status_code, "Upstream Error")
    except Exception as e:
        return error_response(500, str(e))

MELOLO_NATIVE_API = "https://v-api.crazymaplestudios.com"

# Signing headers captured from Melolo 5.3.2 (53218) live traffic (2026-06-10).
# These x-gorgon/x-argus/x-ladon/x-khronos are device-signed and NOT bound to a
# specific request body — verified working cross-video. They DO expire over time;
# refresh by re-capturing a multi_video_model request from the app.
MELOLO_V2_HEADERS = {
    "User-Agent": "com.worldance.drama/53218 (Linux; U; Android 12; en; SM-A528B; Build/V417IR;tt-ok/4.12.0.2)",
    "Accept": "application/json; charset=utf-8,application/x-protobuf",
    "Accept-Encoding": "gzip",
    "x-ss-stub": "C9B41288B301DD5DF11DA74CBADC1EF9",
    "x-xs-from-web": "false",
    "age-range": "3",
    "client-install-id": "33e8642b-8e4b-4e61-bb45-28f45c7aec3d",
    "sdk-version": "2",
    "passport-sdk-version": "50357",
    "x-vc-bdturing-sdk-version": "2.2.1.i18n",
    "x-ladon": "7vZcUXWLsQrjl9duMm7Da8qWJX1zvoIkNtlM2D0EnWLNMaxL",
    "x-khronos": "1781103890",
    "x-argus": "WOBXxIQ197ao6CCl9TrfAZNWuDjNaZCRsh8ZB2JjzM9akNdaWi89LcUVSPI6Dk88GNcN3HAaB4r/bMBBMrRt4aBgErqUKnqVAw3f0/61RJ5MWKVpHW+hMtkRC2dSwlGwaHEr1aV5JM+Xez+e2pXOaEzKhRidxrrOuYgssNG1ZgjpDkwppnmWTlX5RRUYLksscbWiogHyAt59Yr93deSlj6QWd/+KGHbcfKyNDUbJeyL49twDJ8toqZdV8cy5r5BUqq/9hKg+3yIKuE6ARMR7pzpB8yFuPikFNUhYmwLlDURIlA==",
    "x-gorgon": "8404905d4401bcd24dffc97f95fdaea7e3ea3a2b88b49e6051ae",
    "x-bdms": "1",
    "Cookie": "install_id=7649781244226537269; ttreq=1$2bebd990a8693ab5541b3b6d0c9f424f4d8f9b14; odin_tt=02df51b94a0ed87c71626ae712357df719278ecbdf805ee4193c93e6fde020e003cec1dab4147ef2b23fcccfa70ecf486185f1a6da4aa4e9c97e9f7d24ac58d0657b10e3994799e3f1e883240416406b",
}

MELOLO_V2_PARAMS = "iid=7649781244226537269&device_id=7649780290684864005&ac=wifi&channel=gp&aid=645713&app_name=Melolo&version_code=53218&version_name=5.3.2&device_platform=android&os=android&ssmix=a&device_type=SM-A528B&device_brand=Samsung&language=en&os_api=32&os_version=12&openudid=b89e609511df2045&manifest_version_code=53218&resolution=960*540&dpi=186&update_version_code=53218&_rticket=1781103890622&current_region=CA&carrier_region=ca&app_language=en&sys_language=en&app_region=CA&sys_region=US&mcc_mnc=302780&carrier_region_v2=302&user_language=en&time_zone=Asia%2FJakarta&ui_language=en&cdid=cb32a6c0-661b-4491-8ecb-949c558c1180"


def _get_melolo_auth_headers():
    """Build auth headers for v-api requests."""
    return {
        "User-Agent": MELOLO_V2_HEADERS["User-Agent"],
        "Accept": MELOLO_V2_HEADERS["Accept"],
        "Content-Type": "application/x-www-form-urlencoded",
        "x-xs-from-web": "false",
        "age-range": "2",
        "sdk-version": "2",
        "x-ladon": MELOLO_V2_HEADERS["x-ladon"],
        "x-khronos": MELOLO_V2_HEADERS["x-khronos"],
        "x-argus": MELOLO_V2_HEADERS["x-argus"],
        "x-gorgon": MELOLO_V2_HEADERS["x-gorgon"],
        "Cookie": MELOLO_V2_HEADERS["Cookie"],
    }

def _get_chapter_id_for_episode(drama_id, ep_num):
    """Get chapter_id for a specific episode number using multi_video_detail API."""
    target_url = f"https://api.tmtreader.com/novel/player/multi_video_detail/v1/?{MELOLO_V2_PARAMS}"
    payload = {
        "biz_param": {
            "detail_page_version": 0,
            "disable_digg_stat": False,
            "need_all_video_definition": False,
            "need_mp4_align": False,
            "source": 7,
            "use_os_player": False,
            "use_server_dns": False
        },
        "series_id": str(drama_id)
    }
    
    r = requests.post(
        target_url,
        headers={**MELOLO_V2_HEADERS, 'Content-Type': 'application/json; charset=utf-8'},
        json=payload,
        timeout=15
    )
    
    if r.status_code != 200:
        return None, None
    
    data = r.json()
    if data.get("code") != 0:
        return None, None
    
    # multi_video_detail returns data keyed by series_id
    series_data = data.get("data", {}).get(str(drama_id), {})
    video_data = series_data.get("video_data", {})
    video_list = video_data.get("video_list", [])
    
    # Find the episode by vid_index (1-based)
    for item in video_list:
        if item.get("vid_index") == ep_num:
            return item.get("vid"), video_data
    
    return None, video_data

def _get_video_model(video_id):
    """Call multi_video_model API to get video URLs for a given video_id (vid)."""
    import base64
    import json as json_mod
    
    target_url = f"https://api.tmtreader.com/novel/player/multi_video_model/v1/?{MELOLO_V2_PARAMS}"
    payload = {
        "biz_param": {
            "detail_page_version": 0,
            "device_level": 3,
            "disable_digg_stat": False,
            "need_all_video_definition": True,
            "need_mp4_align": False,
            "use_os_player": False,
            "use_server_dns": False,
            "video_platform": 1024
        },
        "mixed_video_id_map": {"1": [str(video_id)]},
        "video_id": str(video_id)
    }

    r = requests.post(
        target_url,
        headers={**MELOLO_V2_HEADERS, 'Content-Type': 'application/json; charset=utf-8'},
        json=payload,
        timeout=15
    )

    if r.status_code != 200:
        return None

    data = r.json()
    if data.get("code") != 0:
        return None

    # Response keyed by video_id
    video_info = data.get("data", {}).get(str(video_id), {})
    video_model_str = video_info.get("video_model", "")
    
    if not video_model_str:
        return None
    
    try:
        video_model = json_mod.loads(video_model_str) if isinstance(video_model_str, str) else video_model_str
    except (json_mod.JSONDecodeError, TypeError):
        return None
    
    # Parse video_list from video_model
    video_list = video_model.get("video_list", {})
    qualities = []
    
    # Quality order preference: 720p > 540p > 480p > 360p > 240p
    quality_order = ["video_5", "video_4", "video_3", "video_2", "video_1"]
    
    for q_key in quality_order:
        q_data = video_list.get(q_key)
        if not q_data:
            continue
        
        main_url_b64 = q_data.get("main_url", "")
        backup_url_b64 = q_data.get("backup_url_1", "")
        
        # Decode base64 URLs
        main_url = ""
        backup_url = ""
        try:
            if main_url_b64:
                main_url = base64.b64decode(main_url_b64).decode('utf-8')
            if backup_url_b64:
                backup_url = base64.b64decode(backup_url_b64).decode('utf-8')
        except Exception:
            continue
        
        if main_url:
            qualities.append({
                "label": q_data.get("definition", "unknown"),
                "url": main_url,
                "backup_url": backup_url,
                "width": q_data.get("vwidth", 0),
                "height": q_data.get("vheight", 0),
                "bitrate": q_data.get("bitrate", 0),
                "codec": q_data.get("codec_type", ""),
                "size": q_data.get("size", 0),
                # DRM info — these streams are CENC AES-CTR encrypted; the bytes
                # at `url` cannot be played directly without decryption.
                "encrypted": bool(q_data.get("encrypt", False)),
                "encryption_method": q_data.get("encryption_method", ""),
                "kid": q_data.get("kid", ""),
                "file_id": q_data.get("file_id", ""),
                "file_hash": q_data.get("file_hash", ""),
            })

    any_encrypted = any(q.get("encrypted") for q in qualities)
    return {
        "qualities": qualities,
        "video_id": video_model.get("video_id", ""),
        "duration": video_model.get("video_duration", 0),
        "video_height": video_info.get("video_height", 0),
        "video_width": video_info.get("video_width", 0),
        "expire_time": video_info.get("expire_time", 0),
        # DRM: key_seed is top-level; needed (with per-quality kid) to derive the
        # CENC content key. Decryption itself is done by ByteDance's native player.
        "encrypted": any_encrypted,
        "key_seed": video_model.get("key_seed", ""),
        "fallback_api": video_model.get("fallback_api", ""),
    }

@melolo_bp.route('/stream', methods=['GET'])
def stream():
    drama_id = request.args.get('id', '')
    episode = request.args.get('ep', '1')

    if not drama_id:
        return error_response(400, "Drama ID Missing (id)")

    try:
        ep_num = int(episode)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    try:
        # Step 1: Get vid for the requested episode from multi_video_detail
        vid, video_data = _get_chapter_id_for_episode(drama_id, ep_num)

        if not vid:
            return error_response(404, f"Episode {ep_num} not found for drama {drama_id}")

        # Step 2: Resolve playable video URLs via multi_video_model
        model = _get_video_model(vid)
        if not model or not model.get("qualities"):
            return error_response(502, "Failed to resolve video model (signing headers may be stale)")

        return json_response({
            "type": "stream",
            "drama_id": drama_id,
            "episode": ep_num,
            "vid": vid,
            "duration": model.get("duration"),
            "expire_time": model.get("expire_time"),
            "encrypted": model.get("encrypted", False),
            "drm": {
                "scheme": "cenc-aes-ctr",
                "key_seed": model.get("key_seed", ""),
                "note": "Video tracks are CENC AES-CTR encrypted. The URLs return ciphertext that ByteDance's native player decrypts on-device using key_seed + per-quality kid. Standard players will show a black screen without the derived content key.",
            } if model.get("encrypted") else None,
            "fallback_api": model.get("fallback_api", ""),
            "qualities": model.get("qualities"),
        })
    except Exception as e:
        return error_response(500, str(e))

@melolo_bp.route('/cdn/<path:video_path>', methods=['GET'])
def cdn_proxy(video_path):
    """Proxy video content through our server for CORS/access."""
    # Support TikTok CDN patterns
    upstream_url = f"https://{video_path}" if "tiktokcdn.com" in video_path or "byteicdn.com" in video_path else f"https://v16m-default.tiktokcdn.com/{video_path}"

    # Forward Range header for video seeking
    headers = {"User-Agent": MELOLO_V2_HEADERS["User-Agent"]}
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        r = requests.get(upstream_url, headers=headers, stream=True, timeout=(5, 60))

        # Build response headers
        resp_headers = {}
        for h in ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]:
            if r.headers.get(h):
                resp_headers[h] = r.headers[h]
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "video/mp4"
        resp_headers["Accept-Ranges"] = "bytes"

        return Response(
            r.iter_content(chunk_size=1024 * 64),
            status=r.status_code,
            headers=resp_headers,
        )
    except Exception as e:
        return error_response(502, str(e))


# ─── streamv2: decrypted playback via dramakuy resolver ────────────────────
# dramakuy.com hosts a Melolo resolver that returns the already-DECRYPTED MP4
# (CENC removed) behind a tobrutmelolo CDN URL signed with a daily auth_key.
# The /api/melolo/stream response body is a CryptoJS AES blob; the passphrase
# was recovered from dramakuy's frontend bundle.
DRAMAKUY_BASE = "https://dramakuy.com"
DRAMAKUY_PASSPHRASE = "DracinBox-SecureKey2026"
MELOLO_WORKER_PROXY = "https://proxy.sonzaixlab.workers.dev/stream"


def _cryptojs_decrypt(b64_blob, passphrase):
    """Decrypt a CryptoJS AES 'Salted__' blob (OpenSSL EVP_BytesToKey/MD5)."""
    raw = base64.b64decode(b64_blob)
    if raw[:8] != b"Salted__":
        raise ValueError("not a CryptoJS salted blob")
    salt = raw[8:16]
    ct = raw[16:]
    # derive 32-byte key + 16-byte IV via repeated MD5
    d = b""
    prev = b""
    pw = passphrase.encode()
    while len(d) < 48:
        prev = hashlib.md5(prev + pw + salt).digest()
        d += prev
    key, iv = d[:32], d[32:48]
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    return pt[:-pt[-1]]  # strip PKCS7 padding


def _dramakuy_resolve(video_id, book_id):
    """Call dramakuy resolver and return the decrypted JSON (playable URL)."""
    url = f"{DRAMAKUY_BASE}/api/melolo/stream?videoId={video_id}&bookId={book_id}"
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "referer": f"{DRAMAKUY_BASE}/watch/melolo/{book_id}/{video_id}",
    }, timeout=20)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    body = r.json()
    blob = body.get("data")
    if not isinstance(blob, str):
        return None, "unexpected response"
    try:
        decrypted = _cryptojs_decrypt(blob, DRAMAKUY_PASSPHRASE)
        return _json.loads(decrypted), None
    except Exception as e:
        return None, f"decrypt failed: {e}"


@melolo_bp.route('/streamv2', methods=['GET'])
def streamv2():
    """Resolve a PLAYABLE (decrypted) Melolo video URL via the dramakuy resolver.

    Params: id (drama/book id, required), ep (episode, default 1).
    Returns a tobrutmelolo CDN URL serving a fully decrypted MP4 (no CENC),
    plus a /melolo/watch proxy URL for CORS-free playback.
    """
    drama_id = request.args.get('id', '')
    episode = request.args.get('ep', '1')
    if not drama_id:
        return error_response(400, "Drama ID Missing (id)")
    try:
        ep_num = int(episode)
    except ValueError:
        return error_response(400, "Invalid episode number (ep)")

    try:
        # 1. drama_id + episode -> video_id (vid) via Melolo's own API
        vid, _ = _get_chapter_id_for_episode(drama_id, ep_num)
        if not vid:
            return error_response(404, f"Episode {ep_num} not found for drama {drama_id}")

        # 2. dramakuy resolver -> decrypted playable URL
        data, err = _dramakuy_resolve(vid, drama_id)
        if err:
            return error_response(502, f"Resolver error: {err}")

        inner = data.get("data", data) if isinstance(data, dict) else {}
        play_url = inner.get("url") or inner.get("main_url")
        if not play_url:
            return error_response(502, "No playable URL in resolver response")

        # Rebuild as a clean worker URL: /stream?id=..&auth_key=..
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(play_url).query)
        vid_q = qs.get("id", [""])[0]
        auth_key = qs.get("auth_key", [""])[0]
        proxied = f"{MELOLO_WORKER_PROXY}?id={vid_q}&auth_key={auth_key}"

        return json_response({
            "type": "streamv2",
            "drama_id": drama_id,
            "episode": ep_num,
            "vid": vid,
            "playable": True,
            "encrypted": False,
            "url": proxied,
        })
    except Exception as e:
        return error_response(500, str(e))


@melolo_bp.route('/watch', methods=['GET'])
def watch():
    """Range-aware proxy for a resolved (decrypted) Melolo video URL.

    Serves the MP4 through our origin so browsers can play it without CORS
    issues. Only proxies the known decrypted-video hosts.
    """
    url = request.args.get('url', '')
    if not url:
        return error_response(400, "URL Missing (url)")
    host = urllib.parse.urlparse(url).netloc
    if not (host.endswith("inicdn.net") or host.endswith("melolostatic.com")):
        return error_response(400, "Host not allowed")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Origin": DRAMAKUY_BASE,
        "Referer": DRAMAKUY_BASE + "/",
    }
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        r = requests.get(url, headers=headers, stream=True, timeout=(5, 60))
        resp_headers = {}
        for h in ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]:
            if r.headers.get(h):
                resp_headers[h] = r.headers[h]
        resp_headers.setdefault("Content-Type", "video/mp4")
        resp_headers["Accept-Ranges"] = "bytes"
        resp_headers["Access-Control-Allow-Origin"] = "*"
        return Response(
            r.iter_content(chunk_size=1024 * 64),
            status=r.status_code,
            headers=resp_headers,
        )
    except Exception as e:
        return error_response(502, str(e))
