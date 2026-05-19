import os
import json
import time
from datetime import datetime

import cv2
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, jsonify, send_from_directory, current_app
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse as url_parse
from app import db
from app.models import User, Video, ProcessingProgress
from app.forms import LoginForm, RegistrationForm, UploadVideoForm
from app.utils import save_uploaded_file, process_video
import threading
from app.core.camera_system import camera_manager

BASEDIR = os.path.abspath(os.path.dirname(__file__))
parent = os.path.dirname(BASEDIR)
# 创建蓝图
# routes.py
main_bp = Blueprint('main', __name__, template_folder=os.path.join(BASEDIR, 'templates'), static_folder=os.path.join(BASEDIR, 'static'))
auth_bp = Blueprint('auth', __name__, template_folder=os.path.join(BASEDIR, 'templates'), static_folder=os.path.join(BASEDIR, 'static'))


# 认证路由
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('用户名或密码错误')
            return redirect(url_for('auth.login'))

        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)

    return render_template('login.html', title='登录', form=form)


@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User()   #email=form.email.data
        user.username = form.username.data
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('恭喜，注册成功！请登录。')
        return redirect(url_for('auth.login'))

    return render_template('register.html', title='注册', form=form)


# 主要功能路由
@main_bp.route('/')
def index():
    return render_template('index.html', title='狗步态识别系统')


@main_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = UploadVideoForm()
    if form.validate_on_submit():
        file_info = save_uploaded_file(form.video.data)

        if file_info:
            # 保存视频信息到数据库
            video = Video(
                filename=file_info['original_filename'],
                filepath=file_info['filepath'],
                user_id=current_user.id
            )
            db.session.add(video)
            db.session.commit()

            # 将视频ID保存在会话中，用于处理页面
            session['processing_video_id'] = video.id

            return redirect(url_for('main.processing'))

        flash('上传失败，请确保文件类型正确')

    return render_template('upload.html', title='上传视频', form=form)


'''def background_process_video(app, video_id):
    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            app.logger.error(f"视频 {video_id} 不存在")
            return

        try:
            results = process_video(video.filepath)

            if not results or len(results) == 0:
                results = {}  # 未识别到狗的情况
                app.logger.info(f"视频 {video_id} 未识别到狗")

            video.processed = True
            video.result_data = json.dumps(results, ensure_ascii=False)
            db.session.commit()
            app.logger.info(f"视频 {video_id} 处理完成，结果已保存")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"处理失败: {str(e)}")
            video.processed = False
            db.session.commit()

'''
# routes.py
@main_bp.route('/processing')
@login_required
def processing():
    video_id = session.get('processing_video_id')
    video = Video.query.get(video_id)

    if not video.processed:
        # 关键修改：通过 current_app 获取代理对象，再调用 _get_current_object()
        app_instance = current_app._get_current_object()  # 正确获取真实应用实例
        thread = threading.Thread(
            target=background_process_video,
            args=(app_instance, video_id),  # 传递真实应用实例到线程
            daemon=True
        )
        thread.start()

    return render_template('processing.html', title='处理中', video=video)


@main_bp.route('/check_progress/<int:video_id>')
@login_required
def check_progress(video_id):
    video = Video.query.get(video_id)
    if not video or video.user_id != current_user.id:
        return jsonify({'error': '无效的视频ID'}), 404

    # 获取最新进度信息
    progress = ProcessingProgress.query.filter_by(video_id=video_id).order_by(
        ProcessingProgress.updated_at.desc()).first()

    if video.processed:
        # 处理完成，返回100%进度
        results = json.loads(video.result_data) if video.result_data else {}
        formatted_results = {}

        for dog_id, data in results.items():
            formatted_results[dog_id] = {
                'name': data.get('name', f'未知狗 {dog_id}'),
                'confidence': data.get('confidence', 0)
            }

        return jsonify({
            'processed': True,
            'results': formatted_results,
            'progress': 100,
            'status': '处理完成',
            'stage': 4,
            'frames_processed': progress.frames_processed if progress else 0,
            'detection_count': progress.detection_count if progress else 0,
            'processing_time': progress.processing_time if progress else 0
        })
    else:
        # 模拟进度：每次通讯增长5%，最高到99%
        current_progress = progress.progress if progress else 0
        simulated_progress = min(current_progress + 2, 99)

        # 更新进度到数据库
        if not progress:
            progress = ProcessingProgress(
                video_id=video_id,
                progress=simulated_progress,
                status_message='正在分析视频...',
                stage=1
            )
            db.session.add(progress)
        else:
            progress.progress = simulated_progress
            progress.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'processed': False,
            'progress': simulated_progress,
            'status': progress.status_message if progress else '正在分析视频...',
            'stage': progress.stage if progress else 1,
            'frames_processed': progress.frames_processed if progress else 0,
            'detection_count': progress.detection_count if progress else 0,
            'processing_time': progress.processing_time if progress else 0
        })


