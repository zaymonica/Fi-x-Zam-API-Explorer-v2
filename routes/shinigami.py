"""
routes/shinigami.py — Shinigami Manga (migrated from backend/shinigami.js)
"""
import io
import random
import requests as http_requests
from flask import Blueprint, request, Response
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import SHINIGAMI_API_URL, SHINIGAMI_USER_AGENT, SHINIGAMI_PROXY_BASE, SHINIGAMI_PROXY_KEYS, CORS_HEADERS
from utils import json_response

shinigami_bp = Blueprint('shinigami', __name__)

SHINI_HEADERS = {
    'User-Agent': SHINIGAMI_USER_AGENT,
    'Accept': 'application/json',
    'referer': 'https://id.shinigami.asia/'
}


def _build_shini_url(url: str) -> str:
    """Build proxied URL and rotate corsproxy key per request."""
    if not SHINIGAMI_PROXY_BASE:
        return url

    parsed = urlsplit(SHINIGAMI_PROXY_BASE)
    if not parsed.scheme or not parsed.netloc:
        return url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query['url'] = url
    if SHINIGAMI_PROXY_KEYS:
        query['key'] = random.choice(SHINIGAMI_PROXY_KEYS)

    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path or '/',
        urlencode(query),
        parsed.fragment
    ))


def _shini_get(url: str, headers=None, timeout=15):
    """HTTP GET helper for Shinigami with optional proxy wrapping."""
    return http_requests.get(_build_shini_url(url), headers=headers, timeout=timeout)


@shinigami_bp.route('/shinigami', defaults={'subpath': ''}, methods=['GET', 'POST', 'OPTIONS'])
@shinigami_bp.route('/shinigami/<path:subpath>', methods=['GET', 'POST', 'OPTIONS'])
def handle_shinigami(subpath):
    if request.method == 'OPTIONS':
        return json_response({}, 200)

    path = f'/{subpath}' if subpath else ''

    # /shinigami/home
    if path == '/home' or path.startswith('/home'):
        page = request.args.get('page', '1')
        target_url = f"{SHINIGAMI_API_URL}/v1/manga/list?page={page}&page_size=24&sort=latest&sort_order=desc"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        return json_response(res.json())

    # /shinigami/populer
    if path == '/populer' or path.startswith('/populer'):
        page = request.args.get('page', '1')
        target_url = f"{SHINIGAMI_API_URL}/v1/manga/list?page={page}&page_size=24&sort=popularity&sort_order=desc"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        return json_response(res.json())

    # /shinigami/search
    if path == '/search' or path.startswith('/search'):
        query = request.args.get('q', '')
        target_url = f"{SHINIGAMI_API_URL}/v1/manga/list?page=1&page_size=100&sort=latest&sort_order=desc&q={query}"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        return json_response(res.json())

    # /shinigami/detail/chapter/<id>
    if path.startswith('/detail/chapter/'):
        chapter_id = path.split('/')[-1]
        target_url = f"{SHINIGAMI_API_URL}/v1/chapter/detail/{chapter_id}"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        return json_response(res.json())

    # /shinigami/detail/manga/<id>
    if path.startswith('/detail/manga/'):
        manga_id = path.split('/')[-1]
        target_url = f"{SHINIGAMI_API_URL}/v1/manga/detail/{manga_id}"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        return json_response(res.json())

    # /shinigami/chapter/<id>
    if path.startswith('/chapter/'):
        manga_id = path.split('/')[-1]
        target_url = f"{SHINIGAMI_API_URL}/v1/chapter/{manga_id}/list?page=1&page_size=10000&sort_by=chapter_number&sort_order=asc"
        res = _shini_get(target_url, headers=SHINI_HEADERS, timeout=15)
        if not res.ok:
            return json_response({'error': f'Upstream error {res.status_code}'}, res.status_code)
        data = res.json()
        if data.get('data') and isinstance(data['data'], list):
            for chapter in data['data']:
                chapter['pdf_download'] = f"{request.host_url.rstrip('/')}/shinigami/download/{chapter.get('chapter_id', '')}"
        return json_response(data)

    # /shinigami/download/<id>
    if path.startswith('/download/'):
        chapter_id = path.split('/')[-1]
        return generate_shinigami_pdf(chapter_id)

    # POST - manual upload
    if request.method == 'POST':
        return handle_shinigami_manual_upload()

    return Response('Shinigami Route Ready.', status=200, headers=CORS_HEADERS)


def generate_shinigami_pdf(chapter_id):
    """Generate PDF from manga chapter images using reportlab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdf_canvas
        from PIL import Image

        detail_url = f"{SHINIGAMI_API_URL}/v1/chapter/detail/{chapter_id}"
        detail_res = _shini_get(detail_url, headers={'User-Agent': SHINIGAMI_USER_AGENT}, timeout=15)
        if not detail_res.ok:
            return json_response({'error': 'Failed fetch info'}, 500)

        data = detail_res.json()
        base = data['data']['base_url']
        img_path = data['data']['chapter']['path']
        files = data['data']['chapter']['data']

        if not img_path.endswith('/'):
            img_path += '/'

        # Create PDF in memory
        pdf_buffer = io.BytesIO()

        # Download all images first
        images = []
        for filename in files:
            img_url = f"{base}{img_path}{filename}"
            try:
                img_res = _shini_get(img_url, headers={'User-Agent': SHINIGAMI_USER_AGENT}, timeout=15)
                if img_res.ok:
                    img = Image.open(io.BytesIO(img_res.content))
                    images.append(img)
            except Exception:
                continue

        if not images:
            return json_response({'error': 'No images found'}, 404)

        # Create PDF with reportlab
        c = pdf_canvas.Canvas(pdf_buffer)
        for img in images:
            width, height = img.size
            c.setPageSize((width, height))
            # Save image to temp buffer
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG')
            img_buffer.seek(0)

            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(img_buffer), 0, 0, width=width, height=height)
            c.showPage()

        c.save()
        pdf_buffer.seek(0)

        chapter_number = data['data'].get('chapter_number', chapter_id)
        headers = {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'attachment; filename="chapter-{chapter_number}.pdf"',
            **CORS_HEADERS
        }
        return Response(pdf_buffer.getvalue(), status=200, headers=headers)

    except Exception as error:
        return json_response({'error': f'PDF Gen Error: {str(error)}'}, 500)


def handle_shinigami_manual_upload():
    """Handle manual image upload to PDF conversion."""
    try:
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image

        if 'file' not in request.files and not request.files:
            return json_response({'error': 'No files uploaded'}, 400)

        images = []
        for key in request.files:
            file = request.files[key]
            img = Image.open(file.stream)
            images.append(img)

        pdf_buffer = io.BytesIO()
        c = pdf_canvas.Canvas(pdf_buffer)

        for img in images:
            width, height = img.size
            c.setPageSize((width, height))
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG')
            img_buffer.seek(0)
            c.drawImage(ImageReader(img_buffer), 0, 0, width=width, height=height)
            c.showPage()

        c.save()
        pdf_buffer.seek(0)

        headers = {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="manual-convert.pdf"',
            **CORS_HEADERS
        }
        return Response(pdf_buffer.getvalue(), status=200, headers=headers)

    except Exception as e:
        return Response(str(e), status=500)
