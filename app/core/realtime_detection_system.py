import cv2
import numpy as np
import torch
import threading
import time
import queue
from collections import deque
from app.core.yolo_segment import yolo_seg


class RealTimeDetectionSystem:
    def __init__(self, reid_system, frame_skip=1, process_interval=1):
        """
        初始化实时检测系统 - 集成光照不变性和质量筛选

        参数:
            reid_system: 已加载的ReID识别系统
            frame_skip: 隔几帧处理一次（减轻计算负担）
            process_interval: 识别间隔时间
        """
        self.reid_system = reid_system
        self.seger = yolo_seg()  # 初始化SAM轮廓提取器
        self.frame_skip = frame_skip
        self.frame_count = 0
        self.contour_frames = deque(maxlen=190)  # 最多保存190帧轮廓
        self.last_process_time = time.time()
        self.results_cache = None  # 缓存最新识别结果
        self.processing_lock = threading.Lock()  # 线程锁
        self.processing = False  # 是否正在处理识别
        self.process_interval = process_interval  # 识别间隔时间

        # 新增：光照不变性模块
        from app.core.dog_reid_system import IlluminationInvariantModule
        self.illumination_invariant = IlluminationInvariantModule().to(
            self.reid_system.device if hasattr(self.reid_system, 'device') else 'cpu'
        )

        # 启动定时器线程
        self.timer_thread = threading.Thread(target=self._interval_check, daemon=True)
        self.timer_thread.start()

        # 哈希缓存优化SAM Embedding计算
        self.prev_image_hash = None

    def apply_illumination_processing(self, frame):
        """应用光照不变性处理"""
        try:
            if frame is None or frame.size == 0:
                return frame

            # 转换为tensor并归一化
            frame_tensor = torch.tensor(frame, dtype=torch.float32).permute(2, 0, 1)
            frame_tensor = frame_tensor.unsqueeze(0).to(self.reid_system.device) / 255.0

            # 应用光照不变性
            with torch.no_grad():
                processed = self.illumination_invariant(frame_tensor)

            # 转回numpy格式
            processed = processed.squeeze(0).permute(1, 2, 0).cpu().numpy()
            return np.clip(processed * 255, 0, 255).astype(np.uint8)
        except Exception as e:
            print(f"光照处理错误: {e}")
            return frame

    def _check_frame_quality(self, frame):
        """检查帧质量"""
        try:
            if frame is None or frame.size == 0:
                return False

            # 非白色像素比例检查
            non_white_pixels = np.sum(frame <= 200)
            total_pixels = frame.size
            non_white_ratio = non_white_pixels / total_pixels

            if non_white_ratio < 0.0011:
                return False

            # 清晰度检查
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            contrast = gray.std()

            return sharpness >= 15 and contrast >= 10
        except:
            return False

    def reset(self):
        """重置系统状态"""
        with self.processing_lock:
            self.contour_frames.clear()  # 清空轮廓帧队列
            self.results_cache = None  # 清空结果缓存
            self.frame_count = 0  # 重置帧计数
            self.last_process_time = time.time()  # 重置最后处理时间
            self.processing = False  # 标记为未处理状态

    def _interval_check(self):
        """定时检查并触发识别"""
        while True:
            time.sleep(1)
            if len(self.contour_frames) >= 10 or \
                    (time.time() - self.last_process_time) >= self.process_interval:
                self._trigger_processing()

    def _trigger_processing(self):
        """触发后台处理"""
        with self.processing_lock:  # 增加锁保护
            if not self.processing and len(self.contour_frames) >= 15:
                threading.Thread(target=self._process_identification, daemon=True).start()
                self.last_process_time = time.time()

    def process_frame(self, frame):
        """处理单帧图像"""
        self.frame_count += 1

        # 每隔几帧处理一次，减轻计算负担
        if self.frame_count % self.frame_skip != 0:
            return self.results_cache

        # 提取轮廓
        contour = self.seger.get_single_mask_from_cvimage(frame)

        # 如果提取到有效轮廓，保存到队列
        if contour is not None and np.any(contour):
            self.contour_frames.append(contour)
            self._trigger_processing()  # 达到15立即触发

        return self.results_cache

    def _extract_single_feature(self, frame):
        """提取单帧特征"""
        try:
            # 预处理轮廓（转RGB，调整尺寸）
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (256, 256))

            # 转换为张量并归一化
            frame_tensor = torch.tensor(frame).float().permute(2, 0, 1).unsqueeze(0)
            frame_tensor = frame_tensor.to(self.reid_system.device) / 255.0

            # 提取特征
            with torch.no_grad():
                feature = self.reid_system.reid_model(frame_tensor)
                return feature.cpu().numpy()
        except Exception as e:
            print(f"特征提取错误: {e}")
            return None

    def _identify_with_weighted_voting(self, features, method1_weight=0.2, method2_weight=0.8):
        """使用加权投票的识别算法"""
        if not features:
            return {}

        # 方法1：简单投票
        results_method1 = {}
        for feature in features:
            similarities = []
            for dog_feature in self.reid_system.dog_features:
                query = feature.flatten()
                gallery = dog_feature[0].flatten()
                sim = np.dot(query, gallery) / (np.linalg.norm(query) * np.linalg.norm(gallery))
                similarities.append(sim)

            if similarities:
                max_idx = np.argmax(similarities)
                dog_id = self.reid_system.dog_features[max_idx][1]
                results_method1[dog_id] = results_method1.get(dog_id, 0) + 1

        # 方法2：加权投票
        results_method2 = {}
        for feature in features:
            weighted_votes = {}
            for dog_feature in self.reid_system.dog_features:
                dog_id = dog_feature[1]
                query = feature.flatten()
                gallery = dog_feature[0].flatten()
                sim = np.dot(query, gallery) / (np.linalg.norm(query) * np.linalg.norm(gallery))

                if dog_id not in weighted_votes:
                    weighted_votes[dog_id] = 0
                weighted_votes[dog_id] += sim ** 2  # 平方增加高相似度权重

            if weighted_votes:
                max_dog = max(weighted_votes.items(), key=lambda x: x[1])
                results_method2[max_dog[0]] = results_method2.get(max_dog[0], 0) + 1

        # 合并结果
        total_frames = len(features)
        final_confidence = {}
        all_dog_ids = set(results_method1.keys()) | set(results_method2.keys())

        for dog_id in all_dog_ids:
            conf1 = results_method1.get(dog_id, 0) / total_frames
            conf2 = results_method2.get(dog_id, 0) / total_frames
            weighted_conf = (conf1 * method1_weight + conf2 * method2_weight) * 100
            final_confidence[int(dog_id)] = weighted_conf

        return final_confidence

    def _process_identification(self):
        """优化后的特征提取和识别"""
        with self.processing_lock:
            if self.processing:
                return
            self.processing = True

        try:
            frames_to_process = list(self.contour_frames)[-190:]
            features = []
            batch_size = 4  # 小批量处理

            # 分批处理减少内存占用
            for i in range(0, len(frames_to_process), batch_size):
                batch_frames = frames_to_process[i:i + batch_size]
                batch_features = []

                for contour_frame in batch_frames:
                    # 质量预筛选
                    if not self._check_frame_quality(contour_frame):
                        continue

                    # 应用光照处理
                    processed_frame = self.apply_illumination_processing(contour_frame)
                    if processed_frame is None:
                        continue

                    # 特征提取
                    feature = self._extract_single_feature(processed_frame)
                    if feature is not None:
                        batch_features.append(feature)

                features.extend(batch_features)

                # 内存管理
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            # 使用优化的识别算法
            if features:
                results = self._identify_with_weighted_voting(features)
                self.results_cache = self._format_results(results)

        except Exception as e:
            print(f"识别处理错误: {e}")
        finally:
            self.processing = False
            # 滚动清理旧帧
            self.contour_frames = deque(list(self.contour_frames)[-100:], maxlen=190)

    def process_external_frame(self, frame):
        """处理从外部传入的帧（用于帧流模式）"""
        # 预处理帧
        processed_frame = self.apply_illumination_processing(frame)
        if processed_frame is None:
            return None

        # 提取轮廓
        contour = self.seger.get_single_mask_from_cvimage(processed_frame)

        # 保存到队列
        if contour is not None and np.any(contour):
            self.contour_frames.append(contour)
            self._trigger_processing()  # 触发识别

        return self.results_cache

    def _format_results(self, results):
        """格式化识别结果"""
        if not results:
            return None

        formatted_results = {}
        total_detections = sum(results.values())

        for dog_id, count in results.items():
            dog_name = self.reid_system.dog_names.get(int(dog_id), f"未知狗 {dog_id}")
            confidence = count / total_detections * 100
            formatted_results[int(dog_id)] = {
                'name': dog_name,
                'count': count,
                'confidence': confidence
            }

        return formatted_results
