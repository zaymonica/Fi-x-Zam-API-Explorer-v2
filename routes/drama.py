"""
routes/drama.py — Drama (Drakor) handler
Scraper untuk drakorid.co — token dinamis + HTML scraping.

Flow stream:
  /go/<id> -> redirect /nonton/<slug>/ (scrape mId, link, token)
  -> POST /myapi/episode_detail.php (id, episode) -> {streaming}
  -> GET /watch-dfast/<slug>/<ep> -> player/bunny.php?v=<base64 m3u8>
  -> base64 decode -> hls.drakor.cc m3u8
"""
import re
import base64
import binascii
import requests as http_requests
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
from flask import Blueprint, request

from utils import json_response, error_response, clean_synopsis_advanced
from config import DRAMA_COOKIE

drama_bp = Blueprint('drama', __name__)

BASE = "https://drakorid.co"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Referer": BASE + "/",
}
if DRAMA_COOKIE:
    BASE_HEADERS["Cookie"] = DRAMA_COOKIE

AJAX_HEADERS = {**BASE_HEADERS, "X-Requested-With": "XMLHttpRequest"}

_TOKEN_NOW_RE = re.compile(r'token_now\s*=\s*"([^"]+)"')
_TOKEN_VAR_RE = re.compile(r'var\s+token\s*=\s*"([^"]+)"')
_MID_RE = re.compile(r'var\s+mId\s*=\s*(\d+)')
_LINK_RE = re.compile(r'var\s+link\s*=\s*"([^"]+)"')
_MTIPE_RE = re.compile(r'var\s+mTipe\s*=\s*(\d+)')
_GOID_RE = re.compile(r'/go/(\d+)')
_BUNNY_V_RE = re.compile(r'player/bunny\.php\?c=[^&]*&v=([^"\'&]+)')


def _http_get(url, **kwargs):
    kwargs.setdefault('headers', BASE_HEADERS)
    kwargs.setdefault('timeout', 20)
    return http_requests.get(url, **kwargs)


def _fetch_home_token():
    """Grab the rotating token_now from the homepage HTML."""
    r = _http_get(BASE + "/")
    m = _TOKEN_NOW_RE.search(r.text)
    return m.group(1) if m else None


def _ajax_cards(php_path, token, query=None):
    """POST a token to an /ajax/*.php endpoint and parse the returned cards."""
    url = f"{BASE}/ajax/{php_path}"
    if query:
        url += "?" + query
    r = http_requests.post(url, headers=AJAX_HEADERS, data={'token': token}, timeout=20)
    return _parse_cards(r.text)


def _b64decode_loose(s):
    """Decode base64 that may use urlsafe alphabet and lack padding."""
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode('utf-8', 'replace')
    except (binascii.Error, ValueError):
        return None


def _fetch_detail_page(id_=None, slug=None):
    """Fetch the /nonton/<slug>/ detail page from either a /go/<id> or a slug."""
    if id_:
        return _http_get(f"{BASE}/go/{id_}", allow_redirects=True)
    return _http_get(f"{BASE}/nonton/{slug}/", allow_redirects=True)


def _parse_cards(html):
    """Parse a block of <div class="item"><div class="card">... into items."""
    soup = BeautifulSoup(html, 'lxml')
    items = []
    for card in soup.select('div.card'):
        a = card.find('a', href=True)
        link = a['href'] if a else None
        gid = None
        slug = None
        if link:
            mm = _GOID_RE.search(link)
            if mm:
                gid = mm.group(1)
            sm = re.search(r'/nonton/([^/]+)/?', link)
            if sm:
                slug = sm.group(1)
        img = card.find('img')
        image = img.get('src') if img else None
        h5 = card.select_one('.card-body h5')
        title = ''
        if h5:
            title = (h5.get('data-original-title') or h5.get_text(strip=True) or '').strip()
        badge = card.find('span', class_='badge')
        episode = None
        if badge:
            bm = re.search(r'(\d+)', badge.get_text())
            if bm:
                episode = bm.group(1)
        if not gid and not title:
            continue
        item = {'id': gid, 'title': title, 'image': image, 'link': link}
        if slug:
            item['slug'] = slug
        if episode is not None:
            item['episode'] = episode
        items.append(item)
    return items


