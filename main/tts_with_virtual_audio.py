import sys
import queue
import threading
import sounddevice as sd
import numpy as np
import pyttsx3
import tempfile
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QLineEdit, QLabel, QComboBox
from PyQt5.QtCore import QTimer
from scipy.io import wavfile
from pydub import AudioSegment

# 仮想オーディオデバイス一覧取得
AUDIO_DEVICES = sd.query_devices()
OUTPUT_DEVICES = [d for d in AUDIO_DEVICES if d['max_output_channels'] > 0]

def list_output_devices():
    return [(i, d['name']) for i, d in enumerate(AUDIO_DEVICES) if d['max_output_channels'] > 0]

# TTS音声をwavファイルで生成
class TTSWorker(threading.Thread):
    def __init__(self, tts_queue, device_idx_getter):
        super().__init__()
        self.tts_queue = tts_queue
        self.device_idx_getter = device_idx_getter
        self.daemon = True
        self.engine = pyttsx3.init()
        self.running = True

    def run(self):
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.1)
                if text:
                    # 一時wavファイルにTTS出力
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tf:
                        self.engine.save_to_file(text, tf.name)
                        self.engine.runAndWait()
                        tf_path = tf.name
                    # wavを指定デバイスで再生
                    self.play_wav_on_device(tf_path, self.device_idx_getter())
                    os.unlink(tf_path)
            except queue.Empty:
                continue

    def play_wav_on_device(self, wav_path, device_idx):
        # pydubで読み込み
        audio = AudioSegment.from_wav(wav_path)
        samples = np.array(audio.get_array_of_samples())
        samples = samples.astype(np.float32) / (2**15)
        sd.play(samples, audio.frame_rate, device=device_idx)
        sd.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TTS仮想オーディオデバイス出力サンプル")
        self.tts_queue = queue.Queue()
        self.device_idx = 0
        self.device_list = list_output_devices()
        self.device_box = QComboBox(self)
        for idx, name in self.device_list:
            self.device_box.addItem(name, idx)
        self.device_box.setGeometry(10, 10, 350, 30)
        self.device_box.currentIndexChanged.connect(self.select_device)
        self.input = QLineEdit(self)
        self.input.setGeometry(10, 50, 350, 30)
        self.input.setPlaceholderText('コメントを入力してEnterで読み上げ')
        self.input.returnPressed.connect(self.handle_comment)
        self.status = QLabel('出力先: ' + self.device_list[0][1], self)
        self.status.setGeometry(10, 90, 350, 30)
        self.tts_worker = TTSWorker(self.tts_queue, self.get_device_idx)
        self.tts_worker.start()

    def select_device(self):
        idx = self.device_box.currentIndex()
        self.device_idx = self.device_list[idx][0]
        self.status.setText('出力先: ' + self.device_list[idx][1])

    def get_device_idx(self):
        return self.device_idx

    def handle_comment(self):
        comment = self.input.text().strip()
        if comment:
            self.tts_queue.put(comment)
            self.input.clear()

    def closeEvent(self, event):
        self.tts_worker.running = False
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
