import cv2
import time
import platform
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from ultralytics import YOLO

class VideoWorker(QThread):
    change_pixmap_signal = Signal(QImage, bool, float)

    def __init__(self, model_path='yolov8n-pose.pt'):
        super().__init__()
        try:
            print(f"[AI] 正在加载模型: {model_path}...")
            self.model = YOLO(model_path)
            print("[AI] 模型加载成功")
        except Exception as e:
            print(f"[AI] 模型加载失败: {e}")
            self.model = None

        self.running = True
        self.is_alarming = False
        self.threshold = 0.6          # 宽高比阈值
        self.angle_threshold = 30     # 躯干与垂直方向夹角阈值（度）
        self.conf_val = 0.5
        self.ui_ready = True

        # 性能调优参数
        self.inference_size = 192     # 缩小推理尺寸，速度优先
        self.frame_skip = 2           # 跳帧数，每2帧推理一次
        self.use_half_precision = False  # Windows 下强制 FP32

        # 跨平台摄像头索引
        self.os_type = platform.system()
        self.camera_id = 0
        self.cap = None

    def _open_camera(self, camera_ref):
        """统一打开摄像头（捕获分辨率 480x360）"""
        if self.os_type == "Windows":
            cap = cv2.VideoCapture(camera_ref)
        else:
            cap = cv2.VideoCapture(camera_ref, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _fall_detection(self, results):
        """
        多策略跌倒判定：
        1. 关键点躯干倾角 < angle_threshold (角度越小越接近水平，即跌倒)
        2. 辅助：边界框宽高比 < threshold (宽大于高)
        返回是否跌倒
        """
        is_fall = False
        if not results or len(results) == 0:
            return False

        for r in results:
            # 策略一：基于边界框宽高比（快速筛查）
            if r.boxes is not None:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    h = y2 - y1
                    w = x2 - x1
                    if h > 0 and w / h > 1.2:   # 宽高比大于1.2，可能躺卧
                        is_fall = True
                        break

            # 策略二：基于关键点躯干倾角（更准确）
            if r.keypoints is not None and r.keypoints.data.shape[0] > 0:
                for kp in r.keypoints.data.cpu().numpy():
                    # 需要有效关键点：左肩(5)、右肩(6)、左髋(11)、右髋(12)
                    if (kp[5][2] > 0.5 and kp[6][2] > 0.5 and
                        kp[11][2] > 0.5 and kp[12][2] > 0.5):
                        # 计算肩部中点与髋部中点
                        shoulder_mid = np.array([(kp[5][0] + kp[6][0]) / 2,
                                                (kp[5][1] + kp[6][1]) / 2])
                        hip_mid = np.array([(kp[11][0] + kp[12][0]) / 2,
                                           (kp[11][1] + kp[12][1]) / 2])
                        # 躯干向量
                        torso_vector = hip_mid - shoulder_mid
                        # 与垂直方向（向下）夹角
                        vertical_vector = np.array([0, 1])
                        cos_angle = np.abs(np.dot(torso_vector, vertical_vector)) / \
                                    (np.linalg.norm(torso_vector) * np.linalg.norm(vertical_vector) + 1e-6)
                        angle = np.degrees(np.arccos(cos_angle))
                        if angle < self.angle_threshold:   # 倾角小于30°即接近水平
                            is_fall = True
                            break
        return is_fall

    def update_camera(self, camera_ref):
        print(f"[AI] 切换摄像头到索引: {camera_ref}")
        self.running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.camera_id = camera_ref
        self.cap = self._open_camera(camera_ref)
        self.running = True

    def run(self):
        if not self.cap:
            self.cap = self._open_camera(self.camera_id)

        prev_time = time.time()
        frame_counter = 0

        while self.running:
            if not self.cap or not self.cap.isOpened():
                self.msleep(50)
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                self.msleep(10)
                continue

            frame_counter += 1

            # 跳帧：只有每隔 frame_skip 帧才推理
            if frame_counter % self.frame_skip != 0:
                # 跳过推理，但发送上一帧的画面和状态（用原图）
                if self.ui_ready:
                    # 发送未经推理的原始图像（或上次推理结果），避免画面停止
                    rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_img.shape
                    qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
                    self.change_pixmap_signal.emit(qt_img, False, 0)
                continue

            # 推理
            try:
                results = self.model(frame, imgsz=self.inference_size,
                                     conf=self.conf_val, verbose=False,
                                     half=self.use_half_precision)
                is_fall = self._fall_detection(results)

                # 绘制结果
                annotated_frame = results[0].plot() if results else frame
                rgb_img = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)

                # 计算即时FPS
                curr_time = time.time()
                fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                prev_time = curr_time

                if self.ui_ready:
                    self.change_pixmap_signal.emit(qt_img, is_fall, fps)
            except Exception as e:
                print(f"[AI] 推理异常: {e}")
                self.msleep(100)
                continue

            # 短暂休眠避免 CPU 过载
            self.msleep(1)

        if self.cap:
            self.cap.release()