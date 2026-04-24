import serial
import serial.tools.list_ports
import os
import threading
import platform

class HardwareManager:
    def __init__(self, port=None, baudrate=9600, mp3_path="RING.wav",
                 twilio_sid=None, twilio_token=None, twilio_from=None):
        self.available = False
        self.ser = None
        self.mp3_path = mp3_path
        self.os_type = platform.system()

        # Twilio 配置（可选）
        self.twilio_sid = twilio_sid
        self.twilio_token = twilio_token
        self.twilio_from = twilio_from
        self.twilio_enabled = all([twilio_sid, twilio_token, twilio_from])

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

    def _play_audio_async(self, file_path, repeat=1):
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
        if os.path.exists(file_path):
            self._play_audio_async(file_path, repeat)
        else:
            print(f"[HW] 音频文件未找到: {file_path}")

    def alert_with_voice(self, active=True):
        serial_ok = self.send_alarm(active)
        if active:
            if os.path.exists(self.mp3_path):
                self._play_audio_async(self.mp3_path, repeat=2)
            else:
                print(f"[HW] 报警音频未找到: {self.mp3_path}")
        else:
            if self.pygame_imported:
                self.pygame.mixer.music.stop()
        print(f"[HW] 报警触发: 串口={serial_ok}")

    def call_emergency(self, to_number):
        """拨打紧急联系人，如果配置了 Twilio 则真实拨打，否则模拟"""
        if self.twilio_enabled:
            try:
                from twilio.rest import Client
                client = Client(self.twilio_sid, self.twilio_token)
                call = client.calls.create(
                    url="http://demo.twilio.com/docs/voice.xml",
                    to=to_number,
                    from_=self.twilio_from
                )
                print(f"[HW] 呼叫 {to_number} 成功，SID: {call.sid}")
                return True
            except Exception as e:
                print(f"[HW] Twilio 呼叫失败: {e}")
                return False
        else:
            print(f"[HW] 模拟呼叫 {to_number}")
            return True

    def close(self):
        if self.pygame_imported:
            self.pygame.mixer.quit()
        if self.ser:
            self.ser.close()