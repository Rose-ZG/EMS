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
        recording = sd.rec(int(self.duration * self.sample_rate), samplerate=self.sample_rate, channels=1,
                           dtype='int16')
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
        self.threshold = 1.4  # 动态宽高比阈值初始值
        self.angle_threshold = 35  # 倾角阈值初始值
        self.conf_val = 0.5
        self.ui_ready = True
        self.debug = debug

        self.inference_size = 192
        self.frame_skip = 2

        # Jetson Ubuntu 环境自动开启 FP16 加速
        self.os_type = platform.system()
        self.use_half_precision = True if self.os_type == "Linux" else False

        self.camera_id = 0
        self.cap = None
        self._camera_request = None
        self._frame_counter = 0
        self.last_is_fall = False

        self.fall_history = deque(maxlen=10)

    def _open_camera(self, camera_ref):
        backend = cv2.CAP_DSHOW if self.os_type == "Windows" else cv2.CAP_V4L2
        cap = cv2.VideoCapture(camera_ref, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def request_camera_switch(self, camera_index):
        self._camera_request = camera_index

    def _perform_camera_switch(self, new_index):
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.camera_id = new_index
        self.cap = self._open_camera(new_index)
        self._camera_request = None

    def _fall_detection(self, results):
        is_fall = False
        debug_info = {"box_ratio": None, "tilt_angle": None, "method": None}
        if not results or len(results) == 0:
            return False, debug_info

        for r in results:
            if r.boxes is None or r.keypoints is None: continue
            for i, box in enumerate(r.boxes):
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                w, h = x2 - x1, y2 - y1
                if h < 10 or w < 10: continue

                ratio = w / h
                debug_info["box_ratio"] = ratio
                kps = r.keypoints.data[i].cpu().numpy()

                if len(kps) >= 13 and all(kps[j][2] > 0.4 for j in [5, 6, 11, 12]):
                    shoulder_mid = np.array([(kps[5][0] + kps[6][0]) / 2, (kps[5][1] + kps[6][1]) / 2])
                    hip_mid = np.array([(kps[11][0] + kps[12][0]) / 2, (kps[11][1] + kps[12][1]) / 2])
                    torso_vec = hip_mid - shoulder_mid
                    vert_vec = np.array([0, 1])
                    norm_torso = np.linalg.norm(torso_vec)

                    if norm_torso > 0:
                        cos_ang = np.clip(np.dot(torso_vec, vert_vec) / norm_torso, -1.0, 1.0)
                        angle = np.degrees(np.arccos(cos_ang))
                        debug_info["tilt_angle"] = angle

                        # 核心判定：变宽了 AND 倾斜了
                        if angle > self.angle_threshold and ratio > self.threshold:
                            is_fall = True
                            debug_info["method"] = "combo_box_angle"
                            break
                else:
                    # 兜底策略：只看极其严重的宽高比失调 (被遮挡)
                    if ratio > max(1.5, self.threshold * 1.5):
                        is_fall = True
                        debug_info["method"] = "strict_box_ratio"
                        break

        return is_fall, debug_info

    def get_fall_ratio(self):
        return sum(self.fall_history) / len(self.fall_history) if len(self.fall_history) > 0 else 0.0

    def run(self):
        if not self.cap: self.cap = self._open_camera(self.camera_id)
        prev_time = time.time()

        while self.running:
            if self._camera_request is not None: self._perform_camera_switch(self._camera_request)
            if not self.cap or not self.cap.isOpened():
                self.msleep(30)
                continue

            ret, frame = self.cap.read()
            if not ret or frame is None:
                self.msleep(10)
                continue

            self._frame_counter += 1
            if self._frame_counter % self.frame_skip != 0:
                self._emit_frame(frame, prev_time)
                continue

            try:
                results = self.model(frame, imgsz=self.inference_size, conf=self.conf_val, verbose=False,
                                     half=self.use_half_precision)
                is_fall, debug = self._fall_detection(results)
                self.last_is_fall = is_fall
                self.fall_history.append(is_fall)

                if self.debug and debug["box_ratio"] is not None:
                    print(
                        f"[DEBUG] 宽高比: {debug['box_ratio']:.2f}, 倾角: {debug['tilt_angle']}, 方法: {debug['method']}")

                annotated_frame = results[0].plot() if results else frame
                prev_time = self._emit_frame(annotated_frame, prev_time, is_fall)
            except Exception as e:
                print(f"[AI] 推理出错: {e}")
                self.msleep(100)
            self.msleep(1)

        if self.cap: self.cap.release()

    def _emit_frame(self, frame, prev_time, is_fall=None):
        if is_fall is None: is_fall = self.last_is_fall
        rgb_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_img.shape
        qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
        curr_time = time.time()
        fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
        self.change_pixmap_signal.emit(qt_img, is_fall, fps)
        return curr_time