import sys
import queue
import threading
import tempfile
import os

from optional_deps import (  # noqa: E402
    np, sd, pyttsx3,
    QApplication, QMainWindow, QLineEdit, QLabel, QComboBox,
)
try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None  # type: ignore

# 仮想オーディオデバイス一覧取得 (sounddevice が使えない場合は空リスト)
if sd is not None:
    AUDIO_DEVICES = sd.query_devices()
    OUTPUT_DEVICES = [d for d in AUDIO_DEVICES if d['max_output_channels'] > 0]
else:
    AUDIO_DEVICES = []
    OUTPUT_DEVICES = []

def list_output_devices():
    return [(i, d['name']) for i, d in enumerate(AUDIO_DEVICES) if d['max_output_channels'] > 0]

# TTS音声をwavファイルで生成
class TTSWorker(threading.Thread):
    def __init__(self, tts_queue, device_idx_getter):
        super().__init__()
        self.tts_queue = tts_queue
        self.device_idx_getter = device_idx_getter
        self.daemon = True
        self.engine = pyttsx3.init() if pyttsx3 is not None else None
        self.running = True

    def run(self):
        if self.engine is None:
            return
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if text:
                tf_path = None
                try:
                    # NamedTemporaryFile を with で保持したまま pyttsx3 へ書かせると、
                    # Windows では「別プロセスが既に開いているファイル」へ書き込めず
                    # (PermissionError / 共有違反) save_to_file が黙って失敗する。
                    # ファイル名だけ確保して即座に閉じ、pyttsx3 に書き込ませる。
                    tf = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                    tf_path = tf.name
                    tf.close()
                    self.engine.save_to_file(text, tf_path)
                    self.engine.runAndWait()
                    self.play_wav_on_device(tf_path, self.device_idx_getter())
                except Exception:
                    pass
                finally:
                    if tf_path and os.path.exists(tf_path):
                        try:
                            os.unlink(tf_path)
                        except OSError:
                            pass

    def play_wav_on_device(self, wav_path, device_idx):
        if AudioSegment is None or np is None or sd is None:
            return
        # pydubで読み込み
        audio = AudioSegment.from_wav(wav_path)
        samples = np.array(audio.get_array_of_samples())
        samples = samples.astype(np.float32) / (2**15)
        sd.play(samples, audio.frame_rate, device=device_idx)
        sd.wait()

class MainWindow(QMainWindow if QMainWindow is not None else object):
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
        initial_device = self.device_list[0][1] if self.device_list else '(デバイスなし)'
        self.status = QLabel('出力先: ' + initial_device, self)
        self.status.setGeometry(10, 90, 350, 30)
        self.tts_worker = TTSWorker(self.tts_queue, self.get_device_idx)
        self.tts_worker.start()

    def select_device(self):
        idx = self.device_box.currentIndex()
        if idx < 0 or idx >= len(self.device_list):
            return
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
