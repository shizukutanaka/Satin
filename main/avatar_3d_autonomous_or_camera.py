import sys
import random
import threading
import queue
import numpy as np
import cv2
import mediapipe as mp
from PyQt5.QtWidgets import QApplication, QMainWindow, QOpenGLWidget, QPushButton, QLabel
from PyQt5.QtCore import Qt, QTimer
from OpenGL.GL import *
from OpenGL.GLU import *

# --- Camera tracking thread ---
mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils

class CameraThread(threading.Thread):
    def __init__(self, pose_queue):
        super().__init__()
        self.pose_queue = pose_queue
        self.running = True

    def run(self):
        cap = cv2.VideoCapture(0)
        with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as face_mesh:
            while self.running and cap.isOpened():
                success, image = cap.read()
                if not success:
                    continue
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(image_rgb)
                pose = None
                if results.multi_face_landmarks:
                    face_landmarks = results.multi_face_landmarks[0]
                    nose = face_landmarks.landmark[1]
                    left_eye = face_landmarks.landmark[33]
                    right_eye = face_landmarks.landmark[263]
                    pose = (nose.x, nose.y, left_eye.x, left_eye.y, right_eye.x, right_eye.y)
                self.pose_queue.put(pose)
                # オーバーレイ表示
                mp_drawing.draw_landmarks(image, face_landmarks, mp_face_mesh.FACEMESH_TESSELATION)
                cv2.imshow('Webcam FaceMesh', image)
                if cv2.waitKey(1) & 0xFF == 27:
                    self.running = False
                    break
        cap.release()
        cv2.destroyAllWindows()

class Avatar3DAutoOrCamViewer(QOpenGLWidget):
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
            self.position[0] += speed * np.cos(np.radians(self.direction))
            self.position[1] += speed * np.sin(np.radians(self.direction))
            if random.random() < 0.05:
                self.direction += random.uniform(-60, 60)
        elif self.ticks < 100:
            # 休憩
            self.talk_text = random.choice(['ふう…ちょっと休憩。', 'すこし止まります。'])
        elif self.ticks < 140:
            # お話し
            self.talk_text = random.choice(self.talks)
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

class MainWindow(QMainWindow):
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
