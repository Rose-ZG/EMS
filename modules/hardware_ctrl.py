import serial
import serial.tools.list_ports
import os
import threading
import platform

class HardwareManager:
    def __init__(self, port=None, baudrate=9600, mp3_path="RING.wav"):
        self.available = False
        self.ser = None
        self.mp3_path = mp3_path          # 默认报警音
        self.os_type = platform.system()

        pygame_imported = False
        try:
            import pygame
            pygame.mixer.init()
            self.pygame = pygame
            pygame_imported = True
            print("[HW] pygame 音频初始化成功")
        except Exception as e:
            print(f"[HW] pygame 音频初始化失败: {e}")
        self.pygame_imported = pygame_imported

        if port is None:
            port = self._auto_detect_serial()
        if port:
            try:
                self.ser = serial.Serial(port, baudrate, timeout=0.1, write_timeout=0.1)
                self.available = True
                print(f"[HW] 串口连接成功 ({port})")
            except Exception as e:
                print(f"[HW] 串口连接失败: {e}")
        else:
            print("[HW] 未找到可用串口设备")

    def _auto_detect_serial(self):
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if "Bluetooth" not in p.description:
                return p.device
        if self.os_type == "Linux":
            for dev in ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyS0"]:
                if os.path.exists(dev):
                    return dev
        return None

    def send_alarm(self, active=True):
        if self.ser and self.available:
            try:
                msg = b'1' if active else b'0'
                self.ser.write(msg)
                return True
            except Exception as e:
                print(f"[HW] 串口发送失败: {e}")
        return False

    def _play_mp3_async(self, repeat=2):
        """播放默认报警音（内部使用）"""
        self._play_audio_async(self.mp3_path, repeat)

    def _play_audio_async(self, file_path, repeat=1):
        """通用音频播放（异步）"""
        if not self.pygame_imported:
            print("[HW] pygame 未可用，无法播放音频")
            return
        def play():
            try:
                self.pygame.mixer.music.stop()
                self.pygame.mixer.music.load(file_path)
                for i in range(repeat):
                    print(f"[HW] 播放音频 ({i+1}/{repeat}): {file_path}")
                    self.pygame.mixer.music.play()
                    while self.pygame.mixer.music.get_busy():
                        self.pygame.time.delay(100)
                print("[HW] 音频播放结束")
            except Exception as e:
                print(f"[HW] 音频播放失败: {e}")
        threading.Thread(target=play, daemon=True).start()

    def play_audio(self, file_path, repeat=1):
        """供外部调用的音频播放接口"""
        if os.path.exists(file_path):
            print(f"[HW] 请求播放音频: {file_path}")
            self._play_audio_async(file_path, repeat)
            return True
        else:
            print(f"[HW] 音频文件未找到: {file_path}")
            return False

    def alert_with_voice(self, active=True):
        serial_ok = self.send_alarm(active)
        if active:
            if os.path.exists(self.mp3_path):
                self._play_mp3_async(repeat=2)
            else:
                print(f"[HW] 报警音频未找到: {self.mp3_path}")
        else:
            if self.pygame_imported:
                self.pygame.mixer.music.stop()
        print(f"[HW] 报警触发: 串口={serial_ok}")

    def close(self):
        if self.pygame_imported:
            self.pygame.mixer.quit()
        if self.ser:
            self.ser.close()