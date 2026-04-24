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
        self.threshold = 0.6          # 宽高比阈值（宽度/高度）
        self.angle_threshold = 30     # 躯干倾角阈值（度）
        self.conf_val = 0.5
        self.ui_ready = True

        # 性能参数
        self.inference_size = 192     # 推理尺寸
        self.frame_skip = 2           # 跳帧数，2 表示每 2 帧推理一次
        self.use_half_precision = False

        self.os_type = platform.system()
        self.camera_id = 0
        self.cap = None

        # 异步摄像头切换请求
        self._camera_request = None
        self._frame_counter = 0
        self.last_is_fall = False     # 缓存最近一次推理的跌倒状态

    def _open_camera(self, camera_ref):
        """根据平台打开摄像头"""
        if self.os_type == "Windows":
            cap = cv2.VideoCapture(camera_ref, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(camera_ref, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def request_camera_switch(self, camera_index):
        """主线程调用：请求切换摄像头，非阻塞"""
        print(f"[AI] 请求切换摄像头到索引: {camera_index}")
        self._camera_request = camera_index

    def _perform_camera_switch(self, new_index):
        """在线程内部执行摄像头切换"""
        print(f"[AI] 正在线程内切换摄像头到 {new_index}...")
        if self.cap and self.cap.isOpened():
            self.cap.release()
            self.cap = None
        self.camera_id = new_index
        self.cap = self._open_camera(new_index)
        if self.cap and self.cap.isOpened():
            print(f"[AI] 摄像头 {new_index} 切换成功")
        else:
            print(f"[AI] 摄像头 {new_index} 打开失败")
        self._camera_request = None

    def _fall_detection(self, results):
        """
        多策略跌倒判定：
        1. 边界框宽高比 > 1.2 (宽度大于高度，可能躺卧)
        2. 关键点躯干与垂直方向夹角 < angle_threshold (接近水平)
        返回 bool
        """
        is_fall = False
        if not results or len(results) == 0:
            return False

        for r in results:
            # 策略一：边界框宽高比
            if r.boxes is not None:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    h = y2 - y1
                    w = x2 - x1
                    if h > 0 and w / h > 1.2:
                        is_fall = True
                        break

            # 策略二：关键点躯干倾角
            if r.keypoints is not None and r.keypoints.data.shape[0] > 0:
                for kp in r.keypoints.data.cpu().numpy():
                    # 需要有效肩部和髋部关键点
                    if (kp[5][2] > 0.5 and kp[6][2] > 0.5 and
                        kp[11][2] > 0.5 and kp[12][2] > 0.5):
                        shoulder_mid = np.array([(kp[5][0] + kp[6][0]) / 2,
                                                (kp[5][1] + kp[6][1]) / 2])
                        hip_mid = np.array([(kp[11][0] + kp[12][0]) / 2,
                                           (kp[11][1] + kp[12][1]) / 2])
                        torso_vector = hip_mid - shoulder_mid
                        vertical_vector = np.array([0, 1])
                        cos_angle = np.abs(np.dot(torso_vector, vertical_vector)) / \
                                    (np.linalg.norm(torso_vector) * np.linalg.norm(vertical_vector) + 1e-6)
                        angle = np.degrees(np.arccos(cos_angle))
                        if angle < self.angle_threshold:
                            is_fall = True
                            break
        return is_fall

    def run(self):
        print("[AI] 视频处理线程启动")
        if not self.cap:
            self.cap = self._open_camera(self.camera_id)

        prev_time = time.time()

        while self.running:
            # 处理摄像头切换请求（线程内部）
            if self._camera_request is not None:
                self._perform_camera_switch(self._camera_request)

            if not self.cap or not self.cap.isOpened():
                self.msleep(30)
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                self.msleep(10)
                continue

            self._frame_counter += 1

            # ---- 跳帧：非推理帧发送缓存状态 + 原图 ----
            if self._frame_counter % self.frame_skip != 0:
                rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
                curr_time = time.time()
                fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                self.change_pixmap_signal.emit(qt_img, self.last_is_fall, fps)
                continue

            # ---- 推理帧 ----
            try:
                results = self.model(frame, imgsz=self.inference_size,
                                     conf=self.conf_val, verbose=False,
                                     half=self.use_half_precision)
                is_fall = self._fall_detection(results)
                self.last_is_fall = is_fall   # 更新状态缓存

                # 绘制检测结果
                annotated_frame = results[0].plot() if results else frame
                rgb_img = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)

                curr_time = time.time()
                fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                prev_time = curr_time

                self.change_pixmap_signal.emit(qt_img, is_fall, fps)

            except Exception as e:
                print(f"[AI] 推理帧出错: {e}")
                self.msleep(100)
                continue

            self.msleep(1)

        # 退出循环，释放资源
        if self.cap:
            self.cap.release()
        print("[AI] 视频处理线程退出")