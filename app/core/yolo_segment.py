from segment_anything import sam_model_registry, SamPredictor
from ultralytics import YOLO
import torch
import cv2
import numpy as np
import math


class yolo_seg:
    def __init__(self):
        # 延迟加载模型
        self.model = None
        self.tracker = None
        self.sam = None
        self.sam_predictor = None
        self.prev_image_hash = None

    def load_models(self):
        """按需加载模型"""
        if self.model is None:
            self.model = YOLO("./fea_data/yolov8m-seg.pt")

        if self.sam is None:
            sam_checkpoint = "./fea_data/sam_vit_b_01ec64.pth"
            model_type = "vit_b"
            self.sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
            self.sam.to(device="cuda" if torch.cuda.is_available() else "cpu")
            self.sam_predictor = SamPredictor(self.sam)

    def get_single_mask_from_cvimage(self, image, min_sharpness=15, min_contrast=10):
        """从图像中获取分割掩码"""
        # 按需加载模型
        self.load_models()

        # 图像质量检查
        if image is None:
            return None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        contrast = gray.std()

        # 跳过低质量图像
        if sharpness < min_sharpness or contrast < min_contrast:
            return None

        # 预处理光照
        image = self.preprocess_illumination(image)

        # YOLO检测
        results = self.model.predict(image, conf=0.73)
        segmentation_mask = np.zeros_like(image, dtype=np.uint8)

        if len(results[0]) == 0:
            return None

        # 创建白色背景
        white_background = np.ones_like(image, dtype=np.uint8) * 255

        # 处理检测结果
        dog_boxes = []
        for box in results[0].boxes:
            if int(box.cls.item()) == 16:  # 类别16为狗
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                w, h = x2 - x1, y2 - y1

                # 尺寸过滤
                if w * h < 3300:
                    continue

                dog_boxes.append((x1, y1, x2, y2))

        if not dog_boxes:
            return None

        # 计算当前图像的哈希值
        current_image_hash = hash(image.tobytes())

        # 如果图像变化，重新设置SAM的Embedding
        if self.prev_image_hash != current_image_hash:
            self.sam_predictor.set_image(image)
            self.prev_image_hash = current_image_hash

        # 对每个检测到的狗进行分割
        for (x1, y1, x2, y2) in dog_boxes:
            input_box = np.array([x1, y1, x2, y2])
            masks, _, _ = self.sam_predictor.predict(
                box=input_box[None, :],
                multimask_output=False
            )
            best_mask = masks[0]

            # 将分割结果叠加到白色背景
            segmented_image = white_background.copy()
            segmented_image[best_mask] = image[best_mask]
            segmentation_mask = cv2.add(segmentation_mask, segmented_image)

        return segmentation_mask

    def preprocess_illumination(self, image):
        """光照预处理"""
        # 自适应直方图均衡化 (CLAHE)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        # 自适应伽马校正
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        mean = np.mean(gray)
        gamma = math.log(0.5) / math.log(mean / 255.0) if mean > 0 else 1.0
        gamma = max(0.5, min(gamma, 2.0))

        # 应用伽马校正
        inv_gamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** inv_gamma) * 255
                          for i in np.arange(0, 256)]).astype("uint8")
        return cv2.LUT(enhanced, table)