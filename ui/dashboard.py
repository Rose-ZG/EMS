# dashboard.py
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon

class MainDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        # 全局样式 - 现代暗色主题
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', 'PingFang SC', sans-serif;
            }
            QLabel {
                font-size: 14px;
            }
            QPushButton {
                background-color: #313244;
                border: none;
                padding: 10px 16px;
                border-radius: 8px;
                min-height: 32px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
            QPushButton:pressed {
                background-color: #585b70;
            }
            QPushButton#action_btn {
                background-color: #89b4fa;
                color: #11111b;
            }
            QPushButton#action_btn:hover {
                background-color: #b4befe;
            }
            QComboBox {
                background: #313244;
                border: 1px solid #45475a;
                padding: 6px 8px;
                border-radius: 6px;
                min-height: 30px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #313244;
                selection-background-color: #45475a;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #313244;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #89b4fa;
                border-radius: 8px;
                width: 18px;
                margin: -6px 0;
            }
            QGroupBox {
                border: 2px solid #45475a;
                margin-top: 20px;
                font-weight: bold;
                padding-top: 15px;
                border-radius: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                color: #f5e0dc;
            }
            QTextEdit {
                background: #181825;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11pt;
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(24)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # --- 左侧视频区 ---
        left_container = QVBoxLayout()
        left_container.setSpacing(12)

        # 顶部工具栏
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        top_bar.addWidget(QLabel("📹"))
        top_bar.addWidget(QLabel("监控源选择:"))
        self.cam_selector = QComboBox()
        top_bar.addWidget(self.cam_selector, 1)
        self.ref_btn = QPushButton("🔄 刷新设备")
        top_bar.addWidget(self.ref_btn)
        left_container.addLayout(top_bar)

        # 视频渲染区
        self.video_label = QLabel("等待摄像头连接...")
        self.video_label.setFixedSize(640, 480)
        self.video_label.setStyleSheet("""
            background-color: #0f0f15;
            border: 3px solid #89b4fa;
            border-radius: 16px;
            color: #6c7086;
            font-size: 18px;
        """)
        self.video_label.setAlignment(Qt.AlignCenter)
        left_container.addWidget(self.video_label, 0, Qt.AlignCenter)

        # 底部状态栏
        info_bar = QHBoxLayout()
        info_bar.setSpacing(16)
        self.fps_label = QLabel("FPS: 0.0")
        self.fps_label.setStyleSheet("color: #a6adc8; font-weight: bold;")
        self.snap_btn = QPushButton("📷 抓拍记录")
        self.open_btn = QPushButton("📁 记录回溯")
        info_bar.addWidget(self.fps_label)
        info_bar.addStretch()
        info_bar.addWidget(self.snap_btn)
        info_bar.addWidget(self.open_btn)
        left_container.addLayout(info_bar)

        main_layout.addLayout(left_container, 5)

        # --- 右侧控制区 ---
        right_container = QVBoxLayout()
        right_container.setSpacing(18)

        # 状态指示灯区域
        self.status_label = QLabel("🟢 系统实时监控中")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            font-size: 20pt;
            font-weight: bold;
            color: #11111b;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #a6e3a1, stop:1 #94e2d5);
            border-radius: 14px;
            padding: 14px;
        """)
        right_container.addWidget(self.status_label)

        # 参数调节面板
        self.cfg_group = QGroupBox("⚙️ AI 模型参数动态调优")
        cfg_lay = QVBoxLayout(self.cfg_group)
        cfg_lay.setSpacing(16)

        cfg_lay.addWidget(QLabel("跌倒判定灵敏度:"))
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(30, 90)
        self.t_slider.setValue(60)
        self.t_slider.setTickPosition(QSlider.TicksBelow)
        self.t_slider.setTickInterval(10)
        cfg_lay.addWidget(self.t_slider)

        cfg_lay.addWidget(QLabel("AI 检测置信度阈值:"))
        self.c_slider = QSlider(Qt.Horizontal)
        self.c_slider.setRange(10, 90)
        self.c_slider.setValue(50)
        self.c_slider.setTickPosition(QSlider.TicksBelow)
        self.c_slider.setTickInterval(10)
        cfg_lay.addWidget(self.c_slider)
        right_container.addWidget(self.cfg_group)

        # 日志输出
        log_label = QLabel("📋 系统运行日志:")
        right_container.addWidget(log_label)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        right_container.addWidget(self.log_box)

        # 复位按钮
        self.reset_btn = QPushButton("🚨 警报解除 / 硬件初始化")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setStyleSheet("""
            QPushButton#reset_btn {
                height: 60px;
                background: #f38ba8;
                color: #11111b;
                font-weight: bold;
                font-size: 16pt;
                border-radius: 12px;
            }
            QPushButton#reset_btn:hover {
                background: #fab387;
            }
        """)
        right_container.addWidget(self.reset_btn)

        main_layout.addLayout(right_container, 3)

    def append_log(self, message):
        """添加日志并自动滚动到底部"""
        self.log_box.append(message)
        self.log_box.verticalScrollBar().setValue(
            self.log_box.verticalScrollBar().maximum()
        )