@main_bp.route('/results/<int:video_id>')
@login_required
def results(video_id):
    video = Video.query.get(video_id)
    if not video or video.user_id != current_user.id:
        flash('无效的视频ID')
        return redirect(url_for('main.upload'))

    if not video.processed:
        return redirect(url_for('main.processing'))

    results = json.loads(video.result_data) if video.result_data else {}

    return render_template('results.html', title='识别结果', video=video, results=results)


@main_bp.route('/uploads/<filename>')
def uploaded_video(filename):
    # 确保上传目录路径正确
    upload_folder = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_folder, filename)


@main_bp.route('/realtime_detection')
@login_required
def realtime_detection():
    return render_template('realtime.html', title='实时检测')


@main_bp.route('/get_realtime_results')
@login_required
def get_realtime_results():
    from app.core.camera_system import get_detection_results
    results = get_detection_results()

    # 格式化结果
    formatted = {}
    for dog_id, data in results.items():
        formatted[dog_id] = {
            'name': data['name'],
            'confidence': data['confidence']
        }
    return jsonify({'results': formatted})

@main_bp.route('/get_realtime_stats')
@login_required
def get_realtime_stats():
    """获取实时检测统计数据"""
    from app.core.camera_system import get_camera_stats, get_camera_fps
    stats = get_camera_stats()
    stats['fps'] = get_camera_fps()  # 添加帧率信息
    return jsonify(stats)


@main_bp.route('/start_realtime', methods=['POST'])
@login_required
def start_realtime():
    try:
        rtsp_url = request.form.get('rtsp_url') or request.json.get('rtsp_url')
        if not rtsp_url:
            return jsonify({'error': 'RTSP地址不能为空'}), 400

        from app.core.camera_system import start_camera_feed
        from app.core.dog_reid_system import DogReIDSystem

        reid_system = DogReIDSystem()
        thread = start_camera_feed(rtsp_url, reid_system)

        if thread:
            return jsonify({
                'status': 'started',
                'message': '实时检测已启动',
                'timestamp': time.time()
            })
        else:
            return jsonify({'error': '启动失败，摄像头可能已在运行'}), 409

    except Exception as e:
        current_app.logger.error(f"启动实时检测失败: {str(e)}")
        return jsonify({'error': f'启动失败: {str(e)}'}), 500


@main_bp.route('/stop_realtime', methods=['POST'])
@login_required
def stop_realtime():
    try:
        from app.core.camera_system import stop_camera_feed, detection_system, clear_detection_cache

        # 停止摄像头并清理资源
        stop_camera_feed()

        # 重置检测系统并清空缓存
        if detection_system:
            detection_system.reset()

        # 清空检测结果缓存
        clear_detection_cache()

        # 强制垃圾回收释放内存
        import gc
        gc.collect()

        return jsonify({
            'status': 'stopped',
            'message': '实时检测已停止，缓存已清理',
            'timestamp': time.time(),
            'cache_cleared': True
        })
    except Exception as e:
        current_app.logger.error(f"停止实时检测失败: {str(e)}")
        return jsonify({'error': f'停止失败: {str(e)}'}), 500


@main_bp.route('/camera_status')
@login_required
def camera_status():
    """获取摄像头连接状态 - 统一版本"""
    try:
        from app.core.camera_system import frame_stream_active, get_connection_status, is_camera_running

        # 如果是帧流模式，返回特定状态
        if frame_stream_active:
            return jsonify({
                'connected': True,
                'is_running': True,
                'mode': 'frame_stream',
                'error_message': '',
                'timestamp': time.time()
            })

        status = get_connection_status()
        status.update({
            'is_running': is_camera_running(),
            'timestamp': time.time(),
            'system_ready': True
        })

        return jsonify(status)
    except Exception as e:
        return jsonify({
            'connected': False,
            'is_running': False,
            'error_message': f'状态检查失败: {str(e)}',
            'system_ready': False,
            'timestamp': time.time()
        })

# 添加视频流路由
@main_bp.route('/camera_stream')
@login_required
def camera_stream():
    """提供视频流"""
    from app.core.camera_system import get_camera_stream
    from flask import Response

    def generate():
        while True:
            frame = get_camera_stream()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.03)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@main_bp.route('/start_local_detection', methods=['POST'])
@login_required
def start_local_detection():
    try:
        data = request.get_json()
        camera_id = data.get('camera_id')

        if not camera_id:
            return jsonify({'error': '摄像头ID不能为空'}), 400

        from app.core.dog_reid_system import DogReIDSystem
        from app.core.camera_system import start_local_camera_feed

        # 确保正确创建reid_system实例
        reid_system = DogReIDSystem()

        # 启动摄像头
        camera = start_local_camera_feed(camera_id, reid_system)

        if camera:
            return jsonify({
                'status': 'started',
                'message': '本地摄像头检测已启动',
                'timestamp': time.time()
            })
        else:
            return jsonify({'error': '启动失败，摄像头可能已在使用'}), 409

    except Exception as e:
        current_app.logger.error(f"启动本地检测失败: {str(e)}")
        return jsonify({'error': f'启动失败: {str(e)}'}), 500


