import sys, os, time, cv2, subprocess
import platform
import threading
from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *

try:
    from modules.ai_engine import VideoWorker, VoiceAssistant
    from modules.hardware_ctrl import HardwareManager
    from ui.dashboard import MainDashboard
except ImportError as e:
    print(f"导入模块失败，请检查文件夹名是否正确: {e}")

class Controller(QMainWindow):
    def __init__(self):
        self.os_type = platform.system()
        super().__init__()
        self.setWindowTitle("居家康复监测系统 v6.0")
        self.resize(1200, 850)

        self.available_cams = []
        self.fall_start_time = None
        self.is_fall_ongoing = False

        self.ui = MainDashboard()
        self.setCentralWidget(self.ui)

        mp3_path = os.path.join(os.path.dirname(__file__), "RING.wav")
        self.hw = HardwareManager(mp3_path=mp3_path)

        self.worker = VideoWorker(debug=False)
        self.worker.change_pixmap_signal.connect(self.update_ui, Qt.QueuedConnection)

        self.ui.ref_btn.clicked.connect(self.refresh_cameras)
        self.ui.cam_selector.currentIndexChanged.connect(self.change_camera)
        self.ui.t_slider.valueChanged.connect(self.sync_params)
        self.ui.c_slider.valueChanged.connect(self.sync_params)
        self.ui.reset_btn.clicked.connect(self.reset_system)
        self.ui.snap_btn.clicked.connect(lambda: self.save_snapshot("MANUAL"))
        self.ui.open_btn.clicked.connect(self.open_folder)
        self.ui.call_btn.clicked.connect(self.call_for_help)
        self.ui.save_phone_btn.clicked.connect(self.save_emergency_contact)

        self.sync_params() # 初始同步参数
        self.worker.start()
        self.refresh_cameras()

    def sync_params(self):
        slider_val = self.ui.t_slider.value()
        # 更新后的物理阈值映射
        self.worker.threshold = 2.0 - (slider_val / 100.0)
        self.worker.angle_threshold = 95 - slider_val
        self.worker.conf_val = self.ui.c_slider.value() / 100.0

    def update_ui(self, img, is_fall, fps):
        self.ui.video_label.setPixmap(QPixmap.fromImage(img))
        self.ui.fps_label.setText(f"FPS: {fps:.1f}")

        if not self.worker.is_alarming:
            fall_ratio = self.worker.get_fall_ratio()
            if fall_ratio > 0.7:
                if not self.is_fall_ongoing:
                    self.is_fall_ongoing = True
                    self.fall_start_time = time.time()
                elif time.time() - self.fall_start_time > 0.5:
                    self.trigger_alarm()
            else:
                self.is_fall_ongoing = False
                self.fall_start_time = None
        self.worker.ui_ready = True

    def trigger_alarm(self):
        if self.worker.is_alarming: return
        self.worker.is_alarming = True
        self.ui.status_label.setText("🚨 紧急报警！")
        self.ui.status_label.setStyleSheet("font-size: 20pt; color: white; background: #d9534f; font-weight: bold; border-radius: 14px; padding: 14px;")
        self.hw.alert_with_voice(active=True)
        self.add_log("CRITICAL: 检测到跌倒！已触发报警")
        self.start_voice_interaction()

    def call_for_help(self):
        call_path = os.path.join(os.path.dirname(__file__), "CALL.wav")
        if os.path.exists(call_path):
            self.hw.play_audio(call_path, repeat=1)
            self.add_log("USER: 手动触发呼叫求助")
        else:
            self.add_log("ERROR: CALL.wav 文件未找到")

    def start_voice_interaction(self):
        def interact():
            try:
                assistant = VoiceAssistant()
            except Exception as e:
                self.add_log(f"语音模块不可用: {e}")
                self.call_emergency()
                return

            self.hw.play_audio(os.path.join(os.path.dirname(__file__), "CALL.wav"), repeat=1)
            time.sleep(1)

            for attempt in range(2):
                assistant.record_audio()
                text, ok = assistant.speech_to_text()
                if ok:
                    result = assistant.analyze_response(text)
                    if result == 'safe':
                        self.add_log(f"用户回复“{text}” (安全)")
                        self.reset_system()
                        return
                    elif result == 'danger':
                        self.add_log(f"用户回复“{text}” (危险)")
                        self.call_emergency()
                        return
            self.add_log("未得到安全确认，拨打紧急电话")
            self.call_emergency()

        threading.Thread(target=interact, daemon=True).start()

    def call_emergency(self):
        phone = self.ui.phone_edit.text().strip()
        if phone:
            self.hw.call_emergency(phone)
            self.add_log(f"已拨打紧急联系人: {phone}")
        else:
            self.add_log("未设置电话！")

    def reset_system(self):
        self.worker.is_alarming = False
        self.is_fall_ongoing = False
        self.fall_start_time = None
        self.ui.status_label.setText("🟢 系统监控中")
        self.ui.status_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #11111b; background: #a6e3a1; border-radius: 14px; padding: 14px;")
        self.hw.alert_with_voice(active=False)
        self.add_log("INFO: 系统已复位")

    def save_emergency_contact(self):
        phone = self.ui.phone_edit.text().strip()
        if phone: self.add_log(f"紧急联系人已保存: {phone}")

    def refresh_cameras(self):
        self.ui.cam_selector.blockSignals(True)
        self.ui.cam_selector.clear()
        valid = []
        backend = cv2.CAP_DSHOW if self.os_type == "Windows" else cv2.CAP_V4L2
        for i in range(3):
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                valid.append(i)
                cap.release()
        self.available_cams = valid
        self.ui.cam_selector.addItems([f"设备 {i}" for i in valid])
        if valid:
            self.ui.cam_selector.setCurrentIndex(0)
            self.worker.request_camera_switch(valid[0])
        self.ui.cam_selector.blockSignals(False)

    def change_camera(self, index):
        if 0 <= index < len(self.available_cams):
            self.worker.request_camera_switch(self.available_cams[index])

    def save_snapshot(self, prefix):
        path = os.path.join(os.getcwd(), "records")
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, f"{prefix}_{time.strftime('%H%M%S')}.jpg")
        if self.ui.video_label.pixmap():
            self.ui.video_label.pixmap().save(file_path)
            self.add_log(f"已保存截图")

    def open_folder(self):
        path = os.path.join(os.getcwd(), "records")
        os.makedirs(path, exist_ok=True)
        if self.os_type == 'Windows': os.startfile(path)
        elif self.os_type == 'Darwin': subprocess.run(['open', path])
        else: subprocess.run(['xdg-open', path])

    def add_log(self, msg):
        self.ui.append_log(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def closeEvent(self, event):
        self.worker.running = False
        self.worker.wait()
        self.hw.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Controller()
    window.show()
    sys.exit(app.exec())