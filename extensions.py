from flask_socketio import SocketIO
from config import REDIS_URL

# Web Dashboard SocketIO (Port 8800)
# Configure with Redis message queue for high scalability if available
_socketio_kwargs = {"cors_allowed_origins": "*", "async_mode": "threading", "allow_eio3": True}
_gateway_kwargs = {"cors_allowed_origins": "*", "async_mode": "threading", "allow_eio3": True}

if REDIS_URL:
    try:
        socketio = SocketIO(message_queue=REDIS_URL, channel='socketio_web', **_socketio_kwargs)
        gateway_socketio = SocketIO(message_queue=REDIS_URL, channel='socketio_gateway', **_gateway_kwargs)
        print("[SocketIO] Configured with Redis message queue broker.")
    except Exception as e:
        print(f"[SocketIO] Redis queue initialization failed ({e}), using default in-memory manager.")
        socketio = SocketIO(**_socketio_kwargs)
        gateway_socketio = SocketIO(**_gateway_kwargs)
else:
    socketio = SocketIO(**_socketio_kwargs)
    gateway_socketio = SocketIO(**_gateway_kwargs)

def emit_device_command(device_id, command_data, sid=None):
    """Safely dispatches a command to a device connected to either port."""
    if sid:
        gateway_socketio.emit('command', command_data, room=sid)
        socketio.emit('command', command_data, room=sid)
    # Also emit to device room as fallback
    gateway_socketio.emit('command', command_data, room=device_id)
    socketio.emit('command', command_data, room=device_id)

