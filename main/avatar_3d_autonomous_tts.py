import sys
import random
import threading
import queue
from PyQt5.QtWidgets import QApplication, QMainWindow, QOpenGLWidget, QPushButton, QLabel, QLineEdit
from PyQt5.QtCore import Qt, QTimer
from OpenGL.GL import *
from OpenGL.GLU import *
import pyttsx3
import numpy as np

class TTSThread(threading.Thread):
    def __init__(self, tts_queue):
        super().__init__()
        self.tts_queue = tts_queue
        self.engine = pyttsx3.init()
        self.daemon = True
        self.running = True

    def run(self):
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.1)
                if text:
                    self.engine.say(text)
                    self.engine.runAndWait()
            except queue.Empty:
                continue

class AutonomousAvatarViewer(QOpenGLWidget):
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

    def start_autonomous(self):
        self.is_autonomous = True
        self.mode = 'run'
        self.ticks = 0
        self.direction = random.uniform(0, 360)
        self.talk_text = ''
        self.comment_text = ''

    def stop_autonomous(self):
        self.is_autonomous = False
        self.mode = 'idle'
        self.talk_text = ''
        self.comment_text = ''
        self.update()

    def speak_comment(self, comment):
        self.comment_text = comment
        self.mode = 'comment'
        self.ticks = 0
        if self.tts_queue:
            self.tts_queue.put(comment)

    def update_autonomous(self):
        if not self.is_autonomous:
            return
        self.ticks += 1
        if self.mode == 'run':
            # 駆け回る
            speed = 0.03
            self.position[0] += speed * np.cos(np.radians(self.direction))
            self.position[1] += speed * np.sin(np.radians(self.direction))
            # ランダムに方向転換
            if random.random() < 0.05:
                self.direction += random.uniform(-60, 60)
            if self.ticks > 60 + random.randint(0, 40):  # 3秒程度
                self.mode = 'rest'
                self.ticks = 0
        elif self.mode == 'rest':
            # 休憩
            if self.ticks == 1:
                self.talk_text = random.choice(['ふう…ちょっと休憩。', 'すこし止まります。'])
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'talk'
                self.ticks = 0
        elif self.mode == 'talk':
            # お話し
            if self.ticks == 1:
                self.talk_text = random.choice(self.talks)
                if self.tts_queue:
                    self.tts_queue.put(self.talk_text)
            if self.ticks > 40 + random.randint(0, 20):  # 2秒程度
                self.mode = 'run'
                self.direction = random.uniform(0, 360)
                self.ticks = 0
                self.talk_text = ''
        elif self.mode == 'comment':
            # コメント読み上げ中
            if self.ticks > 60:  # 3秒表示
                self.mode = 'run'
                self.comment_text = ''
                self.talk_text = ''
                self.ticks = 0
        self.update()

    def initializeGL(self):
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glEnable(GL_DEPTH_TEST)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45.0, float(w)/float(h), 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        glTranslatef(self.position[0], self.position[1], -5.0)
        glColor3f(0.6, 0.8, 1.0)
        quad = gluNewQuadric()
        gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow):
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
