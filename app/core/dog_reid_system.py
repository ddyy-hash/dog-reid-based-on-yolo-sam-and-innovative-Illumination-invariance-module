import os
import queue
import threading
import cv2
import numpy as np
import torch
import torchreid
import logging
import shutil
import gc

from .yolo_segment import yolo_seg
from torchvision import transforms
from PIL import Image


# 简化版光照不变性模块
class IlluminationInvariantModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        # 简化网络结构：2层卷积替代原始4层
        self.conv = torch.nn.Sequential(
            torch.nn.Conv2d(3, 16, kernel_size=3, padding=1),
            torch.nn.ReLU(),
            torch.nn.Conv2d(16, 3, kernel_size=3, padding=1),
            torch.nn.Sigmoid()
        )

    def forward(self, x):
        # 学习光照不变性掩码并应用
        return x * self.conv(x)


class DogReIDSystem:
    def __init__(self, model_path='./fea_data/illumination_robust_model.pth'):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model_path = model_path
        self.seger = None  # 延迟加载
        self.reid_model = None
        self.dog_names = {0: "豆豆", 1: "皮特", 2: "大乖", 3: "多比"}
        self.dog_features = []
        self.lock = threading.Lock()
        self.illumination_invariant = IlluminationInvariantModule().to(self.device)
        self.load_reid_model()
        self.load_dog_database()

    def load_yolo_and_sam(self):
        """按需加载YOLO和SAM模型"""
        if self.seger is None:
            self.seger = yolo_seg()
            logging.info("YOLO和SAM模型加载完成")

    def release_yolo_and_sam(self):
        """释放YOLO和SAM模型以节省内存"""
        if self.seger:
            del self.seger
            self.seger = None
            logging.info("YOLO和SAM模型已释放")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def process_video_and_save_frames(self, video_path, temp_dir):
        """处理视频并保存关键帧"""
        self.load_yolo_and_sam()
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError("无法打开视频文件")

        # 获取视频信息
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        start_frame = int(total_frames * 0.1)
        end_frame = total_frames - int(total_frames * 0.1)
        max_save_frames = 190  # 限制最大保存帧数

        os.makedirs(temp_dir, exist_ok=True)
        frame_queue = queue.Queue(maxsize=20)
        saved_frame_count = 0
        exit_event = threading.Event()

        def read_frames():
            """帧读取线程"""
            try:
                read_cap = cv2.VideoCapture(video_path)
                read_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                current_frame = start_frame

                while (current_frame <= end_frame and
                       saved_frame_count < max_save_frames and
                       not exit_event.is_set()):

                    read_cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                    ret, frame = read_cap.read()
                    if not ret:
                        break

                    # 质量预筛选：跳过低质量帧
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
                    contrast = gray.std()
                    if sharpness < 15 or contrast < 10:
                        current_frame += 5
                        continue

                    frame_queue.put(frame)
                    current_frame += 1  # 跳帧采样

                frame_queue.put(None)  # 结束信号
            except Exception as e:
                logging.error(f"读帧错误: {e}")
            finally:
                read_cap.release()

        def process_frames():
            """帧处理线程"""
            nonlocal saved_frame_count
            try:
                while saved_frame_count < max_save_frames and not exit_event.is_set():
                    frame = frame_queue.get()
                    if frame is None:
                        break

                    # 分割图像
                    segmented_frame = self.seger.get_single_mask_from_cvimage(frame)
                    if segmented_frame is None:
                        continue

                    # 计算非白色像素的比例
                    non_white_pixels = np.sum(segmented_frame <= 200)
                    total_pixels = segmented_frame.size
                    non_white_ratio = non_white_pixels / total_pixels

                    # 如果非白色像素比例小于 0.11%，则跳过该帧
                    if non_white_ratio < 0.0011:
                        continue

                    # 轮廓完整性检查
                    if not self.check_silhouette_integrity(segmented_frame):
                        continue

                    # 保存有效帧
                    temp_file = os.path.join(temp_dir, f"frame_{saved_frame_count:04d}.png")
                    cv2.imwrite(temp_file, segmented_frame)
                    saved_frame_count += 1

                    # 定期清理内存
                    if saved_frame_count % 10 == 0:
                        gc.collect()
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
            except Exception as e:
                logging.error(f"处理帧错误: {e}")

        # 启动线程
        reader = threading.Thread(target=read_frames)
        processor = threading.Thread(target=process_frames)
        reader.daemon = True
        processor.daemon = True
        reader.start()
        processor.start()

        # 等待线程完成
        try:
            reader.join(timeout=120)
            processor.join(timeout=120)
        finally:
            cap.release()
            self.release_yolo_and_sam()
            exit_event.set()

        return min(saved_frame_count, max_save_frames)

    def check_silhouette_integrity(self, image):
        """检查剪影轮廓完整性"""
        if image is None or image.size == 0:
            return False

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return False

        main_contour = max(contours, key=cv2.contourArea)
        contour_area = cv2.contourArea(main_contour)
        x, y, w, h = cv2.boundingRect(main_contour)
        rect_area = w * h

        # 避免除零错误
        if rect_area == 0:
            return False

        # 轮廓面积占矩形面积比例阈值
        return (contour_area / rect_area) > 0.3

    def load_reid_model(self):
        """加载训练好的光照鲁棒模型"""
        if self.reid_model is None:
            # 使用与训练相同的模型结构
            self.reid_model = torchreid.models.build_model(
                name='osnet_ain_x1_0',  # 使用传入的模型名称
                num_classes=4,  # 与训练时的类别数一致
                loss='softmax',
                pretrained=False
            )
            self.reid_model = self.reid_model.to(self.device)

            # 加载训练好的权重
            if os.path.exists(self.model_path):
                try:
                    checkpoint = torch.load(self.model_path, map_location=self.device)

                    # 处理不同的保存格式
                    if 'model_state_dict' in checkpoint:
                        state_dict = checkpoint['model_state_dict']
                    else:
                        state_dict = checkpoint

                    # 加载权重
                    self.reid_model.load_state_dict(state_dict)
                    logging.info(f"成功加载光照鲁棒模型: {self.model_path}")
                except Exception as e:
                    logging.error(f"加载光照鲁棒模型失败: {e}")
                    raise RuntimeError(f"无法加载光照鲁棒模型: {e}")
            else:
                logging.error(f"模型文件不存在: {self.model_path}")
                raise FileNotFoundError(f"模型文件不存在: {self.model_path}")

            self.reid_model.eval()
            logging.info("光照鲁棒ReID模型加载完成")

    def release_reid_model(self):
        """释放重识别模型"""
        if self.reid_model:
            del self.reid_model
            self.reid_model = None
            logging.info("ReID模型已释放")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def extract_features(self, temp_dir, frame_count):
        """提取特征向量"""
        self.load_reid_model()
        features = []
        max_frames = min(frame_count, 190)  # 限制处理帧数
        batch_size = 4  # 小批量处理减少内存占用

        valid_files = sorted([f for f in os.listdir(temp_dir) if f.endswith(".png")])[:max_frames]

        # 分批处理特征提取
        for i in range(0, len(valid_files), batch_size):
            batch_files = valid_files[i:i + batch_size]
            batch_features = []

            for filename in batch_files:
                filepath = os.path.join(temp_dir, filename)
                frame = cv2.imread(filepath)
                if frame is None:
                    continue

                # 应用光照归一化
                frame = self.apply_illumination_invariant_processing(frame)
                if frame is None:
                    continue

                # 预处理
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame = cv2.resize(frame, (256, 256))
                frame_tensor = torch.tensor(frame).float().permute(2, 0, 1)
                frame_tensor = frame_tensor.unsqueeze(0).to(self.device) / 255.0

                # 提取特征
                with torch.no_grad():
                    feature = self.reid_model(frame_tensor)
                    batch_features.append(feature.cpu().numpy())

                # 及时释放内存
                del frame_tensor
                torch.cuda.empty_cache() if torch.cuda.is_available() else None

            features.extend(batch_features)

        self.release_reid_model()
        return features

    def apply_illumination_invariant_processing(self, frame):
        """应用光照不变性处理"""
        try:
            # 输入验证
            if frame is None or frame.size == 0:
                return frame

            # 确保数据类型正确
            if frame.dtype != np.uint8:
                frame = np.clip(frame, 0, 255).astype(np.uint8)

            # 转换为tensor
            frame_tensor = torch.tensor(frame, dtype=torch.float32).permute(2, 0, 1)
            frame_tensor = frame_tensor.unsqueeze(0).to(self.device) / 255.0

            # 应用光照不变性模块
            with torch.no_grad():
                processed_frame = self.illumination_invariant(frame_tensor)

            # 转换回numpy
            processed_frame = processed_frame.squeeze(0).permute(1, 2, 0).cpu().numpy()
            processed_frame = np.clip(processed_frame * 255, 0, 255).astype(np.uint8)

            return processed_frame
        except Exception as e:
            logging.error(f"光照处理错误: {e}")
            return frame  # 返回原始帧

    def identify_dogs(self, features, method1_weight=0.2, method2_weight=0.8):
        """识别狗并返回置信度"""
        if not features:
            return {}

        # 方法1：简单投票
        results_method1 = {}
        for feature in features:
            similarities = []
            for dog_feature in self.dog_features:
                query = feature.flatten()
                gallery = dog_feature[0].flatten()
                sim = np.dot(query, gallery) / (np.linalg.norm(query) * np.linalg.norm(gallery))
                similarities.append(sim)

            if similarities:
                max_idx = np.argmax(similarities)
                dog_id = self.dog_features[max_idx][1]
                results_method1[dog_id] = results_method1.get(dog_id, 0) + 1

        # 方法2：加权投票
        results_method2 = {}
        for feature in features:
            weighted_votes = {}
            for i, dog_feature in enumerate(self.dog_features):
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

    def load_dog_database(self):
        """加载狗特征数据库"""
        features_path = r"C:\Users\dy\Desktop\redog2.0\core\dog_database\features\universal_features_h.npy"
        if os.path.exists(features_path):
            try:
                self.dog_features = np.load(features_path, allow_pickle=True)
                logging.info(f"已加载 {len(self.dog_features)} 条狗特征")
            except Exception as e:
                logging.error(f"加载狗数据库错误: {e}")
                self.dog_features = []
        return self.dog_features

    def cleanup_temp_frames(self, temp_dir):
        """清理临时帧"""
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logging.info(f"已清理临时目录: {temp_dir}")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()