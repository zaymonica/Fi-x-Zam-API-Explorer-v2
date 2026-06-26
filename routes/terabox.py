"""
routes/terabox.py — TeraBox Downloader
Handles TeraBox scraping, session management (via local JSON), and download proxying.
Migrated from Supabase Edge Function (Deno) to Flask.
"""
import os
import json
import time
import random
import re
import string
import urllib.parse
import base64
from urllib.parse import urlparse, parse_qs, urlencode
import requests
from flask import Blueprint, request
from utils import json_response, error_response

terabox_bp = Blueprint('terabox', __name__, url_prefix='/terabox')

API_AUTHOR = "Sonzai X シ"
API_CONTACT = "https://t.me/November2k"

CORS_DOWNLOAD_BASE = "https://proxy.sonzaixlab.workers.dev/dl"
CORS_API_BASE = "https://proxy.sonzaixlab.workers.dev/tb"

TERABOX_DOWNLOAD_TOKEN_TTL_SECONDS = 60 * 60
TERABOX_DOWNLOAD_LINK_BATCH_SIZE = 5

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database')
os.makedirs(DB_DIR, exist_ok=True)
SESSION_DB_FILE = os.path.join(DB_DIR, 'terabox_session.json')


# ─── TeraBox Hardcoded Headers & Cookies ───────────────────────────────
TERABOX_CONFIG = {
    "HARDCODED_HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Connection": "keep-alive",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "sec-ch-ua-platform": '"Windows"',
        "X-Requested-With": "XMLHttpRequest",
        "sec-ch-ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "Content-Type": "application/x-www-form-urlencoded",
        "sec-ch-ua-mobile": "?0",
        "Sec-GPC": "1",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Cookie": 'browserid=4uGVT5WHMOTvRy4Pf013jm_jPUZFmLK7d9t5tJwXf-FHozt2R3iulSbS8No=; lang=en; TSID=kedM5xVXpQrEIS6OV7NG7lmxNHrwuAeG; shareUpdateRandom=1; BOXCLND=rKXMCMiJafcALWLw13GbEhNNgX333Oqfj3Zmc4Ifa7U%3D; ndus=Yvi55CYteHui5qeTCRggyZD-hIkt0Bjat0jVKUdf; csrfToken=36zCJZraVd6MP4ngCfCML4OW; ndut_fmt=91616057879171053DB677C528A7C174417DF3C6C6CE5A2696636BE1BAB2B2DF; ndut_fmv=20c98a0efe5e788baf60761acfbbcda0dca2dc2a6f61aafa4120509e6e72ad8f5c72bbae2586031a67d3fd4472341cbeda567a4ed9d4d7b6742b094e27cc5e258f53567ce20c5b5c5847312ebf0d6e8239f7f6c70a4644c93110c0342258503247fc6405f4a17b4a06eb9b3193600eef; g_state={"i_l":0,"i_ll":1781252961299,"i_b":"562qv1DlC12MoJzyfAtbEVwEJfBzSzRqUC0+acHGBBQ","i_e":{"enable_itp_optimization":0},"i_et":1781252722678}'
    },
    "FALLBACK_COOKIES": [
        'browserid=TtA7v5yR6Ww63FEgTr9PY1OZ6U5_NMhrolc_sNVMHqxBoheDrzWGMVVB0_A=; lang=en; TSID=57UEJEwAyKKRvoKek7ZUGes44RyCAyzr; shareUpdateRandom=12; ndus=Y2L-YenteHui7Sr1wyTFBOIQjLinLSkIZEgufot_; csrfToken=0DPF4idAcFw5nmkP2l5uSwHY; g_state={"i_l":0,"i_ll":1777196753712,"i_b":"n0sCe7X1O4lnsgBVxIBhGPgspZb8fW1Kb6r+Uttz7E4","i_e":{"enable_itp_optimization":0},"i_et":1777196753706}; ndut_fmt=050EF3F3799EDCD8E14DAA5D88D2EBB5FD8529E81F2975F9084000C8A63F886D; ndut_fmv=86007f3893c7cedda99c33d703c9c0e98ecd0580c01d1b5359cb70e7cd722b38ab5750dd338c3a7c51fa970fda43376ba8e19db3eed6c1c2648deb5f9ca6e054a66f1492f8877d8cd1c76783c07bc4cb3bdd0b0cb1571b0ceb63ba1c9487999f9ce21d4109bbfbaca0d256a30d68ff6c',
        'browserid=bHXwjpn0VMV3dL9stwTYVRDNwlmQ6kJnm-Gh0gNz6nO2T2-n1dbtewGsnMA=; lang=en; TSID=0nfQUYjScONbu0CXRFegH5B9It3WRY4E; shareUpdateRandom=72; ri=dm; ndus=YdueFBPpeHui_gP7bjKzQfnn8CzSyYhmbI8AgBWr; csrfToken=611BSR6w3EtIOxz3JB6X-njp; ndut_fmt=894A87436CEC92772A4F66C77E01C53CE1E392918CB10D2BF18749E3D5859E56; ndut_fmv=efbcf7bbf41b768952241c54fca14743ccaa7926c262b00f476946cf768141f0f9c08fcf58c55bc63e999f5311e60095776a99a4bcc725a09bfa521245f372db1f54231824258391ffbf2d00fc06f4a1fa3ebac4d6ed693c28e3e1ee86fc8655afc43001ac2027497fedf83a56f0bce9; g_state={"i_l":0,"i_ll":1774063601518,"i_b":"UUtRnBxLBsZPYNR8oBYTZYHf7YAC1y0nzZD8Z9htFOo","i_e":{"enable_itp_optimization":17}}',
        'browserid=yaAAEvCFra2xV9lGMIC4MUSTROZ0i4O1G4L1edQGv1Hp1oNEMzHiJOOt828C60VkpgyzrV9M9NAH8mAh; lang=en; TSID=YtaeBoctgPje67D1jeNpUP27AYguRWe0; shareUpdateRandom=72; ri=dm; ndus=Y4PdFBPpeHuimcpd3KRYlO6esqNmgZnZyTihEFc5; csrfToken=SbsT7Ag89l3II6fPa9DvHaal; ndut_fmt=D4230DA1049020FB282E457549CC41B3CF684B3D58C0B6EE3D0D69DFFAE46F2F; ndut_fmv=7219ead412f7c97da3718f5a1968c6c96361cf002fd2c4c522bb64ea064bcbba35883662fdb4278082c561a1d0f6d75f034759dcfe08ace918e03244f991c1183eff33bde7133e1d9f26d01348b739530524eeaa95e356995b50909186a7a3faa5b8a3fda5203edac41eea5d5add0b39; g_state={"i_l":0,"i_ll":1774063816513,"i_b":"/qhnJcIN42uRxMRJNMwFbbRwq5Ym3nZUs5JtBqPsrqo","i_e":{"enable_itp_optimization":13}}',
        'browserid=fN1EJwYBF70ZPOE6Ur8JnvYECPG2J8qcfAnkENPpGZJkNMsAUe1Vcs4hqOk=; lang=en; TSID=psb5aNbfRaXOxjpLRHosU2LBF0l0tKmj; shareUpdateRandom=35; ri=dm; ndus=Yu8VFBPpeHui_CXhiScW79bXt1Y3skWjsG4bC8BM; csrfToken=UWnOim9gs3OKglqunN9SyE2Y; ndut_fmt=42B0DA64E1AD2FEE666050F19410F03B407F07237DBCA5951CE6A350F8574189; ndut_fmv=3a2e9ec85528367d5ae60faaa609f93712770f2da98c37dd50be657ece033f494f351eba7e521c465eb704612416a6114911ab49780ac76a03aaf23937383db8e000d7732b9852e4093167b22630f1993560175f4a747f8b846cd8f5014b162c476ef74356625d97b979450ff0115ede; g_state={"i_l":0,"i_ll":1774064039400,"i_b":"PigfkMZ1MXL8kDY5NV3SC47kQTxEDInnqVI6RvGl2R8","i_e":{"enable_itp_optimization":0}}'
    ]
}

