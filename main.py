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
        print("[MAIN] 正在初始化窗口...")
        self.setWindowTitle("居家康复监测系统 v5.0")
        self.resize(1200, 850)

        self.available_cams = []
        self.fall_start_time = None
        self.is_fall_ongoing = False

        # 1. 加载 UI
        self.ui = MainDashboard()
        self.setCentralWidget(self.ui)
        print("[MAIN] UI 加载完成")

        # 2. 加载硬件（可在此传入 Twilio 参数）
        mp3_path = os.path.join(os.path.dirname(__file__), "RING.wav")
        self.hw = HardwareManager(
            mp3_path=mp3_path,
            # twilio_sid="你的SID",
            # twilio_token="你的Token",
            # twilio_from="你的主叫号码"
        )

        # 3. 加载 AI 线程
        self.worker = VideoWorker(debug=False)   # 设置 debug=True 可查看检测数值
        self.worker.change_pixmap_signal.connect(self.update_ui, Qt.QueuedConnection)

        # 4. 绑定事件
        self.ui.ref_btn.clicked.connect(self.refresh_cameras)
        self.ui.cam_selector.currentIndexChanged.connect(self.change_camera)
        self.ui.t_slider.valueChanged.connect(self.sync_params)
        self.ui.c_slider.valueChanged.connect(self.sync_params)
        self.ui.reset_btn.clicked.connect(self.reset_system)
        self.ui.snap_btn.clicked.connect(lambda: self.save_snapshot("MANUAL"))
        self.ui.open_btn.clicked.connect(self.open_folder)
        self.ui.call_btn.clicked.connect(self.call_for_help)
        self.ui.save_phone_btn.clicked.connect(self.save_emergency_contact)

        self.worker.start()
        self.refresh_cameras()
        print("[MAIN] 系统准备就绪")

    def sync_params(self):
        self.worker.threshold = self.ui.t_slider.value() / 100.0
        self.worker.angle_threshold = 90 - self.ui.t_slider.value()
        self.worker.conf_val = self.ui.c_slider.value() / 100.0

    def update_ui(self, img, is_fall, fps):
        self.ui.video_label.setPixmap(QPixmap.fromImage(img))
        self.ui.fps_label.setText(f"FPS: {fps:.1f}")

        if not self.worker.is_alarming:
            fall_ratio = self.worker.get_fall_ratio()
            if fall_ratio > 0.7:                # 滑动窗口中70%为跌倒
                if not self.is_fall_ongoing:
                    self.is_fall_ongoing = True
                    self.fall_start_time = time.time()
                    print(f"[MAIN] 可能摔倒 (占比{fall_ratio:.2f})，开始计时")
                elif time.time() - self.fall_start_time > 0.5:
                    self.trigger_alarm()
            else:
                if self.is_fall_ongoing:
                    print("[MAIN] 跌倒占比降低，重置计时器")
                self.is_fall_ongoing = False
                self.fall_start_time = None

        self.worker.ui_ready = True

    def trigger_alarm(self):
        if self.worker.is_alarming:
            return
        self.worker.is_alarming = True
        self.ui.status_label.setText("🚨 紧急报警！")
        self.ui.status_label.setStyleSheet("""
            font-size: 20pt; color: white; background: #d9534f;
            font-weight: bold; border-radius: 14px; padding: 14px;
        """)
        self.hw.alert_with_voice(active=True)
        self.add_log("CRITICAL: 检测到跌倒！已触发报警")
        # 启动语音交互
        self.start_voice_interaction()

    def call_for_help(self):
        """手动确认呼叫"""
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
                # 无语音功能时，直接拨打紧急电话（或可配置跳过）
                self.call_emergency()
                return

            print("[系统] 正在询问摔倒者...")
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
                    else:
                        self.add_log(f"未识别明确含义，将再次询问 (第{attempt + 1}次)")
                else:
                    self.add_log("未收到语音，将再次询问...")
            self.add_log("未得到安全确认，拨打紧急电话")
            self.call_emergency()

        threading.Thread(target=interact, daemon=True).start()

    def call_emergency(self):
        phone = self.ui.phone_edit.text().strip()
        if phone:
            self.hw.call_emergency(phone)
            self.add_log(f"已拨打紧急联系人: {phone}")
        else:
            self.add_log("未设置紧急联系人电话！")

    def reset_system(self):
        self.worker.is_alarming = False
        self.is_fall_ongoing = False
        self.fall_start_time = None
        self.ui.status_label.setText("🟢 系统监控中")
        self.ui.status_label.setStyleSheet("""
            font-size: 20pt; font-weight: bold; color: #11111b;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #a6e3a1, stop:1 #94e2d5);
            border-radius: 14px; padding: 14px;
        """)
        self.hw.alert_with_voice(active=False)
        self.add_log("INFO: 系统已复位")

    def save_emergency_contact(self):
        phone = self.ui.phone_edit.text().strip()
        if phone:
            self.add_log(f"紧急联系人已保存: {phone}")
        else:
            self.add_log("电话号码不能为空")

    def refresh_cameras(self):
        print("[MAIN] 开始刷新摄像头列表")
        self.ui.cam_selector.blockSignals(True)
        self.ui.cam_selector.clear()
        valid = []

        backend = cv2.CAP_DSHOW if self.os_type == "Windows" else cv2.CAP_ANY
        for i in range(3):
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ret, _ = cap.read()
                if ret:
                    valid.append(i)
                    print(f"[MAIN] 发现摄像头: {i}")
                cap.release()
            else:
                cap.release()

        self.available_cams = valid
        self.ui.cam_selector.addItems([f"设备 {i}" for i in valid])
        print(f"[MAIN] 摄像头列表刷新完成，发现 {len(valid)} 个摄像头")

        if valid:
            self.ui.cam_selector.setCurrentIndex(0)
            self.worker.request_camera_switch(valid[0])
        self.ui.cam_selector.blockSignals(False)

    def change_camera(self, index):
        if 0 <= index < len(self.available_cams):
            cam_ref = self.available_cams[index]
            self.worker.request_camera_switch(cam_ref)

    def save_snapshot(self, prefix):
        path = os.path.join(os.getcwd(), "records")
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, f"{prefix}_{time.strftime('%H%M%S')}.jpg")
        if self.ui.video_label.pixmap():
            self.ui.video_label.pixmap().save(file_path)
            self.add_log(f"已保存: {os.path.basename(file_path)}")

    def open_folder(self):
        path = os.path.join(os.getcwd(), "records")
        os.makedirs(path, exist_ok=True)
        if self.os_type == 'Windows':
            os.startfile(path)
        elif self.os_type == 'Darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])

    def add_log(self, msg):
        self.ui.log_box.append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def closeEvent(self, event):
        self.worker.running = False
        self.worker.wait()
        self.hw.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        window = Controller()
        window.show()
        print("[MAIN] 主循环启动")
        sys.exit(app.exec())
    except Exception as e:
        print(f"[CRASH] 程序发生致命错误: {e}")
        input("按回车键退出...")

