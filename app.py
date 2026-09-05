import os
import sys
import threading
from flask import Flask
from config import SECRET_KEY, WEB_PORT, DEVICE_PORT, HOST
from extensions import socketio
from core.auth import check_maintenance_policy
from routes import register_blueprints
from sockets import register_socket_events
from services.telegram_notifier import start_ip_port_monitor
from gateway import run_gateway

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = SECRET_KEY

    # Maintenance policy middleware
    app.before_request(check_maintenance_policy)

    # Initialize extensions
    socketio.init_app(app)

    # Register blueprints
    register_blueprints(app)

    # Register real-time SocketIO event handlers
    register_socket_events(socketio)

    return app

app = create_app()

# Start background IP and port monitoring daemon
start_ip_port_monitor()

def start_servers():
    web_port = int(os.environ.get('WEB_PORT', WEB_PORT))
    device_port = int(os.environ.get('DEVICE_PORT', DEVICE_PORT))
    host = os.environ.get('HOST', HOST)
    
    web_only = os.environ.get('WEB_ONLY', '0') == '1'
    gateway_only = os.environ.get('GATEWAY_ONLY', '0') == '1'

    print("=" * 65)
    print(" Proton Telemetry Platform (famX Dual-Port Architecture)")
    print("=" * 65)
    print(f" [Web Dashboard]  http://{host}:{web_port} (Admin & User UI)")
    print(f" [famX Gateway]   http://{host}:{device_port} (Hardware Ingestion)")
    print("=" * 65)

    if gateway_only:
        run_gateway(host=host, port=device_port)
        return

    if not web_only:
        # Start famX Device Gateway in dedicated background daemon thread
        gateway_thread = threading.Thread(
            target=run_gateway,
            kwargs={'host': host, 'port': device_port},
            daemon=True
        )
        gateway_thread.start()

    # Start Web Dashboard Server on primary thread
    socketio.run(app, host=host, port=web_port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    start_servers()
