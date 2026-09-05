from flask_socketio import SocketIO

# Web Dashboard SocketIO (Port 8800)
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading', allow_eio3=True)

# famX Device Gateway SocketIO (Port 5000)
gateway_socketio = SocketIO(cors_allowed_origins="*", async_mode='threading', allow_eio3=True)

def emit_device_command(device_id, command_data, sid=None):
    """Safely dispatches a command to a device connected to either port."""
    if sid:
        gateway_socketio.emit('command', command_data, room=sid)
        socketio.emit('command', command_data, room=sid)
    # Also emit to device room as fallback
    gateway_socketio.emit('command', command_data, room=device_id)
    socketio.emit('command', command_data, room=device_id)