def _parse_details_block(p_tag):
    """Parse the Details <p> block into a dict.
    Format:
        Details
        Drama: Name (English title) / Alt Title (working title)
        Revised romanization: X
        Hangul: 한글
        Director: Name
        Writer: Names
        Network: Netflix
        Episodes: 10
        Genres: Action, Thriller, ...
        Release Date: June 5, 2026
        Duration: 60 min.
        Language: Korean
        Country: South Korea
    """
    details = {}
    # Extract HTML line-by-line using <br> splits
    html_str = str(p_tag)
    # Remove the opening <p ...> and closing </p>
    html_str = re.sub(r'^<p[^>]*>', '', html_str)
    html_str = re.sub(r'</p>$', '', html_str)
    # Split on <br> or <br />
    lines = re.split(r'<br\s*/?>', html_str)
    lines = [BeautifulSoup(l, 'lxml').get_text(strip=True) for l in lines]
    lines = [l for l in lines if l]

    # First line is "Details" header — skip
    for line in lines[1:]:
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip().lower()
            value = value.strip()
            # Map keys
            if key == 'drama':
                details['drama'] = value
            elif key == 'revised romanization':
                details['romanization'] = value
            elif key == 'hangul':
                details['hangul'] = value
            elif key == 'director':
                details['director'] = [d.strip() for d in value.split(',') if d.strip()]
            elif key == 'writer':
                details['writer'] = [w.strip() for w in value.split(',') if w.strip()]
            elif key == 'network':
                details['network'] = value
            elif key == 'episodes':
                try:
                    details['episodes'] = int(re.search(r'(\d+)', value).group(1))
                except (ValueError, AttributeError):
                    details['episodes'] = value
            elif key == 'genres':
                details['genres'] = [g.strip() for g in value.split(',') if g.strip()]
            elif key == 'release date':
                details['release_date'] = value
            elif key == 'duration':
                details['duration'] = value
            elif key == 'language':
                details['language'] = value
            elif key == 'country':
                details['country'] = value
            elif key == 'cast':
                pass  # ignore, handled separately

    return details


def _parse_sinopsis_block(p_tag):
    """Extract synopsis text from a Sinopsis <p> block, stripping the header."""
    text = p_tag.get_text('\n', strip=True)
    text = re.sub(r'^Sinopsis\s*', '', text, flags=re.I).strip()
    return text


def _parse_support_role(p_tag):
    """Parse Support Role <p> block.
    Format: Support Role<br />Name1 - Role1 [note]<br />Name2 - Role2"""
    html_str = str(p_tag)
    html_str = re.sub(r'^<p[^>]*>', '', html_str)
    html_str = re.sub(r'</p>$', '', html_str)
    lines = re.split(r'<br\s*/?>', html_str)
    lines = [BeautifulSoup(l, 'lxml').get_text(strip=True) for l in lines]
    lines = [l for l in lines if l and not re.match(r'Support Role', l, re.I)]

    result = []
    for line in lines:
        # Pattern: Name - Role [note]
        match = re.match(r'(.+?)\s*-\s*(.+)', line)
        if match:
            name = match.group(1).strip()
            role_raw = match.group(2).strip()
            # Extract note in brackets
            note = None
            note_m = re.search(r'\[([^\]]+)\]', role_raw)
            if note_m:
                note = note_m.group(1)
                role_raw = re.sub(r'\s*\[[^\]]+\]\s*', '', role_raw).strip()
            result.append({'name': name, 'role': role_raw, 'note': note})
        else:
            result.append({'name': line, 'role': '', 'note': None})

    return result


# ─── Routes ──────────────────────────────────────────────────────────────

