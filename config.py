import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.environ.get('SECRET_KEY', 'cybereye-secret')
DB_FILE = os.environ.get('DB_FILE', os.path.join(BASE_DIR, 'database.json'))
USERS_DB_FILE = os.environ.get('USERS_DB_FILE', os.path.join(BASE_DIR, 'users_db.json'))
BLACKLIST = ["info", "services", "default_device", "web", "🌐", "web"]

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', "AIzaSyBsHMZ1SrAaMXdXScPGbycCZokkD5B3tP0")

ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', "Admin@cybereye.co.in")
ADMIN_DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', "Cybereye@123")

# Server Ports & Host (Configurable)
WEB_PORT = int(os.environ.get('WEB_PORT', 8800))
DEVICE_PORT = int(os.environ.get('DEVICE_PORT', 5000))
HOST = os.environ.get('HOST', '0.0.0.0')

# Database & Redis Connection URLs
DATABASE_URL = os.environ.get('DATABASE_URL', '')
REDIS_URL = os.environ.get('REDIS_URL', '')



