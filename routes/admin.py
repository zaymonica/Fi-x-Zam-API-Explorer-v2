import os
import json
import hashlib
import secrets
from flask import Blueprint, request, session
from utils import json_response, error_response
from config import ADMIN_PASSWORD_HASH

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

MAINTENANCE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'maintenance.json')

# ── Auth helpers ─────────────────────────────────────────────────────
def _check_auth():
    """Return True if the session is authenticated as admin."""
    return session.get("_admin_auth") == ADMIN_PASSWORD_HASH

def _auth_required():
    if not _check_auth():
        return error_response(401, "Admin login required. POST /admin/login with {\"password\":\"...\"}")
    return None

# ── Maintenance data (provider-level) ────────────────────────────────
def get_disabled_providers():
    if not os.path.exists(MAINTENANCE_FILE):
        return []
    try:
        with open(MAINTENANCE_FILE, 'r') as f:
            data = json.load(f)
    except Exception:
        return []
    # Support old format (flat endpoint list) and new format ({"providers":[...]})
    if isinstance(data, list):
        return data  # old format — migrate
    return data.get("providers", [])

def save_disabled_providers(providers):
    os.makedirs(os.path.dirname(MAINTENANCE_FILE), exist_ok=True)
    with open(MAINTENANCE_FILE, 'w') as f:
        json.dump({"providers": providers}, f, indent=2)

# ── Routes ───────────────────────────────────────────────────────────
@admin_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    pw = data.get('password', '')
    if hashlib.md5(pw.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
        session['_admin_auth'] = ADMIN_PASSWORD_HASH
        return json_response({"status": "success", "message": "Logged in"})
    return error_response(403, "Invalid password")

@admin_bp.route('/logout', methods=['POST'])
def logout():
    session.pop('_admin_auth', None)
    return json_response({"status": "success", "message": "Logged out"})

@admin_bp.route('/status', methods=['GET'])
def admin_status():
    return json_response({
        "authenticated": _check_auth(),
        "disabled_providers": get_disabled_providers(),
        "available_providers": AVAILABLE_PROVIDERS,
    })

@admin_bp.route('/maintenance', methods=['GET'])
def get_maintenance():
    return json_response({
        "disabled_providers": get_disabled_providers(),
        "available_providers": AVAILABLE_PROVIDERS,
    })

@admin_bp.route('/toggle', methods=['POST'])
def toggle_maintenance():
    if (err := _auth_required()):
        return err
    data = request.get_json(force=True, silent=True) or {}
    provider = data.get('provider') or data.get('endpoint')
    disable = data.get('disable', True)
    if not provider:
        return error_response(400, "Missing 'provider' parameter")
    if provider not in AVAILABLE_PROVIDERS:
        return error_response(400, f"Unknown provider '{provider}'. Available: {AVAILABLE_PROVIDERS}")

    disabled = get_disabled_providers()
    if disable:
        if provider not in disabled:
            disabled.append(provider)
    else:
        if provider in disabled:
            disabled.remove(provider)
    save_disabled_providers(disabled)
    return json_response({
        "status": "success",
        "provider": provider,
        "disabled": disable,
        "disabled_providers": disabled,
    })

# ── All known providers ──────────────────────────────────────────────
AVAILABLE_PROVIDERS = [
    "melolo", "dramabox", "dramawave", "dramanova", "goodshort",
    "reelshort", "freereels", "netshort", "meloshort", "flickreels",
    "shortmax", "pinedrama", "moviebox", "anime", "drama",
]