@drama_bp.route('/drama', defaults={'subpath': ''}, methods=['GET'])
@drama_bp.route('/drama/<path:subpath>', methods=['GET'])
def handle_drama(subpath):
    path = f'/{subpath}' if subpath else ''
    try:
        # ── Index feeds (token-gated AJAX) ──────────────────────────────
        feed_map = {
            '/terbaru': 'index_terbaru.php',
            '/trending': 'index_trending.php',
            '/ongoing': 'index_ongoing.php',
            '/slider': 'index_slider.php',
        }
        if path in feed_map:
            token = _fetch_home_token()
            if not token:
                return json_response({'status': False, 'error': 'Gagal ambil token'}, 502)
            data = _ajax_cards(feed_map[path], token)
            return json_response({'status': True, 'count': len(data), 'data': data})

        # ── Category (kategori passed as query) ─────────────────────────
        if path == '/home/korea':
            token = _fetch_home_token()
            data = _ajax_cards('index_kategori.php', token, query='kategori=' + quote('Drama Korea'))
            return json_response({'status': True, 'count': len(data), 'data': data})
        if path == '/home/china':
            token = _fetch_home_token()
            data = _ajax_cards('index_kategori.php', token, query='kategori=' + quote('Drama China'))
            return json_response({'status': True, 'count': len(data), 'data': data})
        if path == '/category' or path.startswith('/category'):
            kat = request.args.get('kategori') or request.args.get('q')
            if not kat:
                return json_response({'status': False, 'message': "Parameter 'kategori' wajib diisi"}, 400)
            token = _fetch_home_token()
            data = _ajax_cards('index_kategori.php', token, query='kategori=' + quote(kat))
            return json_response({'status': True, 'kategori': kat, 'count': len(data), 'data': data})

        # ── Search (server-rendered page) ───────────────────────────────
        if path == '/search' or path.startswith('/search'):
            q = request.args.get('q')
            if not q:
                return json_response({'status': False, 'message': "Parameter 'q' wajib diisi"}, 400)
            r = _http_get(f"{BASE}/cari.html?q={quote(q)}")
            data = _parse_cards(r.text)
            return json_response({'status': True, 'query': q, 'count': len(data), 'data': data})

        # ── Detail ─────────────────────────────────────────────────────
        if path == '/detail' or path.startswith('/detail'):
            id_ = request.args.get('id')
            slug_arg = request.args.get('slug')
            if not id_ and not slug_arg:
                return json_response({'status': False, 'message': "Parameter 'id' atau 'slug' wajib diisi"}, 400)
            r = _fetch_detail_page(id_=id_, slug=slug_arg)
            html = r.text
            soup = BeautifulSoup(html, 'lxml')

            # ── title ──
            title_el = soup.select_one('h3.title')
            title = title_el.get_text(strip=True) if title_el else ''
            if not title:
                og = soup.find('meta', property='og:title')
                if og:
                    title = re.sub(r'\s*Sub Indo.*$', '', og.get('content', '')).strip()

            # ── poster ──
            poster_el = soup.select_one('img.poster-img')
            poster = poster_el.get('src') if poster_el else None

            # ── script vars ──
            mid_m = _MID_RE.search(html)
            mid = mid_m.group(1) if mid_m else id_
            link_m = _LINK_RE.search(html)
            slug = link_m.group(1) if link_m else slug_arg
            tipe_m = _MTIPE_RE.search(html)
            is_series = bool(tipe_m and tipe_m.group(1) == '2')

            # ── categories (chips above tabs) ──
            categories = [c.get_text(strip=True) for c in soup.select('#kategoriMe a.chip .chip-label')]

            # ── stats: views & loves ──
            stat_chips = soup.select('#deskripsi .chip-media .chip-label')
            views = stat_chips[0].get_text(strip=True) if len(stat_chips) > 0 else None
            loves = stat_chips[1].get_text(strip=True) if len(stat_chips) > 1 else None

            # ── artists carousel ──
            artists = []
            for item in soup.select('#list-artists .item'):
                a = item.find('a', href=True)
                img = item.find('img')
                h5 = item.find('h5')
                name = h5.get_text(strip=True) if h5 else None
                artists.append({
                    'name': name,
                    'link': a['href'] if a else None,
                    'image': img.get('src') if img else None,
                })

            # ── scrape #deskripsi tab content ──
            deskripsi = soup.select_one('#deskripsi')
            synopsis = ''
            details = {}
            main_cast = []
            support_role = []
            based_on = None
            related_content = None

            if deskripsi:
                children = list(deskripsi.children)

                # Walk children to find Details, Sinopsis, and Cast sections
                current_section = None
                for child in children:
                    if not hasattr(child, 'get_text'):
                        continue
                    text = child.get_text(strip=True)
                    if not text:
                        continue

                    # Detect section headers by text content (some have content inline)
                    if child.name == 'p' and text.lower().startswith('details'):
                        current_section = 'details'
                        details = _parse_details_block(child)
                        continue
                    elif child.name == 'p' and text.lower().startswith('sinopsis'):
                        current_section = 'sinopsis'
                        synopsis = _parse_sinopsis_block(child)
                        continue
                    elif child.name == 'p' and text.lower().startswith('based on'):
                        current_section = 'based_on'
                        based_on = text[8:].strip().lstrip(':').strip()
                        continue
                    elif child.name == 'p' and text.lower().startswith('related content'):
                        current_section = 'related'
                        related_content = text[15:].strip().lstrip(':').strip()
                        continue
                    elif child.name == 'h2' and re.search(r'Cast', text, re.I):
                        current_section = 'cast'
                        continue
                    elif child.name == 'h3':
                        current_section = None  # skip "Daftar Pemeran" etc
                        continue

                    # Process content based on current section (when content is in separate element)
                    if current_section == 'cast':
                        if child.name == 'ul':
                            for li in child.find_all('li', recursive=False):
                                a = li.find('a')
                                li_text = li.get_text(strip=True)
                                if a:
                                    main_cast.append({'name': a.get_text(strip=True), 'role': li_text.replace(a.get_text(strip=True), '').strip('- ').strip(), 'link': a.get('href')})
                                else:
                                    main_cast.append({'name': li_text, 'role': '', 'link': None})
                        elif child.name == 'p':
                            support_role = _parse_support_role(child)

            # ── fallback synopsis from og:description ──
            if not synopsis:
                og_desc = soup.find('meta', property='og:description')
                synopsis = clean_synopsis_advanced(og_desc.get('content', '')) if og_desc else ''

            # ── episodes with markers ──
            episodes = []
            ep_btns = soup.select('.episode-pick-num[data-episode]')
            for btn in ep_btns:
                ep_num = int(btn.get('data-episode'))
                classes = btn.get('class', [])
                episodes.append({
                    'episode': ep_num,
                    'premium': 'is-premium' in classes,
                    'end': 'is-end' in classes,
                })
            episodes.sort(key=lambda e: e['episode'])

            return json_response({
                'status': True,
                'id': mid,
                'slug': slug,
                'title': title,
                'image': poster,
                'is_series': is_series,
                'total_episode': len(episodes) if episodes else (1 if not is_series else 0),
                'episodes': episodes,
                'categories': categories,
                'views': views,
                'loves': loves,
                'artists': artists,
                'details': details,
                'based_on': based_on,
                'related_content': related_content,
                'synopsis': synopsis,
                'cast': {
                    'main': main_cast,
                    'support': support_role,
                },
                'final_url': r.url,
            })

        # ── Stream ──────────────────────────────────────────────────────
        if path == '/stream' or path.startswith('/stream'):
            id_ = request.args.get('id')
            slug_arg = request.args.get('slug')
            if not id_ and not slug_arg:
                return json_response({'status': False, 'message': "Parameter 'id' atau 'slug' wajib diisi"}, 400)
            ep = request.args.get('ep') or request.args.get('episode') or '1'

            # 1. Resolve detail page (via /go/<id> or /nonton/<slug>/), grab token + slug + mId
            r = _fetch_detail_page(id_=id_, slug=slug_arg)
            html = r.text
            token_m = _TOKEN_VAR_RE.search(html)
            link_m = _LINK_RE.search(html)
            mid_m = _MID_RE.search(html)
            if not (token_m and link_m and mid_m):
                return json_response({'status': False, 'error': 'Gagal parse halaman detail'}, 502)
            token = token_m.group(1)
            slug = link_m.group(1)
            mid = mid_m.group(1)

            # 2. episode_detail.php -> streaming id + img
            ed = http_requests.post(
                f"{BASE}/myapi/episode_detail.php",
                headers={**AJAX_HEADERS, 'Referer': r.url},
                data={'token': token, 'id': mid, 'episode': ep},
                timeout=20,
            )
            try:
                meta = ed.json()
            except ValueError:
                return json_response({'status': False, 'error': 'episode_detail bukan JSON', 'raw': ed.text[:200]}, 502)
            if str(meta.get('status')) != '1':
                return json_response({'status': False, 'error': meta.get('error_msg') or 'Episode tidak tersedia', 'raw': meta}, 404)

            # 3. watch page -> bunny player -> decode base64 m3u8
            sources = []
            # 3. watch page -> bunny player -> decode base64 m3u8
            sources = []
            login_wall = False
            for metode in ('dfast', 'sfast'):
                try:
                    wr = _http_get(f"{BASE}/watch-{metode}/{slug}/{ep}", allow_redirects=True)
                except http_requests.RequestException:
                    continue
                if 'streaming 1x' in wr.text or 'belum login' in wr.text:
                    login_wall = True
                for enc in _BUNNY_V_RE.findall(wr.text):
                    dec = _b64decode_loose(enc)
                    if dec and dec.startswith('http') and dec not in [s['url'] for s in sources]:
                        quality_m = re.search(r'/(\d{3,4})p/', dec)
                        sources.append({
                            'method': metode,
                            'quality': (quality_m.group(1) + 'p') if quality_m else 'auto',
                            'type': 'hls',
                            'url': dec,
                        })

            if not sources:
                if login_wall:
                    return json_response({
                        'status': False,
                        'error': 'Limit guest tercapai — drakorid.co membatasi streaming 1x/hari untuk guest. Perlu cookie login.',
                        'login_required': True,
                        'streaming_id': meta.get('streaming'),
                    }, 403)
                return json_response({'status': False, 'error': 'Tidak ada source video ditemukan',
                                      'streaming_id': meta.get('streaming')}, 502)

            return json_response({
                'status': True,
                'id': mid,
                'slug': slug,
                'episode': ep,
                'streaming_id': meta.get('streaming'),
                'thumbnail': meta.get('img'),
                'data_stream': sources,
            })

    except http_requests.RequestException as e:
        return json_response({'status': False, 'error': f'Network error: {e}'}, 502)
    except Exception as e:
        return json_response({'status': False, 'error': str(e)}, 500)

    return error_response(404, 'Drama Endpoint Not Found')
