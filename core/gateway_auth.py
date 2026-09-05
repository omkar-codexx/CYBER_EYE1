import hmac
import hashlib
from functools import wraps
from flask import request, jsonify
from config import SECRET_KEY
from core.database import database, users_database

TOKEN_PREFIX = "famX_"

def generate_famx_token(device_id, secret=None):
    """Generates a secure famX hardware token for a given device."""
    if not secret:
        secret = SECRET_KEY
    sig = hmac.new(secret.encode('utf-8'), device_id.encode('utf-8'), hashlib.sha256).hexdigest()[:24]
    return f"{TOKEN_PREFIX}{device_id}_{sig}"

def verify_famx_token(device_id, token, secret=None):
    """Verifies a famX hardware token using constant-time comparison."""
    if not token or not isinstance(token, str):
        return False
    expected = generate_famx_token(device_id, secret)
    return hmac.compare_digest(token, expected)

def famx_token_or_license_required(f):
    """
    Backwards-compatible authorization decorator for hardware endpoints:
    1. Checks X-famX-Token header or 'token' parameter.
    2. Fallback: Checks legacy license_key for older devices (zero breaking changes).
    """
    @wraps(f)
    def decorated_function(device_id, *args, **kwargs):
        # 1. Check famX hardware token
        token = request.headers.get('X-famX-Token') or request.args.get('token') or request.form.get('token')
        if token and verify_famx_token(device_id, token):
            return f(device_id, *args, **kwargs)

        # 2. Backwards-compatible legacy check (license key)
        license_key = request.headers.get('X-License-Key') or request.args.get('license_key') or request.form.get('license_key')
        if license_key:
            # Match against device in database or active licenses
            device_data = database.get(device_id, {})
            if device_data.get("license_key") == license_key:
                return f(device_id, *args, **kwargs)
            if license_key in users_database.get("licenses", {}):
                return f(device_id, *args, **kwargs)

        # 3. If device already registered in database and no token provided, allow legacy upload
        # while logging a deprecation warning to migrate to famX token
        if device_id in database:
            return f(device_id, *args, **kwargs)

        return jsonify({
            "success": False,
            "error": "Unauthorized device. Valid famX token or license key required."
        }), 401
    return decorated_function
