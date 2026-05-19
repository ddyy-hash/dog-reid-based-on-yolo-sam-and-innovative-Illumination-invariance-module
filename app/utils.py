import os
import json
import uuid
from flask import current_app
from werkzeug.utils import secure_filename
from app.core.dog_reid_system import DogReIDSystem

# 全局变量存储模型实例
dog_reid_system = None


def get_dog_reid_system():
    global dog_reid_system
    if dog_reid_system is None:
        dog_reid_system = DogReIDSystem()
    return dog_reid_system


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def save_uploaded_file(file):
    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        stored_filename = f"{uuid.uuid4().hex}_{original_filename}"

        # 统一路径分隔符为 '/'
        upload_path = os.path.join(
            current_app.config['UPLOAD_FOLDER'],
            stored_filename
        ).replace('\\', '/')  # 替换反斜杠为正斜杠

        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        file.save(upload_path)

        return {
            'original_filename': original_filename,
            'stored_filename': stored_filename,
            'filepath': upload_path  # 保存统一后的路径
        }
    return None


def process_video(filepath, temp_dir=None):
    """处理视频并返回识别结果，同时更新处理统计"""
    import time
    from app.models import ProcessingProgress, Video
    from app import db

    temp_dir = temp_dir or current_app.config['TEMP_FRAME_DIR']
    start_time = time.time()

    # 获取视频ID（从filepath推导或传参）
    video = Video.query.filter_by(filepath=filepath).first()
    if not video:
        return {}

    # 获取或创建进度记录
    progress = ProcessingProgress.query.filter_by(video_id=video.id).first()
    if not progress:
        progress = ProcessingProgress(
            video_id=video.id,
            stage=1,
            status_message='开始处理视频...'
        )
        db.session.add(progress)
        db.session.commit()

    # 获取或创建模型
    reid_system = get_dog_reid_system()

    try:
        # 清理临时目录
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.unlink(file_path)

        # 更新阶段：视频分析
        progress.stage = 2
        progress.status_message = '正在分析视频帧...'
        db.session.commit()

        # 处理视频并提取特征
        frame_count = reid_system.process_video_and_save_frames(filepath, temp_dir)

        # 更新已处理帧数
        progress.frames_processed = frame_count
        progress.stage = 3
        progress.status_message = '正在提取特征...'
        db.session.commit()

        features = reid_system.extract_features(temp_dir, frame_count)

        # 更新阶段：AI识别
        progress.stage = 4
        progress.status_message = '正在进行AI识别...'
        db.session.commit()

        # 识别狗
        results = reid_system.identify_dogs(features)

        # 计算检测次数（非零置信度结果的数量）
        detection_count = len([r for r in results.values() if r > 0]) if results else 0

        # 计算处理时间
        processing_time = time.time() - start_time

        # 更新最终统计信息
        progress.detection_count = detection_count
        progress.processing_time = processing_time
        progress.progress = 99  # 设置为99%，等待完成
        progress.status_message = '识别完成，正在保存结果...'
        db.session.commit()

        # 清理临时文件
        reid_system.cleanup_temp_frames(temp_dir)

        # 格式化结果
        dog_names = {0: "豆豆", 1: "皮特", 2: "大乖", 3: "多比"}
        formatted_results = {}

        if results:
            for dog_id, confidence in results.items():
                dog_name = dog_names.get(int(dog_id), f"未知狗 {dog_id}")
                formatted_results[str(dog_id)] = {
                    'name': dog_name,
                    'confidence': confidence
                }

        return formatted_results

    except Exception as e:
        progress.status_message = f'处理失败: {str(e)}'
        db.session.commit()
        raise e

