import time
from flask import Blueprint, request, jsonify, redirect, url_for, session, render_template
from config import ADMIN_EMAIL
from core.database import users_database
from core.auth import check_password, ADMIN_PASSWORD_HASH

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'], endpoint='login_page')
def login_page():
    if request.method == 'POST':
        req_data = request.json or {}
        username = req_data.get('username')
        password = req_data.get('password')
        license_key = req_data.get('license_key')

        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and Password are required.'}), 400

        if username == ADMIN_EMAIL:
            if check_password(password, ADMIN_PASSWORD_HASH):
                session['username'] = username
                session['admin_logged'] = True
                return jsonify({'success': True, 'is_admin': True, 'redirect': '/admin'})
            else:
                return jsonify({'success': False, 'error': 'Invalid credentials.'}), 401

        if not license_key:
            return jsonify({'success': False, 'error': 'License Key is required.'}), 400

        user_info = users_database.get("users", {}).get(username)
        if not user_info:
            return jsonify({'success': False, 'error': 'Invalid credentials.'}), 401

        if not check_password(password, user_info.get("password_hash", "")):
            return jsonify({'success': False, 'error': 'Invalid credentials.'}), 401

        license_info = users_database.get("licenses", {}).get(license_key)
        if not license_info or license_info.get("assigned_to") != username:
            return jsonify({'success': False, 'error': 'License key invalid or not assigned to this user.'}), 401

        if not license_info.get("is_active", True):
            return jsonify({'success': False, 'error': 'License key is inactive.'}), 401

        current_ts = int(time.time())
        expires_at = license_info.get("expires_at", 0)
        if current_ts > expires_at:
            return jsonify({'success': False, 'error': 'License key expired. Please renew your key.'}), 401

        session['username'] = username
        session['license_key'] = license_key
        return jsonify({'success': True})
        
    if 'username' in session:
        if session.get('admin_logged', False):
            return redirect('/admin')
        return redirect('/dashboard')
    return render_template('login.html')

@auth_bp.route('/logout', endpoint='logout')
def logout():
    session.pop('username', None)
    session.pop('license_key', None)
    session.pop('admin_logged', None)
    if request.headers.get('Accept') == 'application/json' or request.is_json:
        return jsonify({'success': True})
    return redirect('/login')

@auth_bp.route('/check_auth', endpoint='check_auth')
def check_auth():
    authorized = 'username' in session
    return jsonify({'authorized': authorized})

@auth_bp.route('/admin/login', methods=['GET', 'POST'], endpoint='admin_login_page')
def admin_login_page():
    if request.method == 'POST':
        data = request.json or {}
        username = data.get('username')
        password = data.get('password')
        if username == ADMIN_EMAIL and check_password(password, ADMIN_PASSWORD_HASH):
            session['username'] = username
            session['admin_logged'] = True
            return jsonify({'success': True, 'redirect': '/admin'})
        return jsonify({'success': False, 'error': 'Invalid admin credentials.'}), 401
    return render_template('login.html')

@auth_bp.route('/admin/logout', endpoint='admin_logout')
def admin_logout():
    session.pop('username', None)
    session.pop('admin_logged', None)
    return jsonify({'success': True, 'redirect': '/login'})
