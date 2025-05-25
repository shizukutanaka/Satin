import sys
import threading
import queue
import numpy as np
import cv2
import mediapipe as mp
from PyQt5.QtWidgets import QApplication, QMainWindow, QOpenGLWidget
from PyQt5.QtCore import Qt, QTimer
from OpenGL.GL import *
from OpenGL.GLU import *

# --- MediaPipe FaceMesh Setup ---
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
                    # 例: 鼻先・左右目・口の3点座標抽出
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

class Avatar3DSyncViewer(QOpenGLWidget):
    def __init__(self, pose_queue, parent=None):
        super().__init__(parent)
        self.pose_queue = pose_queue
        self.current_pose = None
        self.setMinimumSize(640, 480)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_pose)
        self.timer.start(30)

    def update_pose(self):
        try:
            while True:
                pose = self.pose_queue.get_nowait()
                if pose:
                    self.current_pose = pose
        except queue.Empty:
            pass
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
        glTranslatef(0.0, 0.0, -5.0)
        # 3Dモデルの仮表示（球体）
        glColor3f(0.6, 0.8, 1.0)
        quad = gluNewQuadric()
        gluSphere(quad, 1.0, 32, 32)
        # 顔の向きをposeから反映（例: 鼻・目の位置で回転）
        if self.current_pose:
            nose_x, nose_y, lx, ly, rx, ry = self.current_pose
            dx = (lx + rx)/2 - nose_x
            dy = ((ly + ry)/2 - nose_y)
            glRotatef(dx * 200, 0, 1, 0)
            glRotatef(dy * 200, 1, 0, 0)

class MainWindow(QMainWindow):
    def __init__(self, pose_queue):
        super().__init__()
        self.setWindowTitle("3Dアバター同期ビューア（カメラ連動サンプル）")
        self.viewer = Avatar3DSyncViewer(pose_queue, self)
        self.setCentralWidget(self.viewer)

if __name__ == "__main__":
    pose_queue = queue.Queue()
    cam_thread = CameraThread(pose_queue)
    cam_thread.start()
    app = QApplication(sys.argv)
    win = MainWindow(pose_queue)
    win.show()
    app.exec_()
    cam_thread.running = False
    cam_thread.join()
