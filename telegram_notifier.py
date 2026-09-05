import os
import re
import time
import logging
import threading
from datetime import datetime
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telegram_notifier")

# IP Check Endpoints with Fallbacks
IP_CHECK_SERVICES = [
    "https://api.ipify.org?format=text",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com"
]

IPV4_REGEX = re.compile(r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$')


def get_forwarded_port(file_paths=None):
    """
    Reads the forwarded port from Gluetun's status file.
    Checks common paths inside and outside docker.
    """
    if file_paths is None:
        custom_path = os.environ.get("FORWARDED_PORT_FILE")
        file_paths = [
            custom_path,
            "/gluetun/forwarded_port",
            "./gluetun/forwarded_port",
            os.path.join(os.path.dirname(__file__), "gluetun", "forwarded_port")
        ]

    for path in file_paths:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content.isdigit():
                    port_num = int(content)
                    if 1 <= port_num <= 65535:
                        return str(port_num)
            except Exception as e:
                logger.warning(f"Error reading port from {path}: {e}")
    return None


def get_public_ip():
    """
    Fetches external public IP through the current network interface (VPN tunnel)
    using multiple reliable fallback endpoints.
    """
    for url in IP_CHECK_SERVICES:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if IPV4_REGEX.match(ip):
                    return ip
        except Exception:
            continue
    return None


def send_telegram_message(bot_token, chat_id, text, parse_mode="HTML"):
    """
    Sends a message to the specified Telegram chat using the Telegram Bot API.
    """
    if not bot_token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not configured. Skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram notification delivered successfully.")
            return True
        else:
            logger.error(f"Telegram API responded with error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def build_notification_message(current_ip, current_port, event_type="update", old_ip=None, old_port=None):
    """
    Constructs a formatted HTML message for Telegram.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if event_type == "startup":
        header = "🚀 <b>CyberEye Connection Online</b>"
        change_info = "⚡ Initial connection established."
    elif event_type == "change":
        header = "⚠️ <b>CyberEye Connection Changed</b>"
        changes = []
        if old_ip and old_ip != current_ip:
            changes.append(f"🌐 IP: <code>{old_ip}</code> ➔ <code>{current_ip}</code>")
        if old_port and old_port != current_port:
            changes.append(f"🔌 Port: <code>{old_port}</code> ➔ <code>{current_port}</code>")
        change_info = "\n".join(changes) if changes else "🔄 Connection parameters updated."
    else:
        header = "📡 <b>CyberEye Connection Status</b>"
        change_info = ""

    msg_lines = [
        header,
        "",
        f"🌐 <b>Public IP:</b> <code>{current_ip or 'Detecting...'}</code>",
        f"🔌 <b>Forwarded Port:</b> <code>{current_port or 'Waiting...'}</code>",
    ]

    if current_ip and current_port:
        msg_lines.append(f"🔗 <b>Endpoint:</b> <code>SERVER:http://{current_ip}:{current_port}</code>")

    if change_info:
        msg_lines.extend(["", change_info])

    msg_lines.extend(["", f"🕒 <b>Timestamp:</b> <code>{now}</code>"])

    return "\n".join(msg_lines)


class IPPortMonitor:
    def __init__(self, check_interval=30):
        self.check_interval = check_interval
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.last_ip = None
        self.last_port = None
        self.initial_notified = False
        self.is_running = False
        self._thread = None

    def get_status(self):
        return {
            "ip": self.last_ip,
            "port": self.last_port,
            "telegram_configured": bool(self.bot_token and self.chat_id),
            "check_interval": self.check_interval,
            "initial_notified": self.initial_notified
        }

    def check_once(self):
        # Refresh credentials in case env vars were updated
        if not self.bot_token:
            self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not self.chat_id:
            self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

        current_ip = get_public_ip()
        current_port = get_forwarded_port()

        # If we couldn't resolve either yet (VPN still negotiating), wait for next cycle
        if not current_ip and not current_port:
            logger.debug("Both IP and Port unavailable, waiting for VPN tunnel...")
            return

        ip_changed = (current_ip is not None and current_ip != self.last_ip)
        port_changed = (current_port is not None and current_port != self.last_port)

        if not self.initial_notified:
            # First time both or either became available
            if current_ip or current_port:
                logger.info(f"Initial IP/Port detected: IP={current_ip}, Port={current_port}")
                if self.bot_token and self.chat_id:
                    msg = build_notification_message(
                        current_ip=current_ip,
                        current_port=current_port,
                        event_type="startup"
                    )
                    send_telegram_message(self.bot_token, self.chat_id, msg)
                self.initial_notified = True
                self.last_ip = current_ip
                self.last_port = current_port
        elif ip_changed or port_changed:
            logger.info(f"Connection change detected! IP: {self.last_ip} -> {current_ip}, Port: {self.last_port} -> {current_port}")
            if self.bot_token and self.chat_id:
                msg = build_notification_message(
                    current_ip=current_ip,
                    current_port=current_port,
                    event_type="change",
                    old_ip=self.last_ip,
                    old_port=self.last_port
                )
                send_telegram_message(self.bot_token, self.chat_id, msg)
            if current_ip:
                self.last_ip = current_ip
            if current_port:
                self.last_port = current_port

    def run_loop(self):
        logger.info(f"IP/Port monitor started. Polling every {self.check_interval}s.")
        while self.is_running:
            try:
                self.check_once()
            except Exception as e:
                logger.error(f"Unexpected error in IP/Port monitor: {e}")
            time.sleep(self.check_interval)

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self.run_loop, name="IPPortMonitorThread", daemon=True)
        self._thread.start()


_monitor_instance = None
_monitor_lock = threading.Lock()


def start_ip_port_monitor(interval=None):
    """
    Initializes and starts the singleton IP/Port background monitor.
    """
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            if interval is None:
                try:
                    interval = int(os.environ.get("IP_PORT_CHECK_INTERVAL", 30))
                except ValueError:
                    interval = 30
            _monitor_instance = IPPortMonitor(check_interval=interval)
            _monitor_instance.start()
    return _monitor_instance


def get_current_connection_status():
    """
    Returns current connection info from the monitor instance if active.
    """
    global _monitor_instance
    if _monitor_instance:
        return _monitor_instance.get_status()
    return {
        "ip": None,
        "port": get_forwarded_port(),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    }

