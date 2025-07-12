import os
import sys
from collections import deque
from datetime import datetime
import json
import cv2
import time
import threading
import numpy as np

from app.core.realtime_detection_system import RealTimeDetectionSystem


#摄像头管理器类
class CameraManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.cameras = {}
            return cls._instance

    def get_camera(self, camera_id="default"):
        """获取指定ID的摄像头实例"""
        return self.cameras.get(camera_id)

    def create_camera(self, camera_id, reid_system):
        """创建并返回摄像头实例"""
        with self._lock:
            if camera_id in self.cameras:
                return self.cameras[camera_id]

            camera = LocalCamera(camera_id, reid_system)
            self.cameras[camera_id] = camera
            return camera


class LocalCamera:
    """本地摄像头封装类"""

    def __init__(self, camera_id, reid_system):
        self.camera_id = camera_id
        self.reid_system = reid_system
        self.frame_buffer = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.connection_status = {"connected": False, "error_message": ""}
        self.detection_results = {}
        self.detection_system = None
        self.frame_times = deque(maxlen=30)  # 用于计算帧率
        self.current_fps = 0
        self.detection_lock = threading.Lock()
        self.camera_stats = {
            "start_time": None,
            "frames_processed": 0,
            "detection_count": 0,
            "last_detection_time": None
        }

    def start(self):
        """启动摄像头线程"""
        global camera_running, connection_status  # 新增全局变量声明

        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )

        # 更新全局状态
        camera_running = True
        connection_status = {"connected": False, "error_message": "正在初始化..."}

        self.thread.start()

    def stop(self):
        """停止摄像头线程"""
        global camera_running, connection_status, frame_buffer  # 新增全局变量声明

        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None

        # 更新全局状态
        camera_running = False
        connection_status = {"connected": False, "error_message": "已停止"}
        frame_buffer = None

    def get_frame(self):
        """获取当前帧"""
        with self.lock:
            return self.frame_buffer

    def get_status(self):
        """获取连接状态"""
        return self.connection_status.copy()

    def get_stats(self):
        """获取摄像头统计信息"""
        if self.camera_stats["start_time"]:
            processing_time = (datetime.now() - self.camera_stats["start_time"]).total_seconds()
            return {
                **self.camera_stats,
                "processing_time": f"{processing_time:.1f}"
            }
        return {"frames_processed": 0, "detection_count": 0, "processing_time": "0.0"}

    def get_results(self):
        """获取检测结果"""
        with self.detection_lock:
            return self.detection_results.copy()

    def _run(self):
        """摄像头主运行逻辑"""
        global frame_buffer, connection_status, camera_running  # 新增全局变量声明

        # 初始化状态
        camera_running = True
        self.connection_status = {"connected": False, "error_message": "正在初始化本地摄像头..."}
        connection_status = self.connection_status.copy()  # 更新全局状态
        self.connection_status = {"connected": False, "error_message": "正在初始化本地摄像头..."}
        self.camera_stats["start_time"] = datetime.now()

        # 初始化检测系统
        if self.reid_system:
            self.detection_system = RealTimeDetectionSystem(self.reid_system, frame_skip=2, process_interval=1)

        cap = None
        retry_count = 0
        max_retries = 3

        # 确定摄像头索引列表
        camera_indices = []
        try:
            # 尝试将输入转换为整数索引
            camera_indices.append(int(self.camera_id))
        except ValueError:
            # 如果是字符串路径，直接使用
            camera_indices.append(self.camera_id)

        # 添加备用索引
        camera_indices.extend([0, 1, 2])  # 常见的摄像头索引

        # Linux系统添加设备路径
        if sys.platform.startswith('linux'):
            camera_indices.extend([f'/dev/video{i}' for i in range(4)])

        while self.running and retry_count < max_retries:
            try:
                # 尝试打开摄像头
                cap = None
                for idx in camera_indices:
                    print(f"尝试打开摄像头索引/路径: {idx}")

                    # 尝试不同的后端
                    backends = [
                        cv2.CAP_DSHOW if sys.platform.startswith('win32') else cv2.CAP_V4L2,
                        cv2.CAP_ANY
                    ]

                    for backend in backends:
                        cap = cv2.VideoCapture(idx, backend)
                        if cap.isOpened():
                            # 测试读取一帧
                            ret, test_frame = cap.read()
                            if ret and test_frame is not None:
                                # 设置关键参数
                                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                                cap.set(cv2.CAP_PROP_FPS, 30)
                                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                                print(f"成功打开摄像头: {idx} (后端: {backend})")
                                self.connection_status = {"connected": True, "error_message": ""}
                                break
                            else:
                                cap.release()
                                cap = None
                        else:
                            if cap:
                                cap.release()
                                cap = None

                    if cap and cap.isOpened():
                        break

                if cap is None or not cap.isOpened():
                    raise ConnectionError("无法打开任何摄像头设备")

                # 主处理循环
                frame_count = 0
                last_frame_time = time.time()
                while self.running:
                    start_time = time.time()
                    ret, frame = cap.read()
                    if not ret:
                        print("无法读取摄像头帧，尝试重新连接...")
                        raise IOError("摄像头读取失败")

                    frame_count += 1
                    self.camera_stats["frames_processed"] = frame_count

                    # 检测处理
                    try:
                        # 即使没有检测结果也要处理帧
                        current_results = self.detection_system.process_frame(frame)

                        if current_results:
                            with self.detection_lock:
                                self.detection_results = current_results
                                self.camera_stats["detection_count"] += 1
                                self.camera_stats["last_detection_time"] = datetime.now()

                        # 绘制检测结果（即使没有识别到狗）
                        display_text = "检测中..."
                        if current_results:
                            top_result = max(current_results.values(), key=lambda x: x['confidence'])
                            display_text = f"{top_result['name']} ({top_result['confidence']:.1f}%)"

                        cv2.putText(frame, display_text, (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    except Exception as e:
                        print(f"帧处理错误: {e}")

                    # 更新帧缓存
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    with self.lock:
                        self.frame_buffer = buffer.tobytes()
                        frame_buffer = self.frame_buffer  # 更新全局帧缓冲

                    # 更新连接状态
                    self.connection_status = {"connected": True, "error_message": ""}
                    connection_status = self.connection_status.copy()  # 更新全局状态

                    # 计算帧率
                    frame_time = time.time() - start_time
                    self.frame_times.append(frame_time)

                    if len(self.frame_times) > 10:
                        self.current_fps = round(1.0 / (sum(self.frame_times) / len(self.frame_times)))

                    # 控制帧率
                    elapsed = time.time() - start_time
                    sleep_time = max(0.001, 0.033 - elapsed)  # 保持约30fps
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"本地摄像头处理错误: {e}")
                self.connection_status = {"connected": False, "error_message": str(e)}
                connection_status = self.connection_status.copy()  # 更新全局状态
                retry_count += 1

                if cap:
                    cap.release()
                    cap = None

                if retry_count < max_retries and self.running:
                    print(f"等待2秒后重试... ({retry_count}/{max_retries})")
                    time.sleep(2)

        # 清理资源
        if cap:
            cap.release()
        self.running = False
        self.connection_status = {"connected": False, "error_message": "摄像头已停止"}
        print("本地摄像头处理已终止")

    def get_fps(self):
        return self.current_fps


# 为了兼容原有代码，保留全局变量和函数
frame_stream_active = False
frame_buffer = None
detection_results = {}
camera_running = False
detection_system = None
detection_lock = threading.Lock()
connection_status = {"connected": False, "error_message": ""}
camera_stats = {
    "start_time": None,
    "frames_processed": 0,
    "detection_count": 0,
    "last_detection_time": None
}

# 创建摄像头管理器实例
camera_manager = CameraManager()
active_camera = None

def start_frame_stream_detection():
    """标记帧流模式已启动"""
    global frame_stream_active
    frame_stream_active = True

def stop_frame_stream_mode():
    """标记帧流模式已停止"""
    global frame_stream_active
    frame_stream_active = False

# 修改 get_connection_status 函数
def get_connection_status():
    """返回连接状态"""
    global frame_stream_active, connection_status
    if frame_stream_active:
        return {"connected": True, "error_message": "帧流模式已连接"}
    return connection_status.copy()

def get_camera_fps():
    """获取摄像头帧率"""
    global active_camera
    if active_camera:
        return active_camera.get_fps()
    return 0

def set_detection_results(results):
    """设置全局检测结果 - 用于帧流模式"""
    global detection_results
    with detection_lock:
        detection_results = results


def get_camera_stats():
    """获取摄像头统计信息"""
    global camera_stats
    if camera_stats["start_time"]:
        processing_time = (datetime.now() - camera_stats["start_time"]).total_seconds()
        return {
            **camera_stats,
            "processing_time": f"{processing_time:.1f}"
        }
    return {"frames_processed": 0, "detection_count": 0, "processing_time": "0.0"}


def get_camera_stream():
    """返回全局视频帧数据"""
    global frame_buffer
    return frame_buffer


def get_detection_results():
    """返回当前检测结果"""
    global detection_results, detection_lock
    with detection_lock:
        return detection_results.copy()


def get_connection_status():
    """返回连接状态"""
    global connection_status
    return connection_status.copy()


def is_camera_running():
    """返回摄像头运行状态"""
    global camera_running
    return camera_running


def start_camera_feed(rtsp_url, reid_system=None):
    """
    启动摄像头视频流处理线程

    参数:
        rtsp_url (str): RTSP摄像头URL
        reid_system: 狗识别系统实例，如果为None则只捕获视频流不进行识别

    返回:
        threading.Thread: 启动的线程对象
    """
    global camera_running

    if camera_running:
        return None

    # 创建并启动新线程
    camera_thread = threading.Thread(
        target=_gen_camera_feed,
        args=(rtsp_url, reid_system),
        daemon=True
    )
    camera_thread.start()
    return camera_thread


def start_local_camera_feed(camera_id, reid_system):
    global camera_running, active_camera, frame_buffer, connection_status, camera_stats

    # 确保没有其他摄像头在运行
    if camera_running:
        stop_camera_feed()

    # 创建并启动摄像头实例
    camera = camera_manager.create_camera(camera_id, reid_system)
    camera.start()
    active_camera = camera

    # 更新全局状态以兼容旧代码
    camera_running = True
    connection_status = camera.get_status()
    camera_stats = camera.get_stats()

    return camera


def stop_camera_feed():
    """停止摄像头视频流处理"""
    global camera_running, connection_status, frame_buffer, detection_results, active_camera

    if active_camera:
        active_camera.stop()
        active_camera = None

    camera_running = False
    connection_status = {"connected": False, "error_message": "检测已停止"}
    frame_buffer = None
    detection_results = {}

    # 强制释放OpenCV资源
    cv2.destroyAllWindows()

    # 等待线程退出
    time.sleep(0.5)

    print("摄像头资源已强制释放")


#RTSP处理函数
def _gen_camera_feed(rtsp_url, reid_system=None):
    """
    处理摄像头视频流的内部函数（含自动重连机制）

    参数:
        rtsp_url (str): RTSP摄像头URL
        reid_system: 狗识别系统实例
    """
    global frame_buffer, detection_results, camera_running, connection_status

    # 初始化参数
    camera_running = True
    MAX_RETRIES = 3  # 最大重连次数
    RETRY_INTERVAL = 2  # 重连间隔(秒)
    FRAME_TIMEOUT = 5  # 帧读取超时时间(秒)
    resolution = (1280, 720)  # 控制处理分辨率

    global detection_system
    detection_system = RealTimeDetectionSystem(reid_system, frame_skip=1, process_interval=1)
    cap = None
    retry_count = 0

    while camera_running:
        try:
            # 阶段1：摄像头初始化
            if cap is None or not cap.isOpened():
                print(f"尝试连接摄像头 (第{retry_count + 1}次)...")
                connection_status = {"connected": False, "error_message": f"正在连接... (第{retry_count + 1}次)"}

                cap = cv2.VideoCapture(rtsp_url)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)  # 3秒连接超时

                if not cap.isOpened():
                    raise ConnectionError("摄像头连接失败")

                # 设置缓存区大小（减少延迟）
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                retry_count = 0  # 重置重试计数器
                connection_status = {"connected": True, "error_message": ""}
                print("摄像头连接成功")

            # 阶段2：帧读取与处理
            start_read_time = time.time()
            ret, frame = cap.read()

            # 超时检测
            if (time.time() - start_read_time) > FRAME_TIMEOUT:
                raise TimeoutError("帧读取超时")

            if not ret:
                print("收到空帧，尝试重置连接...")
                raise IOError("无效帧数据")

            # 分辨率调整（降低处理负担）
            frame = cv2.resize(frame, resolution)

            # 阶段3：实时检测处理
            if reid_system is not None:
                current_results = detection_system.process_frame(frame)

                # 更新检测结果
                if current_results:
                    with detection_lock:
                        detection_results = current_results

                    # 绘制实时结果
                    top_result = max(current_results.values(), key=lambda x: x['confidence'])
                    cv2.putText(
                        frame,
                        f"{top_result['name']} ({top_result['confidence']:.1f}%)",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
                    )

            # 阶段4：更新帧缓存
            _, buffer = cv2.imencode('.jpg', frame)
            frame_buffer = buffer.tobytes()

            # 控制帧率
            time.sleep(0.03)  # 约33fps

        except (TimeoutError, IOError, ConnectionError) as e:
            print(f"视频流异常: {str(e)}")
            connection_status = {"connected": False, "error_message": str(e)}
            if cap and cap.isOpened():
                cap.release()
            cap = None
            retry_count += 1

            # 超过最大重试次数则退出
            if retry_count >= MAX_RETRIES:
                print(f"达到最大重试次数({MAX_RETRIES})，停止视频流")
                connection_status = {"connected": False, "error_message": f"连接失败，已重试{MAX_RETRIES}次"}
                break

            # 指数退避重连
            sleep_time = RETRY_INTERVAL * (2 ** (retry_count - 1))
            print(f"{sleep_time}秒后尝试重连...")
            time.sleep(sleep_time)

        except Exception as e:
            print(f"未处理的异常: {str(e)}")
            connection_status = {"connected": False, "error_message": f"系统错误: {str(e)}"}
            break

    # 资源清理
    if cap and cap.isOpened():
        cap.release()
    camera_running = False
    connection_status = {"connected": False, "error_message": "视频流已停止"}
    print("视频流处理已终止")


def clear_detection_cache():
    """清理检测缓存"""
    global detection_results, frame_buffer

    # 清空全局变量
    detection_results = {}
    frame_buffer = None
    detection_history = []

    # 清理临时文件
    temp_dir = 'temp_frames'
    if os.path.exists(temp_dir):
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                os.unlink(file_path)