USER_AGENT_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 OPR/113.0.0.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0'
]

TERABOX_PRIMARY_ENDPOINTS = [
    {
        'origin': 'https://dm.1024tera.com',
        'list': 'https://dm.1024tera.com/share/list',
        'verify': 'https://dm.1024tera.com/share/verify',
        'siteReferer': 'https://www.1024tera.com/'
    },
    {
        'origin': 'https://dm.terabox.app',
        'list': 'https://dm.terabox.app/share/list',
        'verify': 'https://dm.terabox.app/share/verify',
        'siteReferer': 'https://www.terabox.app/'
    },
    {
        'origin': 'https://www.terabox.app',
        'list': 'https://www.terabox.app/share/list',
        'verify': 'https://www.terabox.app/share/verify',
        'siteReferer': 'https://www.terabox.app/'
    },
    {
        'origin': 'https://www.1024tera.com',
        'list': 'https://www.1024tera.com/share/list',
        'verify': 'https://www.1024tera.com/share/verify',
        'siteReferer': 'https://www.1024tera.com/'
    }
]

TERABOX_EXTRA_LIST_ENDPOINTS = [
    'https://terabox.com/share/list',
    'https://freeterabox.com/share/list',
    'https://teraboxapp.com/share/list'
]

RETRYABLE_TERABOX_ERRORS = {4000020, 4000018, -6, 400141, 400142, 460020, 400210}

