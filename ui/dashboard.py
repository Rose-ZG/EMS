from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon


class MainDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        # 全局暗色调样式
        self.setStyleSheet("""
            QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', 'PingFang SC'; }
            QLabel { font-size: 14px; }
            QPushButton { 
                background-color: #313244; border: none; padding: 8px 15px; border-radius: 5px; 
                min-height: 30px; font-weight: bold;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton#action_btn { background-color: #89b4fa; color: #11111b; }
            QComboBox { background: #313244; border: 1px solid #45475a; padding: 5px; border-radius: 4px; }
            QSlider::handle:horizontal { background: #89b4fa; border-radius: 5px; width: 18px; }
            QGroupBox { border: 2px solid #45475a; margin-top: 15px; font-weight: bold; padding: 10px; border-radius: 8px; }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # --- 左侧视频区 ---
        left_container = QVBoxLayout()

        # 顶部工具栏
        top_bar = QHBoxLayout()
        cam_icon = QLabel("📹")  # 辅助图标
        top_bar.addWidget(cam_icon)
        top_bar.addWidget(QLabel("监控源选择:"))
        self.cam_selector = QComboBox()
        top_bar.addWidget(self.cam_selector, 1)
        self.ref_btn = QPushButton("刷新设备")
        top_bar.addWidget(self.ref_btn)
        left_container.addLayout(top_bar)

        # 视频渲染区
        self.video_label = QLabel("正在初始化 AI 推理引擎...")
        self.video_label.setFixedSize(640, 480)
        # 优化视频框视觉
        self.video_label.setStyleSheet("""
            background: #000; border: 2px solid #89b4fa; border-radius: 12px;
        """)
        self.video_label.setAlignment(Qt.AlignCenter)
        left_container.addWidget(self.video_label)

        # 底部状态栏
        info_bar = QHBoxLayout()
        self.fps_label = QLabel("帧率: 0.0 FPS")
        self.fps_label.setStyleSheet("color: #a6adc8; font-weight: bold;")
        self.snap_btn = QPushButton("📷 抓拍记录")
        self.open_btn = QPushButton("📁 记录回溯")
        info_bar.addWidget(self.fps_label)
        info_bar.addStretch()
        info_bar.addWidget(self.snap_btn)
        info_bar.addWidget(self.open_btn)
        left_container.addLayout(info_bar)

        main_layout.addLayout(left_container, 6)

        # --- 右侧控制区 ---
        right_container = QVBoxLayout()

        # 状态指示灯区域
        self.status_label = QLabel("系统实时监控中")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            font-size: 18pt; color: #11111b; background: #a6e3a1; 
            border-radius: 10px; padding: 10px; margin-bottom: 10px;
        """)
        right_container.addWidget(self.status_label)

        # 参数调节面板
        self.cfg_group = QGroupBox("AI 模型参数动态调优")
        cfg_lay = QVBoxLayout(self.cfg_group)

        cfg_lay.addWidget(QLabel("跌倒判定灵敏度:"))
        self.t_slider = QSlider(Qt.Horizontal)
        self.t_slider.setRange(30, 90)
        self.t_slider.setValue(60)
        cfg_lay.addWidget(self.t_slider)

        cfg_lay.addWidget(QLabel("AI 检测置信度阈值:"))
        self.c_slider = QSlider(Qt.Horizontal)
        self.c_slider.setRange(10, 90)
        self.c_slider.setValue(50)
        cfg_lay.addWidget(self.c_slider)
        right_container.addWidget(self.cfg_group)

        # 日志输出
        log_label = QLabel("🚀 系统运行日志:")
        right_container.addWidget(log_label)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            background: #11111b; color: #f5e0dc; border: 1px solid #45475a;
            font-family: 'Consolas'; font-size: 10pt; border-radius: 5px;
        """)
        right_container.addWidget(self.log_box)

        # 复位按钮
        self.reset_btn = QPushButton("警报解除 / 硬件初始化")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setStyleSheet("""
            height: 55px; background: #f38ba8; color: #11111b; 
            font-weight: bold; font-size: 14pt; border-radius: 8px;
        """)
        right_container.addWidget(self.reset_btn)

        main_layout.addLayout(right_container, 4)