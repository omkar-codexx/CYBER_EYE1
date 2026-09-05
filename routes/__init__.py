from .auth import auth_bp
from .views import views_bp
from .api import api_bp
from .admin import admin_bp

def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
