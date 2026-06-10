import sys
import threading
import queue

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)
from camera_thread import CameraThread  # noqa: E402

class Avatar3DSyncViewer(QOpenGLWidget if QOpenGLWidget is not None else object):
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

class MainWindow(QMainWindow if QMainWindow is not None else object):
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
