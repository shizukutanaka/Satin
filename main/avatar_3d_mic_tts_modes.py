import sys
import random
import threading
import queue

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)

# --- マイク音量取得スレッド ---
class MicVolumeThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.volume = 0.0

    def run(self):
        if np is None or sd is None:
            return

        def callback(indata, frames, time, status):
            vol = np.linalg.norm(indata) / frames
            self.volume = min(vol * 10, 1.0)  # 正規化
        with sd.InputStream(callback=callback, channels=1, samplerate=16000):
            while self.running:
                sd.sleep(50)

# --- TTSスレッド (共有実装) ---
from tts_thread import TTSThread  # noqa: E402,F401
from gl_widget_base import GLViewportMixin  # noqa: E402

class Avatar3DModesViewer(GLViewportMixin, QOpenGLWidget if QOpenGLWidget is not None else object):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.mouth_open = 0.0  # 0:閉じ 1:全開
        self.mode = 'mic'  # 'mic' or 'tts'
        self.mic_thread = None
        self.tts_thread = None
        self.tts_queue = None
        self.is_tts_speaking = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_mouth)
        self.timer.start(50)

    def set_mic_thread(self, mic_thread):
        self.mic_thread = mic_thread

    def set_tts_thread(self, tts_thread):
        self.tts_thread = tts_thread

    def set_tts_queue(self, tts_queue):
        self.tts_queue = tts_queue

    def set_mode(self, mode):
        self.mode = mode
        self.mouth_open = 0.0
        self.update()

    def tts_speak(self, text):
        if self.tts_queue:
            self.tts_queue.put(text)

    def update_mouth(self):
        if self.mode == 'mic' and self.mic_thread:
            # マイク音量に応じて口を開閉
            self.mouth_open = self.mic_thread.volume
        elif self.mode == 'tts' and self.tts_thread:
            # TTS発話中は口を開く
            self.mouth_open = 1.0 if self.tts_thread.is_speaking else 0.0
        else:
            self.mouth_open = 0.0
        self.update()

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(0.0, 0.0, -5.0)
        # 口パク付き球体（下半分をmouth_open分だけスケール）
        glColor3f(0.6, 0.8, 1.0)
        quad = gluNewQuadric()
        # 上半球
        glPushMatrix()
        glTranslatef(0, 0.5, 0)
        glScalef(1, 0.5, 1)
        gluSphere(quad, 1.0, 32, 16)
        glPopMatrix()
        # 下半球（口パク）
        glPushMatrix()
        glTranslatef(0, -0.5 + self.mouth_open*0.5, 0)
        glScalef(1, 0.5 + self.mouth_open, 1)
        gluSphere(quad, 1.0, 32, 16)
        glPopMatrix()

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3Dアバター：マイク口パク/コメントTTSモード切替")
        self.mic_thread = MicVolumeThread()
        self.mic_thread.start()
        self.tts_queue = queue.Queue()
        self.tts_thread = TTSThread(self.tts_queue)
        self.tts_thread.start()
        self.viewer = Avatar3DModesViewer(self)
        self.viewer.set_mic_thread(self.mic_thread)
        self.viewer.set_tts_thread(self.tts_thread)
        self.viewer.set_tts_queue(self.tts_queue)
        self.setCentralWidget(self.viewer)
        self.mic_btn = QPushButton('マイク口パク', self)
        self.mic_btn.setGeometry(10, 10, 120, 30)
        self.mic_btn.clicked.connect(self.set_mic_mode)
        self.tts_btn = QPushButton('コメントTTS', self)
        self.tts_btn.setGeometry(140, 10, 120, 30)
        self.tts_btn.clicked.connect(self.set_tts_mode)
        self.comment_input = QLineEdit(self)
        self.comment_input.setGeometry(10, 50, 400, 30)
        self.comment_input.setPlaceholderText('コメントを入力してEnterで読み上げ')
        self.comment_input.returnPressed.connect(self.handle_comment)
        self.comment_input.setEnabled(False)
        self.status_label = QLabel('モード: マイク口パク', self)
        self.status_label.setGeometry(280, 10, 300, 30)
        self.status_label.setStyleSheet('font-size:16px; color:#222; background:#eee;')

    def set_mic_mode(self):
        self.viewer.set_mode('mic')
        self.comment_input.setEnabled(False)
        self.status_label.setText('モード: マイク口パク')

    def set_tts_mode(self):
        self.viewer.set_mode('tts')
        self.comment_input.setEnabled(True)
        self.status_label.setText('モード: コメントTTS')

    def handle_comment(self):
        if self.viewer.mode == 'tts':
            comment = self.comment_input.text().strip()
            if comment:
                self.viewer.tts_speak(comment)
                self.comment_input.clear()

    def closeEvent(self, event):
        self.mic_thread.running = False
        self.tts_thread.running = False
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
