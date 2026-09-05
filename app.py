import os
from flask import Flask
from config import SECRET_KEY
from extensions import socketio
from core.auth import check_maintenance_policy
from routes import register_blueprints
from sockets import register_socket_events
from services.telegram_notifier import start_ip_port_monitor

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