@main_bp.route('/process_frame', methods=['POST'])
@login_required
def process_frame():
    """处理前端发送的视频帧 - 优化版本"""
    try:
        data = request.get_json()
        frame_data = data.get('frame_data')

        if not frame_data:
            return jsonify({'error': '缺少帧数据'}), 400

        # 解码base64图像数据
        import base64
        import numpy as np

        # 检查数据格式
        if not frame_data.startswith('data:image/jpeg;base64,'):
            return jsonify({'error': '无效的图片格式'}), 400

        try:
            header, encoded = frame_data.split(',', 1)
            frame_bytes = base64.b64decode(encoded)
        except Exception as e:
            return jsonify({'error': f'图片解码失败: {str(e)}'}), 400

        # 转换为OpenCV格式
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({'error': '图片解码失败'}), 400

        # 使用现有的检测系统处理
        if not hasattr(current_app, 'frame_detection_system'):
            from app.core.dog_reid_system import DogReIDSystem
            from app.core.realtime_detection_system import RealTimeDetectionSystem

            reid_system = DogReIDSystem()
            current_app.frame_detection_system = RealTimeDetectionSystem(
                reid_system,
                frame_skip=1,
                process_interval=1
            )

        # 处理帧并返回结果
        results = current_app.frame_detection_system.process_external_frame(frame)

        # 更新全局检测结果
        from app.core.camera_system import set_detection_results
        formatted_results = {}
        if results:
            for dog_id, data in results.items():
                formatted_results[dog_id] = {
                    'name': data.get('name', f'未知狗 {dog_id}'),
                    'confidence': data.get('confidence', 0)
                }
            set_detection_results(formatted_results)

        return jsonify({
            'success': True,
            'timestamp': time.time(),
            'processed': bool(results)
        })

    except Exception as e:
        current_app.logger.error(f"帧处理失败: {str(e)}")
        return jsonify({'error': f'处理失败: {str(e)}'}), 500

@main_bp.route('/stop_local_detection', methods=['POST'])
@login_required
def stop_local_detection():
    try:
        from app.core.camera_system import stop_camera_feed, detection_system
        stop_camera_feed()
        if detection_system:
            detection_system.reset()
        return jsonify({
            'status': 'stopped',
            'message': '本地摄像头检测已停止',
            'timestamp': time.time()
        })
    except Exception as e:
        current_app.logger.error(f"停止本地检测失败: {str(e)}")
        return jsonify({'error': f'停止失败: {str(e)}'}), 500

#处理本地摄像头
@main_bp.route('/local_camera_stream')
@login_required
def local_camera_stream():
    """提供本地摄像头视频流"""
    from app.core.camera_system import get_camera_stream
    from flask import Response

    def generate():
        while True:
            frame = get_camera_stream()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.033)  # 约30fps

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@main_bp.route('/detection_history')
@login_required
def detection_history():
    """获取检测历史记录"""
    # 这里可以从数据库获取历史记录
    # 暂时返回空数组，可根据需要扩展
    return jsonify({'history': []})


@main_bp.route('/system_performance')
@login_required
def system_performance():
    """系统性能监控"""
    import psutil
    import torch

    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()

    performance_data = {
        'cpu_usage': cpu_percent,
        'memory_usage': memory.percent,
        'memory_available': f"{memory.available / (1024 ** 3):.1f} GB"
    }

    # GPU信息（如果可用）
    if torch.cuda.is_available():
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        gpu_allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
        performance_data.update({
            'gpu_available': True,
            'gpu_memory_total': f"{gpu_memory:.1f} GB",
            'gpu_memory_used': f"{gpu_allocated:.1f} GB"
        })
    else:
        performance_data['gpu_available'] = False

    return jsonify(performance_data)


@main_bp.route('/export_results/<int:video_id>')
@login_required
def export_results(video_id):
    """导出识别结果"""
    video = Video.query.get(video_id)
    if not video or video.user_id != current_user.id:
        return jsonify({'error': '无效的视频ID'}), 404

    if not video.processed or not video.result_data:
        return jsonify({'error': '视频尚未处理完成'}), 400

    # 生成导出文件
    import json
    from flask import make_response

    results = json.loads(video.result_data)
    export_data = {
        'video_filename': video.filename,
        'upload_date': video.upload_date.isoformat(),
        'results': results,
        'export_time': datetime.now().isoformat()
    }

    response = make_response(json.dumps(export_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=results_{video_id}.json'

    return response



def background_process_video(app, video_id):
    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            app.logger.error(f"视频 {video_id} 不存在")
            return

        try:
            results = process_video(video.filepath)

            if not results or len(results) == 0:
                results = {}
                app.logger.info(f"视频 {video_id} 未识别到狗")

            video.processed = True
            video.result_data = json.dumps(results, ensure_ascii=False)
            db.session.commit()

            # 清理上传文件以节省空间
            cleanup_upload_file(video.filepath)
            app.logger.info(f"视频 {video_id} 处理完成，文件已清理")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"处理失败: {str(e)}")
            video.processed = False
            db.session.commit()


def cleanup_upload_file(filepath):
    """清理上传的视频文件"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            current_app.logger.info(f"已清理文件: {filepath}")
    except Exception as e:
        current_app.logger.error(f"清理文件失败: {e}")
