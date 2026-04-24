import cv2
import time
import platform
import numpy as np
from collections import deque
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from ultralytics import YOLO

# ----- 语音助手类 -----
try:
    import sounddevice as sd
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
except ImportError:
    SPEECH_AVAILABLE = False
    print("[语音] 语音库未安装，语音交互功能禁用")
import threading

class VoiceAssistant:
    def __init__(self, sample_rate=16000, duration=3):
        if not SPEECH_AVAILABLE:
            raise RuntimeError("语音库不可用")
        self.recognizer = sr.Recognizer()
        self.sample_rate = sample_rate
        self.duration = duration
        self.audio_data = None

    def record_audio(self):
        print("[语音] 开始录音...")
        recording = sd.rec(int(self.duration * self.sample_rate),
                           samplerate=self.sample_rate,
                           channels=1, dtype='int16')
        sd.wait()
        self.audio_data = np.squeeze(recording)
        print("[语音] 录音结束")
        return self.audio_data

    def speech_to_text(self):
        if self.audio_data is None:
            return "", False
        audio_bytes = (self.audio_data * 32767).astype(np.int16).tobytes()
        audio = sr.AudioData(audio_bytes, self.sample_rate, 2)
        try:
            # 在线识别（需联网）
            text = self.recognizer.recognize_google(audio, language='zh-CN')
            print(f"[语音] 识别结果: {text}")
            return text, True
        except sr.UnknownValueError:
            print("[语音] 无法识别")
            return "", False
        except sr.RequestError as e:
            print(f"[语音] 服务错误: {e}")
            return "", False

    def analyze_response(self, text):
        safe_keywords = ['没事', '没', '好', '不用', '没事儿', '没问题', '挺好', '还行']
        danger_keywords = ['摔', '严重', '疼', '不行', '快不行', '救命', '伤', '骨折', '不舒服']
        if any(word in text for word in danger_keywords):
            return 'danger'
        elif any(word in text for word in safe_keywords):
            return 'safe'
        else:
            return 'unclear'


# ----- 视频处理与跌倒检测类 -----
class VideoWorker(QThread):
    change_pixmap_signal = Signal(QImage, bool, float)

    def __init__(self, model_path='yolov8n-pose.pt', debug=False):
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
        self.angle_threshold = 45     # 躯干倾角阈值（度）
        self.conf_val = 0.5
        self.ui_ready = True
        self.debug = debug

        self.inference_size = 192
        self.frame_skip = 2
        self.use_half_precision = False

        self.os_type = platform.system()
        self.camera_id = 0
        self.cap = None
        self._camera_request = None
        self._frame_counter = 0
        self.last_is_fall = False

        # 滑动窗口，存储最近10帧的跌倒判定结果
        self.fall_history = deque(maxlen=10)

    def _open_camera(self, camera_ref):
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
        print(f"[AI] 请求切换摄像头到索引: {camera_index}")
        self._camera_request = camera_index

    def _perform_camera_switch(self, new_index):
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
        is_fall = False
        debug_info = {"box_ratio": None, "tilt_angle": None, "method": None}
        if not results or len(results) == 0:
            return False, debug_info

        for r in results:
            # 策略1：边界框宽高比
            if r.boxes is not None:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    h = y2 - y1
                    w = x2 - x1
                    if h > 0:
                        ratio = w / h
                        debug_info["box_ratio"] = ratio
                        if ratio > self.threshold:
                            is_fall = True
                            debug_info["method"] = "box_ratio"
                            break
            # 策略2：关键点躯干倾角
            if r.keypoints is not None and r.keypoints.data.shape[0] > 0:
                for kp in r.keypoints.data.cpu().numpy():
                    if (kp[5][2] > 0.5 and kp[6][2] > 0.5 and
                        kp[11][2] > 0.5 and kp[12][2] > 0.5):
                        shoulder_mid = np.array([(kp[5][0] + kp[6][0]) / 2,
                                                (kp[5][1] + kp[6][1]) / 2])
                        hip_mid = np.array([(kp[11][0] + kp[12][0]) / 2,
                                           (kp[11][1] + kp[12][1]) / 2])
                        torso_vec = hip_mid - shoulder_mid
                        vert_vec = np.array([0, 1])
                        cos_ang = np.abs(np.dot(torso_vec, vert_vec)) / \
                                  (np.linalg.norm(torso_vec) * np.linalg.norm(vert_vec) + 1e-6)
                        angle = np.degrees(np.arccos(cos_ang))
                        debug_info["tilt_angle"] = angle
                        if angle < self.angle_threshold:
                            is_fall = True
                            debug_info["method"] = "tilt_angle"
                            break
        return is_fall, debug_info

    def get_fall_ratio(self):
        if len(self.fall_history) == 0:
            return 0.0
        return sum(self.fall_history) / len(self.fall_history)

    def run(self):
        print("[AI] 视频处理线程启动")
        if not self.cap:
            self.cap = self._open_camera(self.camera_id)

        prev_time = time.time()

        while self.running:
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

            # ---------- 跳帧处理 ----------
            if self._frame_counter % self.frame_skip != 0:
                rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_img.shape
                qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
                curr_time = time.time()
                fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                self.change_pixmap_signal.emit(qt_img, self.last_is_fall, fps)
                continue

            # ---------- 推理帧 ----------
            try:
                results = self.model(frame, imgsz=self.inference_size,
                                     conf=self.conf_val, verbose=False,
                                     half=self.use_half_precision)
                is_fall, debug = self._fall_detection(results)
                self.last_is_fall = is_fall
                self.fall_history.append(is_fall)

                if self.debug and debug["box_ratio"] is not None:
                    print(f"[DEBUG] 宽高比: {debug['box_ratio']:.2f}, 倾角: {debug['tilt_angle']}, 方法: {debug['method']}")

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

        if self.cap:
            self.cap.release()
        print("[AI] 视频处理线程退出")