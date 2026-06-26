"""
routes/youtube.py — YouTube Downloader
Flow: oembed (metadata) -> cnv.cx sanity key -> cnv.cx converter (tunnel link).
"""
import re
import urllib.parse
import requests
from flask import Blueprint, request
from utils import json_response, error_response

youtube_bp = Blueprint('youtube', __name__, url_prefix='/youtube')

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'

OEMBED_URL = 'https://www.youtube.com/oembed'
CNV_KEY_URL = 'https://cnv.cx/v2/sanity/key'
CNV_CONVERTER_URL = 'https://cnv.cx/v2/converter'

CNV_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept-Encoding': 'gzip, deflate, br',
    'sec-ch-ua-platform': '"Windows"',
    'sec-ch-ua': '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'Sec-GPC': '1',
    'Accept-Language': 'en-US,en;q=0.6',
    'origin': 'https://iframe.y2meta-uk.com',
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
    'referer': 'https://iframe.y2meta-uk.com/',
}

VALID_FORMATS = {'mp4', 'mp3'}


def _extract_video_id(url):
    """Pull the 11-char video id out of any common YouTube URL form."""
    if not url:
        return None
    # Bare id passed directly
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', url):
        return url
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None
    host = (parsed.netloc or '').lower()
    if 'youtube.com' in host:
        if parsed.path == '/watch':
            vid = urllib.parse.parse_qs(parsed.query).get('v', [None])[0]
            if vid:
                return vid
        m = re.search(r'/(?:embed|shorts|v|live)/([A-Za-z0-9_-]{11})', parsed.path)
        if m:
            return m.group(1)
    if 'youtu.be' in host:
        m = re.match(r'/([A-Za-z0-9_-]{11})', parsed.path)
        if m:
            return m.group(1)
    # Last resort: first 11-char token anywhere
    m = re.search(r'[A-Za-z0-9_-]{11}', url)
    return m.group(0) if m else None


def _fetch_metadata(video_id):
    watch_url = f'https://www.youtube.com/watch?v={video_id}'
    params = {'url': watch_url, 'format': 'json'}
    r = requests.get(OEMBED_URL, params=params, headers={'User-Agent': USER_AGENT}, timeout=15)
    if r.status_code != 200:
        return None
    return r.json()


def _fetch_key():
    headers = dict(CNV_HEADERS)
    headers['content-type'] = 'application/json'
    r = requests.get(CNV_KEY_URL, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json().get('key')


def _convert(video_id, fmt, video_quality, audio_bitrate, vcodec):
    headers = dict(CNV_HEADERS)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    headers['key'] = _fetch_key()

    data = {
        'link': f'https://youtu.be/{video_id}',
        'format': fmt,
        'audioBitrate': audio_bitrate,
        'filenameStyle': 'pretty',
    }
    if fmt == 'mp4':
        data['videoQuality'] = video_quality
        data['vCodec'] = vcodec

    r = requests.post(CNV_CONVERTER_URL, headers=headers, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


# ─── Flask Routes ────────────────────────────────────────────────────────

@youtube_bp.route('', methods=['GET'])
@youtube_bp.route('/', methods=['GET'])
def youtube_index():
    return json_response({
        "status": "online",
        "service": "YouTube Downloader",
        "endpoints": {
            "info": "/youtube/info?url=YOUTUBE_URL",
            "download": "/youtube/download?url=YOUTUBE_URL&format=mp4&quality=720",
            "download_mp3": "/youtube/download?url=YOUTUBE_URL&format=mp3&audioBitrate=128",
        },
        "params": {
            "format": "mp4 (default) | mp3",
            "quality": "video resolution for mp4, e.g. 360/480/720/1080 (default 720)",
            "audioBitrate": "audio bitrate, e.g. 128/192/320 (default 128)",
            "vCodec": "h264 (default) | av1 | vp9",
        },
    })


@youtube_bp.route('/info', methods=['GET'])
def youtube_info():
    url = request.args.get('url')
    if not url:
        return error_response(400, "Masukkan parameter ?url= dulu maseh!")

    video_id = _extract_video_id(url)
    if not video_id:
        return error_response(400, "URL YouTube tidak valid")

    try:
        meta = _fetch_metadata(video_id)
    except Exception as e:
        return error_response(502, f"Gagal mengambil metadata: {e}")

    if not meta:
        return error_response(404, "Video tidak ditemukan atau private")

    return json_response({
        "status": "success",
        "video_id": video_id,
        "title": meta.get('title'),
        "author": meta.get('author_name'),
        "author_url": meta.get('author_url'),
        "thumbnail": meta.get('thumbnail_url'),
        "provider": meta.get('provider_name'),
    })


@youtube_bp.route('/download', methods=['GET'])
def youtube_download():
    url = request.args.get('url')
    if not url:
        return error_response(400, "Masukkan parameter ?url= dulu maseh!")

    video_id = _extract_video_id(url)
    if not video_id:
        return error_response(400, "URL YouTube tidak valid")

    fmt = (request.args.get('format') or 'mp4').lower()
    if fmt not in VALID_FORMATS:
        return error_response(400, f"Format tidak didukung: {fmt}. Pakai mp4 atau mp3.")

    video_quality = request.args.get('quality') or request.args.get('videoQuality') or '720'
    audio_bitrate = request.args.get('audioBitrate') or '128'
    vcodec = (request.args.get('vCodec') or 'h264').lower()

    try:
        meta = _fetch_metadata(video_id)
    except Exception:
        meta = None

    try:
        result = _convert(video_id, fmt, video_quality, audio_bitrate, vcodec)
    except Exception as e:
        return error_response(502, f"Gagal memproses konversi: {e}")

    if result.get('error'):
        return json_response({
            "status": "error",
            "video_id": video_id,
            "error": result.get('errorMsg') or "Konversi gagal",
        }, 502)

    return json_response({
        "status": "success",
        "video_id": video_id,
        "title": (meta or {}).get('title'),
        "channel": (meta or {}).get('author_name'),
        "thumbnail": (meta or {}).get('thumbnail_url'),
        "format": fmt,
        "quality": video_quality if fmt == 'mp4' else None,
        "filename": result.get('filename'),
        "download_link": result.get('url'),
    })
