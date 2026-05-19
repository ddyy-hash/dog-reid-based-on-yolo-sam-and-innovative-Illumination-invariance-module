import os
from datetime import timedelta


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dog-reid-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///dog_reid.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload settings.
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(BASE_DIR, 'uploads')
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'dav'}
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE', 100)) * 1024 * 1024

    # Runtime asset settings. Large model files are intentionally not tracked.
    MODEL_DIR = os.environ.get('MODEL_DIR') or os.path.join(BASE_DIR, 'fea_data')
    YOLO_MODEL_PATH = os.environ.get('YOLO_MODEL_PATH') or os.path.join(MODEL_DIR, 'yolov8m-seg.pt')
    SAM_CHECKPOINT_PATH = os.environ.get('SAM_CHECKPOINT_PATH') or os.path.join(MODEL_DIR, 'sam_vit_b_01ec64.pth')
    REID_MODEL_PATH = os.environ.get('REID_MODEL_PATH') or os.path.join(MODEL_DIR, 'illumination_robust_model.pth')
    DOG_FEATURES_PATH = os.environ.get('DOG_FEATURES_PATH') or os.path.join(MODEL_DIR, 'universal_features_h.npy')
    TEMP_FRAME_DIR = os.environ.get('TEMP_FRAME_DIR') or os.path.join(BASE_DIR, 'temp_frames')

    # Session settings.
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get('SESSION_HOURS', 2)))

    # Real-time detection settings.
    RTSP_TIMEOUT = int(os.environ.get('RTSP_TIMEOUT', 10))
    MAX_RETRY_ATTEMPTS = int(os.environ.get('MAX_RETRY_ATTEMPTS', 5))


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_ECHO = False