# ─── Local Database ──────────────────────────────────────────────────────

def _db_read(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def _db_write(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to write to {filename}: {e}")

def _db_get(filename, key):
    data = _db_read(filename)
    return data.get(key)

def _db_put(filename, key, value):
    data = _db_read(filename)
    data[key] = value
    _db_write(filename, data)



# ─── Utility ─────────────────────────────────────────────────────────────

def _random_token(n=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

def _random_ua():
    return random.choice(USER_AGENT_POOL)

def _random_ip():
    ranges = [
        lambda: f"{random.randint(36, 40)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"{random.randint(101, 110)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"{random.randint(175, 179)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"{random.randint(180, 189)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
        lambda: f"{random.randint(85, 94)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
    ]
    return random.choice(ranges)()

def _get_cookies():
    return [c for c in [TERABOX_CONFIG["HARDCODED_HEADERS"]["Cookie"]] + TERABOX_CONFIG["FALLBACK_COOKIES"] if c]

def _is_folder(item):
    return str(item.get('isdir')) == '1'

def _extract_pcftoken(cookie_str):
    """Extract pcftoken from cookie string"""
    match = re.search(r'pcftoken=([^;]+)', cookie_str)
    if match:
        return match.group(1)
    return ''

def _is_likely_jstoken(token):
    return isinstance(token, str) and len(token) >= 32 and re.match(r'^[A-Za-z0-9_-]+$', token)

def _set_cookie_value(cookie_str, key, value):
    """Replace or add a key=value pair in a cookie string.
    If the key already exists, it is replaced; otherwise it is appended."""
    parts = [p.strip() for p in cookie_str.split(';') if p.strip()]
    found = False
    new_parts = []
    for part in parts:
        if '=' in part:
            k = part.split('=', 1)[0].strip()
            if k == key:
                new_parts.append(f"{key}={value}")
                found = True
            else:
                new_parts.append(part)
        else:
            new_parts.append(part)
    if not found:
        new_parts.append(f"{key}={value}")
    return '; '.join(new_parts)

def _proxy_tb_url(target_url, config):
    """Build a proxied URL that routes through CF Worker /tb endpoint.
    The Worker forwards the request from a clean Cloudflare edge IP."""
    encoded_cookie = base64.b64encode(config['headers'].get('Cookie', '').encode('utf-8')).decode('utf-8').rstrip('=')
    return f"{CORS_API_BASE}?url={urllib.parse.quote(target_url, safe='')}&cookie={encoded_cookie}"

def _proxy_tb_post_url(target_url, config, post_body):
    """Build a proxied POST URL that routes through CF Worker /tb endpoint.
    Sends method=POST and base64-encoded body so verify goes through the same IP as list calls."""
    encoded_cookie = base64.b64encode(config['headers'].get('Cookie', '').encode('utf-8')).decode('utf-8').rstrip('=')
    encoded_body = base64.b64encode(post_body.encode('utf-8')).decode('utf-8').rstrip('=')
    return f"{CORS_API_BASE}?url={urllib.parse.quote(target_url, safe='')}&cookie={encoded_cookie}&method=POST&body={urllib.parse.quote(encoded_body, safe='')}"

def _gen_dp_logid():
    """Generate a 20-digit dp-logid. TeraBox rejects malformed (too-long) values with errno 460020."""
    return f"{random.randint(10**19, 10**20 - 1)}"

def _extract_jstoken(html):
    sources = [html]
    for match in re.finditer(r'decodeURIComponent\(`([^`]+)`\)', html):
        try: sources.append(urllib.parse.unquote(match.group(1)))
        except: pass
    for match in re.finditer(r'decodeURIComponent\("([^"]+)"\)', html):
        try: sources.append(urllib.parse.unquote(match.group(1)))
        except: pass
    for match in re.finditer(r"decodeURIComponent\('([^']+)'\)", html):
        try: sources.append(urllib.parse.unquote(match.group(1)))
        except: pass

    patterns = [
        r'window\.jsToken\s*=\s*["\']([^"\']+)["\']',
        r'jsToken\s*=\s*["\']([^"\']+)["\']',
        r'["\']?jsToken["\']?\s*[:]\s*["\']([^"\']+)["\']',
        r'fn%28%22([^%]+)%22%29',
        r'fn\(\s*["\']jsToken["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
        r'fn\(\s*["\']([A-Za-z0-9_-]{32,})["\']\s*\)'
    ]

    for source in sources:
        for pattern in patterns:
            match = re.search(pattern, source)
            if match and _is_likely_jstoken(match.group(1)):
                return match.group(1)
    return None

def _get_endpoint_meta(list_url):
    for ep in TERABOX_PRIMARY_ENDPOINTS:
        if ep['list'] == list_url:
            return ep
    return None

def _get_endpoint_meta_by_verify(verify_url):
    """Find endpoint config by verify URL."""
    for ep in TERABOX_PRIMARY_ENDPOINTS:
        if ep['verify'] == verify_url:
            return ep
    return None

def _build_terabox_session(input_data):
    matched_primary = None
    for ep in TERABOX_PRIMARY_ENDPOINTS:
        if ep['origin'] == input_data.get('originBase') or \
           ep['list'] == input_data.get('preferredListUrl') or \
           ep['verify'] == input_data.get('preferredVerifyUrl'):
            matched_primary = ep
            break
    if not matched_primary:
        matched_primary = TERABOX_PRIMARY_ENDPOINTS[0]

    cookie = input_data.get('cookie') or TERABOX_CONFIG["HARDCODED_HEADERS"]["Cookie"]
    pref_list = input_data.get('preferredListUrl') or matched_primary['list']
    pref_verify = input_data.get('preferredVerifyUrl') or matched_primary['verify']

    list_endpoints = []
    for x in [TERABOX_PRIMARY_ENDPOINTS[0]['list'], pref_list] + \
             [ep['list'] for ep in TERABOX_PRIMARY_ENDPOINTS] + \
             TERABOX_EXTRA_LIST_ENDPOINTS:
        if x not in list_endpoints:
            list_endpoints.append(x)
            
    verify_endpoints = []
    for x in [TERABOX_PRIMARY_ENDPOINTS[0]['verify'], pref_verify] + \
             [ep['verify'] for ep in TERABOX_PRIMARY_ENDPOINTS]:
        if x not in verify_endpoints:
            verify_endpoints.append(x)

    headers = dict(TERABOX_CONFIG["HARDCODED_HEADERS"])
    headers['Cookie'] = cookie

    return {
        'jsToken': input_data.get('jsToken'),
        'cookie': cookie,
        'originBase': input_data.get('originBase') or matched_primary['origin'],
        'siteReferer': input_data.get('siteReferer') or matched_primary['siteReferer'] or matched_primary['origin'],
        'preferredListUrl': pref_list,
        'preferredVerifyUrl': pref_verify,
        'headers': headers,
        'listEndpoints': list_endpoints,
        'verifyEndpoints': verify_endpoints,
        'source': input_data.get('source', 'Terabox')
    }

# ─── Scraping & Fetching ─────────────────────────────────────────────────

def _get_shorturl_info(short_url, config, debug_log):
    """Get shorturl info using /api/shorturlinfo endpoint.
    Proxied through CF Worker to avoid VPS IP blocks."""
    ep_meta = _get_endpoint_meta(config.get('preferredListUrl'))
    origin = ep_meta['origin'] if ep_meta else config.get('originBase', 'https://dm.terabox.app')

    params = {
        'clientfrom': 'h5',
        'psign': '0',
        'pcftoken': _extract_pcftoken(config.get('headers', {}).get('Cookie', '')),
        'clienttype': '0',
        'channel': 'dubox',
        'shorturl': short_url,
        'root': '1',
        'scene': '',
        'app_id': '250528',
        'web': '1',
        'jsToken': config.get('jsToken', ''),
        'dp-logid': _gen_dp_logid()
    }

    target_url = f"{origin}/api/shorturlinfo?{urllib.parse.urlencode(params)}"
    proxy_url = _proxy_tb_url(target_url, config)

    try:
        r = requests.get(proxy_url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            errno = _get_errno(data)
            debug_log.append(f"Shorturl info: errno={errno}, fcount={data.get('fcount')}")
            return {'success': True, 'data': data}
    except Exception as e:
        debug_log.append(f"Shorturl info failed: {e}")

    return {'success': False}

def _fetch_terabox_list(short_url, dir_path, config, endpoints, debug_log, page=1):
    last_error_msg = ''
    last_endpoint = None
    data = None
    text = ""

    for endpoint in endpoints:
        ep_meta = _get_endpoint_meta(endpoint)
        origin_base = ep_meta['origin'] if ep_meta else config.get('originBase') or f"https://{urllib.parse.urlparse(endpoint).netloc}"

        params = {
            'clientfrom': 'h5',
            'psign': '0',
            'pcftoken': _extract_pcftoken(config.get('headers', {}).get('Cookie', '')),
            'clienttype': '0',
            'channel': 'dubox',
            'page': str(page),
            'num': '200',
            'web': '1',
            'scene': '',
            'shorturl': short_url,
            'by': 'time',
            'order': 'desc',
            'app_id': '250528',
            'jsToken': config.get('jsToken', ''),
            'dp-logid': _gen_dp_logid()
        }

        if dir_path == '/':
            params['root'] = '1'
        else:
            params['dir'] = dir_path

        target_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        proxy_url = _proxy_tb_url(target_url, config)

        try:
            r = requests.get(proxy_url, timeout=15)
            if r.status_code != 200:
                last_error_msg = f"HTTP {r.status_code}"
                last_endpoint = endpoint
                continue

            text = r.text
            last_endpoint = endpoint
            parsed = r.json()

            parsed_errno = _get_errno(parsed)
            if parsed_errno != 0 and parsed_errno in RETRYABLE_TERABOX_ERRORS:
                last_error_msg = f"API Error {parsed_errno} on {endpoint}"
                data = parsed
                continue

            has_missing = False
            for item in parsed.get('list', []):
                if not _is_folder(item) and not item.get('dlink'):
                    has_missing = True
                    break

            if parsed_errno == 0 and has_missing:
                last_error_msg = f"API stripped dlink on {endpoint}"
                data = parsed
                continue

            if parsed_errno == 0:
                debug_log.append(f"List OK via {endpoint} (page={page}, items={len(parsed.get('list', []))}).")

            return {'success': True, 'data': parsed, 'endpoint': endpoint}
        except Exception as e:
            last_error_msg = f"Invalid JSON or Network Error: {e}"
            last_endpoint = endpoint
            continue

    if data and 'errno' in data:
        return {
            'success': False,
            'error': 'no_dlink' if data.get('errno') == 0 else data.get('errno'),
            'msg': data.get('errmsg') or last_error_msg,
            'raw': data,
            'endpoint': last_endpoint
        }

    preview = text[:50].replace('\n', ' ') if text else last_error_msg
    debug_log.append(f"All domains failed at {dir_path}. Last: {preview}")
    return {'success': False, 'error': 'html_response', 'msg': 'Received HTML/Invalid JSON', 'endpoint': last_endpoint}

def _probe_terabox_session(short_url, candidate, debug_log):
    session = _build_terabox_session(candidate)
    probe = _fetch_terabox_list(short_url, '/', session, session['listEndpoints'][:3], debug_log)
    if not probe['success']:
        debug_log.append(f"Scraped session rejected ({probe.get('error')} => {probe.get('msg') or 'unusable'}).")
        return None

    matched_primary = _get_endpoint_meta(probe['endpoint'])
    hydrated = _build_terabox_session({
        **candidate,
        'originBase': matched_primary['origin'] if matched_primary else candidate.get('originBase'),
        'siteReferer': matched_primary['siteReferer'] if matched_primary else candidate.get('siteReferer'),
        'preferredListUrl': probe['endpoint'] or candidate.get('preferredListUrl'),
        'preferredVerifyUrl': matched_primary['verify'] if matched_primary else candidate.get('preferredVerifyUrl')
    })
    debug_log.append(f"Validated scraped session via {hydrated['preferredListUrl']}.")
    return hydrated

def _scrape_terabox_config(short_url, debug_log):
    cookies = _get_cookies()
    for i, cookie in enumerate(cookies):
        debug_log.append(f"Attempting scrape with cookie index {i}/{len(cookies)-1}...")
        for endpoint in TERABOX_PRIMARY_ENDPOINTS:
            share_url = f"{endpoint['origin']}/sharing/link?surl={short_url}&clearCache=1"
            ip = _random_ip()
            headers = {
                'User-Agent': _random_ua(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'X-Forwarded-For': ip,
                'X-Real-IP': ip,
                'Cookie': cookie
            }
            try:
                r = requests.get(share_url, headers=headers, timeout=10, allow_redirects=True)
                if r.status_code != 200:
                    debug_log.append(f"Cookie {i} on {endpoint['origin']} failed. HTTP {r.status_code}")
                    continue
                html = r.text
                if len(html) < 200:
                    debug_log.append(f"Cookie {i} on {endpoint['origin']} failed (Too short: {len(html)}).")
                    continue

                # Capture fresh cookies from Set-Cookie headers (browser sets ndut_fmt, ndut_fmv, etc)
                fresh_cookies = {}
                for c in r.cookies:
                    fresh_cookies[c.name] = c.value
                # Merge: original cookie + fresh Set-Cookie values (fresh wins)
                merged_parts = []
                for part in cookie.split(';'):
                    part = part.strip()
                    if '=' in part:
                        k = part.split('=', 1)[0].strip()
                        if k in fresh_cookies:
                            merged_parts.append(f"{k}={fresh_cookies.pop(k)}")
                        else:
                            merged_parts.append(part)
                # Add any remaining fresh cookies not in original
                for k, v in fresh_cookies.items():
                    merged_parts.append(f"{k}={v}")
                merged_cookie = '; '.join(merged_parts)

                js_token = _extract_jstoken(html)
                if js_token:
                    debug_log.append(f"Success: Token found with cookie {i} on {endpoint['origin']} (HTML len: {len(html)}, fresh cookies: {len(r.cookies)}).")
                    validated = _probe_terabox_session(short_url, {
                        'jsToken': js_token, 'cookie': merged_cookie, 'originBase': endpoint['origin'],
                        'siteReferer': endpoint['siteReferer'], 'preferredListUrl': endpoint['list'],
                        'preferredVerifyUrl': endpoint['verify'], 'source': 'SCRAPED_NEW'
                    }, debug_log)
                    if validated: return validated
                    continue

                if any(x in html for x in ['security-check', 'captcha', 'Access Denied', 'Just a moment']) or len(html) < 500:
                    debug_log.append(f"Cookie {i} on {endpoint['origin']} failed (Blocked).")
                else:
                    debug_log.append(f"Cookie {i} on {endpoint['origin']} failed (No token).")
            except Exception as e:
                debug_log.append(f"Cookie {i} on {endpoint['origin']} exception: {e}")
    debug_log.append("Failed: All cookies exhausted for token scraping.")
    return None

def _verify_password(short_url, pwd, config, debug_log=None):
    """Verify password via CF Worker proxy so BOXCLND session is associated
    with the same IP that will be used for subsequent share/list calls."""
    if debug_log is None:
        debug_log = []
    for endpoint in config.get('verifyEndpoints', []):
        try:
            ep_meta = _get_endpoint_meta_by_verify(endpoint)
            origin_base = ep_meta['origin'] if ep_meta else config.get('originBase')
            params = {
                'app_id': '250528', 'web': '1', 'channel': 'dubox', 'clienttype': '0',
                'jsToken': config['jsToken'], 'surl': short_url,
                'dp-logid': _gen_dp_logid()
            }
            post_body = f"pwd={urllib.parse.quote(pwd)}"
            target_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
            proxy_url = _proxy_tb_post_url(target_url, config, post_body)

            debug_log.append(f"Verifying password via proxy: {endpoint}")
            r = requests.get(proxy_url, timeout=15)
            data = r.json()
            debug_log.append(f"Verify response: errno={data.get('errno')}, has_randsk={bool(data.get('randsk'))}")
            if data.get('errno') == 0 and data.get('randsk'):
                return {'randsk': data['randsk'], 'endpoint': endpoint}
        except Exception as e:
            debug_log.append(f"Verify exception on {endpoint}: {e}")
    return None

def _get_errno(data):
    """Extract error code from API response — handles both 'errno' and 'code' keys."""
    return data.get('errno') if data.get('errno') is not None else data.get('code', 0)

def _scan_directory(short_url, dir_path, collection, debug_log, config):
    """Scan a directory with pagination support — fetches all pages."""
    page = 1
    page_size = 200
    max_pages = 50  # Safety limit to prevent infinite loops

    while page <= max_pages:
        if config.get('deadline') and time.time() > config['deadline']:
            debug_log.append("Timeout exceeded. Returning partial results.")
            return {'success': True, 'timeout': True}

        res = _fetch_terabox_list(short_url, dir_path, config, config['listEndpoints'], debug_log, page=page)
        if not res.get('success'):
            return {'error': res.get('error'), 'msg': res.get('msg'), 'raw': res.get('raw')}

        data = res['data']
        errno = _get_errno(data)
        if errno != 0:
            return {'error': errno, 'msg': data.get('errmsg'), 'raw': data}

        items = data.get('list', [])
        for item in items:
            if config.get('deadline') and time.time() > config['deadline']:
                debug_log.append("Timeout exceeded. Returning partial results.")
                return {'success': True, 'timeout': True}

            if _is_folder(item):
                sub = _scan_directory(short_url, item.get('path'), collection, debug_log, config)
                if sub.get('error') or sub.get('timeout'):
                    return sub
            else:
                if not item.get('dlink'):
                    debug_log.append(f"Skipping file without dlink: {item.get('server_filename')}")
                    continue

                collection.append({
                    'filename': item.get('server_filename'),
                    'size': item.get('size'),
                    'path': item.get('path'),
                    'base_link': item.get('dlink'),
                    'thumbnail': item.get('thumbs', {}).get('url3'),
                    'md5': item.get('md5'),
                    'category': item.get('category'),
                    '_short_url': short_url
                })

        # If this page returned fewer items than page_size, we've reached the end
        if len(items) < page_size:
            break
        page += 1

    return {'success': True}

# ─── Flask Routes ────────────────────────────────────────────────────────

@terabox_bp.route('/', methods=['GET'])
def terabox_index():
    url = request.args.get('url')
    if not url:
        return json_response({
            "author": API_AUTHOR,
            "contact": API_CONTACT,
            "status": "online",
            "service": "TeraBox API",
            "version": "1.0.0",
            "endpoints": {
                "terabox": "/terabox?url=TERABOX_URL",
                "terabox_with_pwd": "/terabox?url=TERABOX_URL&pwd=PASSWORD",
                "terabox_full": "/terabox?url=TERABOX_URL&cookie=BASE64_COOKIE&jstoken=JSTOKEN",
                "note": "cookie+jstoken must be from the same browser session (extract from DevTools → Application → Cookies & page source)"
            }
        })

    pwd = request.args.get('pwd')
    client_cookie = request.args.get('cookie')  # Optional: user-provided full cookie string
    client_jstoken = request.args.get('jstoken')  # Optional: user-provided jsToken (from same session as cookie)
    debug_log = []

    short_url = None
    try:
        # Handle redirect from 1024terabox.com to dm.terabox.app
        if '1024terabox.com' in url:
            debug_log.append("Detected 1024terabox.com URL, following redirect...")
            try:
                r = requests.get(url, allow_redirects=True, timeout=10, headers={
                    'User-Agent': _random_ua(),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
                })
                final_url = r.url
                debug_log.append(f"Redirected to: {final_url}")
                url = final_url
            except Exception as e:
                debug_log.append(f"Redirect failed: {e}, trying to extract surl manually...")

        if 'surl=' in url:
            short_url = parse_qs(urlparse(url).query).get('surl', [None])[0]
        if not short_url:
            match = re.search(r's/1?([A-Za-z0-9_-]+)', url)
            if match: short_url = match.group(1)
    except Exception as e:
        debug_log.append(f"URL parsing error: {e}")

    if not short_url:
        return error_response(400, "URL Invalid")

    debug_log.append(f"Extracted short URL: {short_url}")

    # If user provides both cookie AND jsToken (from same browser session), use them directly
    if client_cookie and client_jstoken:
        debug_log.append(f"Using client-provided jsToken + cookie (same session).")
        config = _build_terabox_session({
            'jsToken': client_jstoken, 'cookie': client_cookie,
            'originBase': 'https://dm.terabox.app',
            'preferredListUrl': 'https://dm.terabox.app/share/list',
            'preferredVerifyUrl': 'https://dm.terabox.app/share/verify',
            'source': 'CLIENT_PROVIDED'
        })
        config['headers']['Cookie'] = client_cookie
        config['deadline'] = time.time() + 25
    else:
        # Scrape fresh jsToken (it can expire anytime)
        debug_log.append("Scraping fresh jsToken...")
        session = _scrape_terabox_config(short_url, debug_log)
        if session:
            _db_put(SESSION_DB_FILE, 'current', session)
            source = 'SCRAPED_NEW'

        if not session:
            # Fallback to stored session if scrape fails
            session = _db_get(SESSION_DB_FILE, 'current')
            if session and _is_likely_jstoken(session.get('jsToken')):
                debug_log.append(f"Fallback to stored session: {session['jsToken'][:10]}...")
                session = _build_terabox_session({**session, 'source': 'Terabox'})
                source = 'STORED_FALLBACK'
            else:
                session = None

        if not session:
            return json_response({
                "author": API_AUTHOR, "contact": API_CONTACT, "status": "error",
                "source": "SCRAPE_FAILED", "request_url": url, "extracted_shorturl": short_url,
                "is_private": bool(pwd), "total_files": 0, "files": [], "debug": debug_log
            })

        config = _build_terabox_session(session)
        config['deadline'] = time.time() + 60 # 60s timeout for paginated scans

        # Merge client-provided cookie (with ndut_fmt, ndut_fmv, etc) into session
        if client_cookie:
            debug_log.append(f"Using client-provided cookie (len={len(client_cookie)}).")
            config['headers']['Cookie'] = client_cookie

    # Get shorturl info first — used to discover root folder structure
    root_folder = None
    info_res = _get_shorturl_info(short_url, config, debug_log)
    if info_res.get('success'):
        info_data = info_res['data']
        info_errno = _get_errno(info_data)
        debug_log.append(f"Share info: errno={info_errno}, fcount={info_data.get('fcount')}, owner={info_data.get('share_username')}")
        if info_data.get('list') and len(info_data['list']) > 0:
            first_item = info_data['list'][0]
            if _is_folder(first_item):
                root_folder = first_item.get('path')
                debug_log.append(f"Root is a folder: {root_folder}")

    all_files = []

    if pwd:
        v_res = _verify_password(short_url, pwd, config, debug_log)
        if v_res and v_res.get('randsk'):
            config['headers']['Cookie'] = _set_cookie_value(config['headers']['Cookie'], 'BOXCLND', v_res['randsk'])
            debug_log.append(f"Password verified via {v_res['endpoint']}.")
            debug_log.append(f"BOXCLND set to: {v_res['randsk']}")
            # Re-fetch shorturl info now that we have the password cookie (BOXCLND)
            # The pre-verify call would have failed with errno=2 for private links
            if not root_folder:
                info_res2 = _get_shorturl_info(short_url, config, debug_log)
                if info_res2.get('success'):
                    info_data2 = info_res2['data']
                    info_errno2 = _get_errno(info_data2)
                    debug_log.append(f"Post-verify share info: errno={info_errno2}, fcount={info_data2.get('fcount')}")
                    if info_data2.get('list') and len(info_data2['list']) > 0:
                        first_item = info_data2['list'][0]
                        if _is_folder(first_item):
                            root_folder = first_item.get('path')
                            debug_log.append(f"Root is a folder: {root_folder}")
        else:
            debug_log.append("Password verify failed.")

    # Try root scan first; if errno=2 or 460020 (folder at root / need verify), use discovered root folder
    res = _scan_directory(short_url, '/', all_files, debug_log, config)
    if res.get('error') in (2, 460020, 'no_dlink', 'html_response'):
        # Try to discover root_folder if we don't have one yet
        if not root_folder:
            info_retry = _get_shorturl_info(short_url, config, debug_log)
            if info_retry.get('success') and info_retry['data'].get('list'):
                first = info_retry['data']['list'][0]
                if _is_folder(first):
                    root_folder = first.get('path')
                    debug_log.append(f"Discovered root folder on retry: {root_folder}")
        if root_folder:
            debug_log.append(f"Root returned error={res.get('error')}, scanning discovered folder: {root_folder}")
            all_files = []
            config['deadline'] = time.time() + 25
            res = _scan_directory(short_url, root_folder, all_files, debug_log, config)

    # Retry if needed
    if res.get('error') in [2, 'no_dlink', 'html_response'] or res.get('error') in RETRYABLE_TERABOX_ERRORS or res.get('error') == 460020:
        debug_log.append(f"Primary session failed ({res.get('error')}). Re-scraping...")
        session = _scrape_terabox_config(short_url, debug_log)
        if session:
            _db_put(SESSION_DB_FILE, 'current', session)
            source = 'SCRAPED_REFRESH'
            config = _build_terabox_session(session)
            config['deadline'] = time.time() + 25
            # Re-apply client cookie after config rebuild
            if client_cookie:
                config['headers']['Cookie'] = client_cookie
            all_files = []
            if pwd:
                v_res = _verify_password(short_url, pwd, config, debug_log)
                if v_res and v_res.get('randsk'):
                    config['headers']['Cookie'] = _set_cookie_value(config['headers']['Cookie'], 'BOXCLND', v_res['randsk'])
            res = _scan_directory(short_url, '/', all_files, debug_log, config)
            if res.get('error') in (2, 460020, 'no_dlink', 'html_response'):
                # Try root_folder from shorturlinfo
                if not root_folder:
                    info2 = _get_shorturl_info(short_url, config, debug_log)
                    if info2.get('success') and info2['data'].get('list'):
                        first = info2['data']['list'][0]
                        if _is_folder(first):
                            root_folder = first.get('path')
                            debug_log.append(f"Retry: discovered root folder: {root_folder}")
                if root_folder:
                    debug_log.append(f"Retry: scanning folder: {root_folder}")
                    all_files = []
                    config['deadline'] = time.time() + 25
                    res = _scan_directory(short_url, root_folder, all_files, debug_log, config)

    # Build proxy download links for Cloudflare Worker
    for f in all_files:
        # Build Cloudflare Worker download link (bypassing VPS bandwidth)
        encoded_dlink = base64.b64encode(f['base_link'].encode('utf-8')).decode('utf-8').rstrip('=')
        encoded_cookie = base64.b64encode(config['headers']['Cookie'].encode('utf-8')).decode('utf-8').rstrip('=')
        f['download_link'] = f"{CORS_DOWNLOAD_BASE}?url={encoded_dlink}&cookie={encoded_cookie}"

        del f['_short_url']
        del f['base_link']

    return json_response({
        "author": API_AUTHOR, "contact": API_CONTACT,
        "status": "success" if all_files else "error",
        "source": source, "request_url": url, "extracted_shorturl": short_url,
        "is_private": bool(pwd), "total_files": len(all_files),
        "files": all_files, "debug": debug_log
    })


