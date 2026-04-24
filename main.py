import sys, os, time, cv2, subprocess
import platform
from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *

try:
    from modules.ai_engine import VideoWorker
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

        self.ui = MainDashboard()
        self.setCentralWidget(self.ui)
        print("[MAIN] UI 加载完成")

        mp3_path = os.path.join(os.path.dirname(__file__), "RING.wav")
        self.hw = HardwareManager(mp3_path=mp3_path)

        self.worker = VideoWorker()
        self.worker.change_pixmap_signal.connect(self.update_ui, Qt.QueuedConnection)

        # 绑定事件
        self.ui.ref_btn.clicked.connect(self.refresh_cameras)
        self.ui.cam_selector.currentIndexChanged.connect(self.change_camera)
        self.ui.t_slider.valueChanged.connect(self.sync_params)
        self.ui.c_slider.valueChanged.connect(self.sync_params)
        self.ui.reset_btn.clicked.connect(self.reset_system)
        self.ui.snap_btn.clicked.connect(lambda: self.save_snapshot("MANUAL"))
        self.ui.open_btn.clicked.connect(self.open_folder)
        # 新增：摔倒确认呼叫按钮
        self.ui.call_btn.clicked.connect(self.call_for_help)

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
            if is_fall:
                if not self.is_fall_ongoing:
                    self.is_fall_ongoing = True
                    self.fall_start_time = time.time()
                    print(f"[MAIN] 可能摔倒，开始计时 {self.fall_start_time:.2f}")
                else:
                    elapsed = time.time() - self.fall_start_time
                    if elapsed > 0.5:
                        self.trigger_alarm()
            else:
                if self.is_fall_ongoing:
                    print("[MAIN] 姿态恢复正常，重置摔倒计时器")
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

    def call_for_help(self):
        """手动触发呼叫求助"""
        call_path = os.path.join(os.path.dirname(__file__), "CALL.wav")
        if os.path.exists(call_path):
            self.hw.play_audio(call_path, repeat=1)   # 播放一次
            self.add_log("USER: 手动触发呼叫求助")
            # 如果希望同时发送串口信号，可增加：
            # self.hw.send_alarm(True)
        else:
            self.add_log("ERROR: CALL.wav 文件未找到，请检查")
            print("[MAIN] CALL.wav 不存在，无法播放呼叫音频")

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