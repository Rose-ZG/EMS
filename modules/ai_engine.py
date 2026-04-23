import cv2
import time
import platform
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
        self.threshold = 0.6
        self.conf_val = 0.5
        self.ui_ready = True

        # 跨平台：统一使用数字索引
        self.os_type = platform.system()
        self.camera_id = 0   # 默认索引
        self.cap = None

    def _open_camera_windows(self, index):
        """Windows 下使用 DirectShow 后端"""
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def _open_camera_linux(self, index):
        """Linux 下强制使用 V4L2 后端，并设置 YUYV 格式"""
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def _open_camera(self, camera_ref):
        """统一接口，camera_ref 为整数索引"""
        if self.os_type == "Windows":
            return self._open_camera_windows(camera_ref)
        else:
            return self._open_camera_linux(camera_ref)

    def update_camera(self, camera_ref):
        """切换摄像头，camera_ref 为整数索引"""
        self.running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.camera_id = camera_ref
        self.cap = self._open_camera(camera_ref)
        self.running = True
        print(f"[AI] 已切换到摄像头索引: {camera_ref}")

    def run(self):
        if not self.cap:
            self.cap = self._open_camera(self.camera_id)

        prev_time = 0
        while self.running:
            if self.ui_ready and self.cap and self.cap.isOpened() and self.model:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    curr_time = time.time()
                    fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                    prev_time = curr_time

                    results = self.model(frame, imgsz=256, conf=self.conf_val, verbose=False)
                    is_fall = False
                    for r in results:
                        for box in r.boxes:
                            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                            if (y2 - y1) / (x2 - x1) < self.threshold:
                                is_fall = True
                                break

                    annotated_frame = results[0].plot()
                    rgb_img = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_img.shape
                    qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)

                    self.ui_ready = False
                    self.change_pixmap_signal.emit(qt_img, is_fall, fps)
                else:
                    self.msleep(10)
            else:
                self.msleep(100)
        if self.cap:
            self.cap.release()