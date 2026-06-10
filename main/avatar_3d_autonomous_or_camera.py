import sys
import random
import threading
import queue

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)
from camera_thread import CameraThread  # noqa: E402
from gl_widget_base import GLViewportMixin  # noqa: E402

try:
    from persona import get_persona  # noqa: E402
except Exception:  # pragma: no cover - defensive
    get_persona = None

class Avatar3DAutoOrCamViewer(GLViewportMixin, QOpenGLWidget if QOpenGLWidget is not None else object):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.mode = 'autonomous'  # 'autonomous' or 'camera'
        # --- autonomous ---
        self.position = [0.0, 0.0]
        self.direction = random.uniform(0, 360)
        self.ticks = 0
        self.talk_text = ''
        self.talks = [
            'こんにちは！',
            '今日はいい天気ですね。',
            'ちょっと休憩します…',
            '走るの大好き！',
            'あなたも一緒にどう？'
        ]
        # --- camera ---
        self.pose_queue = queue.Queue()
        self.cam_thread = None
        self.current_pose = None
        # --- timer ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(50)

    def _pick_rest_text(self):
        """休憩台詞。ペルソナ優先、無ければハードコード配列にフォールバック。"""
        if get_persona is not None:
            text = get_persona().rest()
            if text:
                return text
        return random.choice(['ふう…ちょっと休憩。', 'すこし止まります。'])

    def _pick_talk_text(self):
        """雑談台詞。ペルソナ優先、無ければ self.talks にフォールバック。"""
        if get_persona is not None:
            text = get_persona().talk()
            if text:
                return text
        return random.choice(self.talks)

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        if mode == 'camera':
            self.start_camera()
        else:
            self.stop_camera()
            self.reset_autonomous()
        self.update()

    def start_camera(self):
        if self.cam_thread is None or not self.cam_thread.is_alive():
            self.pose_queue = queue.Queue()
            self.cam_thread = CameraThread(self.pose_queue)
            self.cam_thread.start()

    def stop_camera(self):
        if self.cam_thread:
            self.cam_thread.running = False
            self.cam_thread = None
        self.current_pose = None

    def reset_autonomous(self):
        self.position = [0.0, 0.0]
        self.direction = random.uniform(0, 360)
        self.ticks = 0
        self.talk_text = ''

    def update_logic(self):
        if self.mode == 'autonomous':
            self.update_autonomous()
        elif self.mode == 'camera':
            self.update_camera()
        self.update()

    def update_autonomous(self):
        self.ticks += 1
        if self.ticks < 60:
            # 駆け回る
            speed = 0.03
            if np is not None:
                self.position[0] += speed * np.cos(np.radians(self.direction))
                self.position[1] += speed * np.sin(np.radians(self.direction))
            if random.random() < 0.05:
                self.direction += random.uniform(-60, 60)
        elif self.ticks < 100:
            # 休憩
            self.talk_text = self._pick_rest_text()
        elif self.ticks < 140:
            # お話し
            self.talk_text = self._pick_talk_text()
        else:
            self.ticks = 0
            self.talk_text = ''

    def update_camera(self):
        try:
            while True:
                pose = self.pose_queue.get_nowait()
                if pose:
                    self.current_pose = pose
        except queue.Empty:
            pass

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        if self.mode == 'autonomous':
            glTranslatef(self.position[0], self.position[1], -5.0)
            glColor3f(0.6, 0.8, 1.0)
            quad = gluNewQuadric()
            gluSphere(quad, 1.0, 32, 32)
            if self.talk_text:
                # OpenGLでテキスト描画は難しいので、PyQt側でラベル表示
                pass
        elif self.mode == 'camera':
            glTranslatef(0.0, 0.0, -5.0)
            # 顔の向きを反映
            if self.current_pose:
                nose_x, nose_y, lx, ly, rx, ry = self.current_pose
                dx = (lx + rx)/2 - nose_x
                dy = ((ly + ry)/2 - nose_y)
                glRotatef(dx * 200, 0, 1, 0)
                glRotatef(dy * 200, 1, 0, 0)
            glColor3f(0.6, 0.8, 1.0)
            quad = gluNewQuadric()
            gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3Dアバター：自律モード/カメラ連動切り替え")
        self.viewer = Avatar3DAutoOrCamViewer(self)
        self.setCentralWidget(self.viewer)
        self.auto_btn = QPushButton('自律モード', self)
        self.auto_btn.setGeometry(10, 10, 120, 30)
        self.auto_btn.clicked.connect(self.set_auto_mode)
        self.cam_btn = QPushButton('カメラ連動', self)
        self.cam_btn.setGeometry(140, 10, 120, 30)
        self.cam_btn.clicked.connect(self.set_cam_mode)
        self.status_label = QLabel('モード: 自律', self)
        self.status_label.setGeometry(280, 10, 300, 30)
        self.status_label.setStyleSheet('font-size:16px; color:#222; background:#eee;')
        self.talk_label = QLabel('', self)
        self.talk_label.setGeometry(10, 50, 600, 30)
        self.talk_label.setStyleSheet('font-size:18px; color:#222; background:#eee;')
        # テキスト更新タイマー
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self.update_talk_text)
        self.text_timer.start(100)

    def set_auto_mode(self):
        self.viewer.set_mode('autonomous')
        self.status_label.setText('モード: 自律')

    def set_cam_mode(self):
        self.viewer.set_mode('camera')
        self.status_label.setText('モード: カメラ連動')

    def update_talk_text(self):
        if self.viewer.mode == 'autonomous' and self.viewer.talk_text:
            self.talk_label.setText(self.viewer.talk_text)
        else:
            self.talk_label.setText('')

    def closeEvent(self, event):
        self.viewer.stop_camera()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
