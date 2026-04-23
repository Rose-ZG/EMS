import sys, os, time, cv2, subprocess
import platform  #引入系统识别模块
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
        #初始化时先判定系统环境
        self.os_type=platform.system()
        #判定OpenCV驱动后端
        self.cap_backend = cv2.CAP_MSMF if self.os_type == "Windows" else cv2.CAP_ANY

        super().__init__()
        print("[MAIN] 正在初始化窗口...")
        self.setWindowTitle("居家康复监测系统 v4.0")
        self.resize(1200, 850)

        self.available_cams = []
        self.fall_counter = 0

        # 1. 加载UI
        self.ui = MainDashboard()
        self.setCentralWidget(self.ui)
        print("[MAIN] UI 加载完成")

        # 2. 加载硬件
        mp3_path = os.path.join(os.path.dirname(__file__), "RING.wav")
        self.hw = HardwareManager(mp3_path=mp3_path)

        # 3. 加载AI线程
        self.worker = VideoWorker()
        self.worker.change_pixmap_signal.connect(self.update_ui, Qt.QueuedConnection)

        # 4. 绑定事件
        self.ui.ref_btn.clicked.connect(self.refresh_cameras)
        self.ui.cam_selector.currentIndexChanged.connect(self.change_camera)
        self.ui.t_slider.valueChanged.connect(self.sync_params)
        self.ui.c_slider.valueChanged.connect(self.sync_params)
        self.ui.reset_btn.clicked.connect(self.reset_system)
        self.ui.snap_btn.clicked.connect(lambda: self.save_snapshot("MANUAL"))
        self.ui.open_btn.clicked.connect(self.open_folder)

        self.refresh_cameras()
        self.worker.start()
        print("[MAIN] 系统准备就绪")

    def sync_params(self):
        self.worker.threshold = self.ui.t_slider.value() / 100.0
        self.worker.conf_val = self.ui.c_slider.value() / 100.0

    def update_ui(self, img, is_fall, fps):
        self.ui.video_label.setPixmap(QPixmap.fromImage(img))
        self.ui.fps_label.setText(f"FPS: {fps:.1f}")

        if is_fall and not self.worker.is_alarming:
            self.fall_counter += 1
            if self.fall_counter > 12: self.trigger_alarm()
        else:
            self.fall_counter = 0
        self.worker.ui_ready = True

    # 在 Controller 类中修改 trigger_alarm 方法
    def trigger_alarm(self):
        if self.worker.is_alarming:
            return
        self.worker.is_alarming = True
        self.ui.status_label.setText("🚨 紧急报警！")
        self.ui.status_label.setStyleSheet("""
            font-size: 20pt; color: white; background: #d9534f; 
            font-weight: bold; border-radius: 14px; padding: 14px;
        """)
        # 新硬件管理：同时触发串口和语音
        self.hw.alert_with_voice(active=True)
        self.add_log("CRITICAL: 检测到跌倒！已触发报警")

    def reset_system(self):
        self.worker.is_alarming = False
        self.ui.status_label.setText("🟢 系统监控中")
        self.ui.status_label.setStyleSheet("""
            font-size: 20pt; font-weight: bold; color: #11111b;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #a6e3a1, stop:1 #94e2d5);
            border-radius: 14px; padding: 14px;
        """)
        self.hw.alert_with_voice(active=False)  # 停止报警
        self.add_log("INFO: 系统已复位")

    def refresh_cameras(self):
        self.ui.cam_selector.blockSignals(True)
        self.ui.cam_selector.clear()
        valid = []

        if self.os_type == "Windows":
            # Windows：枚举摄像头索引
            for i in range(3):
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        valid.append(i)
                    cap.release()
                else:
                    cap.release()
            self.available_cams = valid
            self.ui.cam_selector.addItems([f"设备 {i}" for i in valid])
        else:
            # Linux：枚举 /dev/video* 设备
            for i in range(3):
                dev = f"/dev/video{i}"
                if not os.path.exists(dev):
                    continue
                # 使用 VideoWorker 中的 Linux 打开逻辑进行测试
                tmp_cap = self.worker._open_camera_linux(dev)
                if tmp_cap and tmp_cap.isOpened():
                    ret, _ = tmp_cap.read()
                    if ret:
                        valid.append(dev)
                    tmp_cap.release()
                else:
                    if tmp_cap:
                        tmp_cap.release()
            self.available_cams = valid
            self.ui.cam_selector.addItems([os.path.basename(d) for d in valid])

        self.ui.cam_selector.blockSignals(False)

    def change_camera(self, index):
        if index >= 0 and index < len(self.available_cams):
            cam_ref = self.available_cams[index]
            self.worker.update_camera(cam_ref)

    def save_snapshot(self, prefix):
        path = os.path.join(os.getcwd(), "records")
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, f"{prefix}_{time.strftime('%H%M%S')}.jpg")
        if self.ui.video_label.pixmap():
            self.ui.video_label.pixmap().save(file_path)
            self.add_log(f"已保存: {os.path.basename(file_path)}")

    def open_folder(self):
        path = os.path.join(os.getcwd(), "records")
        if not os.path.exists(path):
            os.makedirs(path)

        if self.os_type=='Windows':
            os.startfile(path)
        elif self.os_type == 'Darwin': #MacOS
            subprocess.run(['open', path])
        else:  #Linux
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
