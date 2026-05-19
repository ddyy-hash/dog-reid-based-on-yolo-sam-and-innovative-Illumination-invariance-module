import json
import os

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

from config import Config


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def create_app(config_class=Config):
    app = Flask(
        __name__,
        static_folder=os.path.join(BASEDIR, 'static'),
        static_url_path='/static',
        template_folder=os.path.join(BASEDIR, 'templates')
    )
    app.config.from_object(config_class)

    @app.template_filter('basename')
    def basename_filter(filepath):
        return os.path.basename(filepath)

    @app.template_filter('fromjson')
    def fromjson_filter(value):
        """Parse a JSON string for templates."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['TEMP_FRAME_DIR'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app.routes import auth_bp, main_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')

    return app

