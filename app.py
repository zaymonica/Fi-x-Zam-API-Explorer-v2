"""
app.py — Main Flask Application (migrated from worker.js)
Fi x Zam API — Python/Flask version for VPS deployment
"""
import os
from flask import Flask, send_from_directory, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'fi-x-zam-api-secret-2026')
# Don't redirect /foo -> /foo/ — trailing-slash redirects break HTTPS callers
# when running behind a reverse proxy that doesn't preserve scheme.
app.url_map.strict_slashes = False
# Trust the reverse-proxy headers so url_for / redirects use the original
# host + scheme (https) instead of the internal http://0.0.0.0:5000.
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1, x_proto=1, x_host=1, x_prefix=1,
)
CORS(app, resources={r"/*": {"origins": "*"}})

# ── Import Blueprints ───────────────────────────────────────────────
from routes.cors_proxy import cors_bp
from routes.sosmed import sosmed_bp
from routes.shinigami import shinigami_bp
from routes.drama import drama_bp
from routes.anime import anime_bp
from routes.freereels import freereels_bp
from routes.netshort import netshort_bp
from routes.meloshort import meloshort_bp
from routes.flickreels import flickreels_bp
from routes.terabox import terabox_bp
from routes.youtube import youtube_bp
from routes.moviebox import moviebox_bp
from routes.pinedrama import pinedrama_bp
from routes.admin import admin_bp, get_disabled_providers
from routes.downloader import downloader_bp
from routes.sonzai_bridge import sonzai_bp
from routes.sonzai_native import sonzai_native_bp
from routes.ggreels_bp import ggreels_bp

# NOTE: Blueprint short-drama LAMA (reelshort, melolo, goodshort, dramabox,
# shortmax, dramanova) SUDAH DIHAPUS — sekarang dilayani oleh provider BUNDLED
# via routes/sonzai_native.py di endpoint /sonzai/<provider>/...
# Blueprint lama rusak (nyangkut ke dramakuy.com & proxy mati).

# ── Register Blueprints ─────────────────────────────────────────────
app.register_blueprint(cors_bp)
app.register_blueprint(sosmed_bp)
app.register_blueprint(shinigami_bp)
app.register_blueprint(drama_bp)
app.register_blueprint(anime_bp)
app.register_blueprint(freereels_bp)
app.register_blueprint(netshort_bp)
app.register_blueprint(meloshort_bp)
app.register_blueprint(flickreels_bp)
app.register_blueprint(terabox_bp)
app.register_blueprint(youtube_bp)
app.register_blueprint(moviebox_bp)
app.register_blueprint(pinedrama_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(downloader_bp)
app.register_blueprint(sonzai_bp)
app.register_blueprint(sonzai_native_bp)
app.register_blueprint(ggreels_bp)

# ── Global Request Hook ─────────────────────────────────────────────
@app.before_request
def check_maintenance():
    # Only check standard endpoints, ignore static files, admin routes, and root
    if request.path.startswith('/admin') or request.path.startswith('/static') or request.path == '/':
        return

    # Strip trailing slash for matching
    path = request.path.rstrip('/')
    disabled = get_disabled_providers()

    # Provider-level: first path segment is the provider prefix
    segments = path.split('/')
    first_segment = segments[1] if len(segments) > 1 else ''  # [0] is empty string from leading /
    if first_segment and first_segment in disabled:
        from utils import json_response
        return json_response({
            "author": "Fi x Zam シ",
            "message": "error",
            "error": f"Provider '{first_segment}' is currently under maintenance"
        }, 503)

# ── Frontend (API Explorer) ─────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ── Error Handlers ──────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    from utils import json_response
    return json_response({'error': 'Not Found'}, 404)


@app.errorhandler(500)
def server_error(e):
    from utils import json_response
    return json_response({'error': 'Internal Server Error', 'message': str(e)}, 500)


# ── Run ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    
    print(f"""
    +==========================================+
    |     Fi x Zam API - Flask Edition         |
    |     Running on http://{host}:{port}        |
    +==========================================+
    """)
    
    app.run(host=host, port=port, debug=debug)
