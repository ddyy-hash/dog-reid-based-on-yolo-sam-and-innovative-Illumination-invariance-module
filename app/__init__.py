import json
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请登录后访问此页面'

BASEDIR = os.path.abspath(os.path.dirname(__file__))
parent = os.path.dirname(BASEDIR)
def create_app(config_class=Config):
    app = Flask(
        __name__,
        static_folder=os.path.join(BASEDIR, 'static'),
        static_url_path='/static',
        template_folder=os.path.join(BASEDIR, 'templates')
    )
    app.config.from_object(config_class)

    # 注册自定义过滤器：从路径中提取文件名
    @app.template_filter('basename')
    def basename_filter(filepath):
        return os.path.basename(filepath)

    @app.template_filter('fromjson')
    def fromjson_filter(value):
        """将 JSON 字符串解析为 Python 对象"""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None  # 或返回空字典/列表

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('temp_frames', exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app.routes import main_bp, auth_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')

    return app

