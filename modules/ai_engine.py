import cv2
import time
import platform
import os
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

        # 跨平台摄像头标识：Windows 用整数索引，Linux 用设备路径
        self.os_type = platform.system()
        if self.os_type == "Windows":
            self.camera_id = 0          # 默认索引
        else:
            self.camera_id = "/dev/video0"   # 默认路径

        self.cap = None
        self.use_gstreamer = True

        # Linux 下自动检测 GStreamer 可用性
        if self.os_type == "Linux":
            try:
                test_cap = cv2.VideoCapture(
                    "v4l2src device=/dev/video0 ! video/x-raw,format=YUY2,width=640,height=480 ! videoconvert ! appsink",
                    cv2.CAP_GSTREAMER
                )
                if test_cap.isOpened():
                    self.use_gstreamer = True
                    test_cap.release()
                    print("[AI] GStreamer 后端可用，将使用硬件加速管道")
                else:
                    print("[AI] GStreamer 不可用，回退到 V4L2 后端")
            except:
                print("[AI] GStreamer 检测失败，使用 V4L2 后端")

    def _open_camera_linux(self, device_path):
        # 强制使用 GStreamer，不再回退
        gst_pipeline = (
            f"v4l2src device={device_path} ! "
            "video/x-raw, format=YUY2, width=640, height=480, framerate=30/1 ! "
            "videoconvert ! video/x-raw, format=BGR ! appsink"
        )
        return cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)

    def _open_camera_linux(self, device_path):
        """Linux 下根据检测结果选择 GStreamer 或 V4L2 打开"""
        if self.use_gstreamer:
            gst_pipeline = (
                f"v4l2src device={device_path} ! "
                "video/x-raw, format=YUY2, width=640, height=480, framerate=30/1 ! "
                "videoconvert ! video/x-raw, format=BGR ! appsink"
            )
            return cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        else:
            cap = cv2.VideoCapture(device_path, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return cap

    def _open_camera(self, camera_ref):
        """统一摄像头打开接口，参数在 Windows 下为 int，Linux 下为 str"""
        if self.os_type == "Windows":
            return self._open_camera_windows(camera_ref)
        else:
            return self._open_camera_linux(camera_ref)

    def update_camera(self, camera_ref):
        """camera_ref 在 Windows 下是整数索引，Linux 下是设备路径字符串"""
        self.running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.camera_id = camera_ref
        self.cap = self._open_camera(camera_ref)
        self.running = True
        print(f"[AI] 已切换到摄像头: {camera_ref}")

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
                    # 读取失败时短暂等待，避免空转
                    self.msleep(10)
            else:
                self.msleep(100)
        if self.cap:
            self.cap.release()