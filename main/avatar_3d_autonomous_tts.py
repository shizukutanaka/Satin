import sys
import random
import threading
import queue

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)
from autonomous_behavior import AutonomousBehaviorMixin  # noqa: E402
from tts_thread import TTSThread  # noqa: E402,F401
from gl_widget_base import GLViewportMixin  # noqa: E402

try:
    from conversation_log import get_conversation_log  # noqa: E402
except Exception:  # pragma: no cover - defensive
    get_conversation_log = None

class AutonomousAvatarViewer(AutonomousBehaviorMixin, GLViewportMixin, QOpenGLWidget if QOpenGLWidget is not None else object):
    reset_direction_on_run = True
    EXTRA_TEXT_FIELDS = ('comment_text',)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.mode = 'idle'  # 'run', 'rest', 'talk', 'comment'
        self.position = [0.0, 0.0]
        self.direction = random.uniform(0, 360)
        self.ticks = 0
        self.talk_text = ''
        self.comment_text = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_autonomous)
        self.timer.start(50)
        self.is_autonomous = False
        self.talks = [
            'こんにちは！',
            '今日はいい天気ですね。',
            'ちょっと休憩します…',
            '走るの大好き！',
            'あなたも一緒にどう？'
        ]
        self.tts_queue = None

    def set_tts_queue(self, tts_queue):
        self.tts_queue = tts_queue

    def speak_comment(self, comment):
        # ペルソナが応答を返せばそれを表示・読み上げ、無ければ入力をそのまま
        # 読み上げる（後方互換のオウム返し）。respond の失敗で TTS は壊さない。
        reply = comment
        persona = self.persona
        if persona is not None:
            try:
                generated = persona.respond(comment)
            except Exception:
                generated = ""
            if generated:
                reply = generated
        # 会話履歴を記録（失敗しても UI/TTS を壊さない）
        if get_conversation_log is not None:
            try:
                get_conversation_log().log_exchange(comment, reply)
            except Exception:
                pass
        self.comment_text = reply
        self.mode = 'comment'
        self.ticks = 0
        if self.tts_queue:
            self.tts_queue.put(reply)

    def _on_talk_start(self, text):
        if self.tts_queue:
            self.tts_queue.put(text)

    def update_autonomous(self):
        if not self.is_autonomous:
            return
        if self.mode == 'comment':
            # コメント読み上げ中
            self.ticks += 1
            if self.ticks > 60:  # 3秒表示
                self.mode = 'run'
                self.comment_text = ''
                self.talk_text = ''
                self.ticks = 0
        else:
            self._advance_autonomous_state()
        self.update()

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(self.position[0], self.position[1], -5.0)
        glColor3f(0.6, 0.8, 1.0)
        quad = gluNewQuadric()
        gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自律モード＋コメント読み上げ 3Dアバター")
        self.tts_queue = queue.Queue()
        self.tts_thread = TTSThread(self.tts_queue)
        self.tts_thread.start()
        self.viewer = AutonomousAvatarViewer(self)
        self.viewer.set_tts_queue(self.tts_queue)
        self.setCentralWidget(self.viewer)
        self.autonomous_btn = QPushButton('自律モードON', self)
        self.autonomous_btn.setGeometry(10, 10, 120, 30)
        self.autonomous_btn.clicked.connect(self.toggle_autonomous)
        self.talk_label = QLabel('', self)
        self.talk_label.setGeometry(150, 10, 400, 30)
        self.talk_label.setStyleSheet('font-size:18px; color:#222; background:#eee;')
        self.comment_input = QLineEdit(self)
        self.comment_input.setGeometry(10, 50, 400, 30)
        self.comment_input.setPlaceholderText('コメントを入力してEnterで読み上げ')
        self.comment_input.returnPressed.connect(self.handle_comment)
        # テキスト更新タイマー
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self.update_talk_text)
        self.text_timer.start(100)

    def toggle_autonomous(self):
        if not self.viewer.is_autonomous:
            self.viewer.start_autonomous()
            self.autonomous_btn.setText('自律モードOFF')
        else:
            self.viewer.stop_autonomous()
            self.autonomous_btn.setText('自律モードON')
            self.talk_label.setText('')

    def update_talk_text(self):
        if self.viewer.comment_text:
            self.talk_label.setText(self.viewer.comment_text)
        elif self.viewer.talk_text:
            self.talk_label.setText(self.viewer.talk_text)
        else:
            self.talk_label.setText('')

    def handle_comment(self):
        comment = self.comment_input.text().strip()
        if comment:
            self.viewer.speak_comment(comment)
            self.comment_input.clear()

    def closeEvent(self, event):
        self.tts_thread.running = False
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
