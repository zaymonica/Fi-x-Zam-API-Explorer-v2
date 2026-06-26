"""
routes/sosmed.py — Social Media Downloader (migrated from backend/sosmed.js)
"""
import re
import json
import requests as http_requests
from flask import Blueprint, request

from config import IG_COOKIE, FB_COOKIE
from utils import json_response

sosmed_bp = Blueprint('sosmed', __name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def find_by_key(obj, key):
    """Recursively find a value by key in nested dicts/lists."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for k, v in obj.items():
            result = find_by_key(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_by_key(item, key)
            if result is not None:
                return result
    return None


def extract_instagram(html):
    """Extract Instagram media metadata from HTML."""
    scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
    if not scripts:
        return None

    for s in scripts:
        if 'video_versions' in s or 'xdt_api__v1__clips' in s:
            try:
                data = json.loads(s)
                clips = find_by_key(data, 'xdt_api__v1__clips__home__connection_v2')
                media = None
                if clips:
                    edges = clips.get('edges', [])
                    if edges:
                        media = edges[0].get('node', {}).get('media')
                if not media:
                    media = find_by_key(data, 'media')

                if media:
                    user = media.get('user', {}) or media.get('owner', {}) or {}
                    caption = media.get('caption', {}) or {}
                    edge_caption = media.get('edge_media_to_caption', {}) or {}
                    image_versions = media.get('image_versions2', {}) or {}
                    edge_like = media.get('edge_media_preview_like', {}) or {}
                    edge_comment = media.get('edge_media_to_parent_comment', {}) or {}

                    caption_text = caption.get('text', '')
                    if not caption_text:
                        edges_c = edge_caption.get('edges', [])
                        if edges_c:
                            caption_text = edges_c[0].get('node', {}).get('text', '')

                    video_url = ''
                    vv = media.get('video_versions', [])
                    if vv:
                        video_url = vv[0].get('url', '')
                    if not video_url:
                        video_url = media.get('video_url', '')

                    thumbnail = ''
                    candidates = image_versions.get('candidates', [])
                    if candidates:
                        thumbnail = candidates[0].get('url', '')
                    if not thumbnail:
                        thumbnail = media.get('display_url', '')

                    return {
                        'platform': 'Instagram',
                        'username': user.get('username', ''),
                        'nickname': user.get('full_name', ''),
                        'description': caption_text,
                        'video_url': video_url,
                        'thumbnail': thumbnail,
                        'stats': {
                            'likes': media.get('like_count') or edge_like.get('count'),
                            'comments': media.get('comment_count') or edge_comment.get('count'),
                            'plays': media.get('play_count') or media.get('video_view_count')
                        }
                    }
            except Exception:
                pass
    return None


def fetch_tiktok(target_url):
    """Fetch TikTok video via tikwm.com API directly."""
    try:
        import random
        random_ip = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}"
        api_res = http_requests.post('https://www.tikwm.com/api/', headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://www.tikwm.com', 'Referer': 'https://www.tikwm.com/',
            'X-Forwarded-For': random_ip, 'Client-IP': random_ip, 'X-Real-IP': random_ip,
        }, data={'url': target_url, 'count': '12', 'cursor': '0', 'web': '1', 'hd': '1'}, timeout=30)
        data = api_res.json()
        if data.get('code') != 0 or not data.get('data'):
            return json_response({'error': 'Gagal extract video dari tikwm', 'logs': data}, 404)
        info = data['data']
        to_abs = lambda p: f'https://www.tikwm.com{p}' if p and p.startswith('/') else p
        result = {
            'platform': 'TikTok', 'id': info.get('id'), 'region': info.get('region'),
            'title': info.get('title', ''), 'cover': to_abs(info.get('cover','')),
            'duration': info.get('duration', 0), 'play': to_abs(info.get('play','')),
            'wmplay': to_abs(info.get('wmplay','')), 'hdplay': to_abs(info.get('hdplay','')),
            'size': info.get('size', 0), 'wm_size': info.get('wm_size', 0), 'hd_size': info.get('hd_size', 0),
            'music': to_abs(info.get('music','')), 'music_info': info.get('music_info'),
            'play_count': info.get('play_count', 0), 'digg_count': info.get('digg_count', 0),
            'comment_count': info.get('comment_count', 0), 'share_count': info.get('share_count', 0),
            'download_count': info.get('download_count', 0), 'collect_count': info.get('collect_count', 0),
            'create_time': info.get('create_time', 0), 'author': info.get('author'),
        }
        return json_response({'status': 'success', 'data': result})
    except Exception as err:
        return json_response({'error': str(err)}, 500)



@sosmed_bp.route('/sosmed', defaults={'subpath': ''}, methods=['GET'])
@sosmed_bp.route('/sosmed/<path:subpath>', methods=['GET'])
def handle_sosmed(subpath):
    target_url = request.args.get('url')
    path = subpath

    if not target_url:
        return json_response({'error': 'Masukkan parameter ?url= dulu maseh!'}, 400)

    is_ig = 'instagram.com' in target_url
    is_tiktok = 'tiktok.com' in target_url or 'vt.tiktok' in target_url

    if path == 'tiktok' and not is_tiktok:
        return json_response({'error': 'URL tidak valid untuk TikTok'}, 400)
    if path == 'instagram' and not is_ig:
        return json_response({'error': 'URL tidak valid untuk Instagram'}, 400)
    if path == 'facebook':
        return json_response({
            'error': 'Endpoint Facebook dihentikan karena API upstream sudah tidak aktif.',
            'supported_platforms': ['TikTok', 'Instagram']
        }, 410)

    if not is_ig and not is_tiktok:
        return json_response({
            'error': 'URL tidak didukung',
            'supported_platforms': ['TikTok', 'Instagram']
        }, 400)

    if is_tiktok:
        return fetch_tiktok(target_url)

    # Instagram
    custom_headers = {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
        'Sec-Ch-Ua': '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    }

    if is_ig:
        custom_headers['Cookie'] = IG_COOKIE
        custom_headers['Referer'] = 'https://www.instagram.com/accounts/onetap/'
        custom_headers['X-IG-App-ID'] = '936619743392459'
        custom_headers['Sec-Fetch-Site'] = 'same-origin'

    try:
        response = http_requests.get(target_url, headers=custom_headers, timeout=30)
        if not response.ok:
            return json_response({
                'error': 'Upstream Error',
                'status': response.status_code,
                'statusText': response.reason
            }, response.status_code)

        html = response.text
        if not html or len(html) < 100:
            return json_response({
                'error': 'Empty Response Body',
                'platform': 'Instagram',
                'status': response.status_code
            }, 429)

        result = extract_instagram(html) if is_ig else None

        if result:
            return json_response({'status': 'success', **result})

        title_match = re.search(r'<title>(.*?)</title>', html)
        return json_response({
            'error': 'Gagal mengambil metadata maseh!',
            'platform': 'Instagram',
            'html_title': title_match.group(1) if title_match else 'No Title',
            'html_sample': html[:600]
        }, 404)

    except Exception as err:
        return json_response({'error': str(err)}, 500)
