import sys
import os
import threading
import queue

from optional_deps import (  # noqa: E402
    np, cv2, QApplication, QMainWindow, QOpenGLWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, Qt, QTimer,
    pyttsx3, sd, pygltflib,
)

from camera_thread import CameraThread  # noqa: E402
from gltf_utils import load_first_mesh_vertices  # noqa: E402

class GLTFModel:
    def __init__(self, filename):
        self.filename = filename
        self.vertices = []
        self.faces = []
        self.load_gltf()

    def load_gltf(self):
        if pygltflib is None or np is None:
            return
        # シンプルなGLTF/GLB読み込み（バイナリメッシュのみ対応）
        gltf = pygltflib.GLTF2().load(self.filename)
        vertices = load_first_mesh_vertices(gltf, np)
        if vertices is None:
            return
        self.vertices = vertices
        # 顔情報は省略（サンプルではワイヤーフレームのみ）

    def draw(self):
        if len(self.vertices) == 0:
            return
        glBegin(GL_LINE_STRIP)
        for v in self.vertices:
            glVertex3f(*v)
        glEnd()

class Avatar3DGLTFViewer(QOpenGLWidget if QOpenGLWidget is not None else object):
    def __init__(self, pose_queue, parent=None):
        super().__init__(parent)
        self.pose_queue = pose_queue
        self.current_pose = None
        self.setMinimumSize(640, 480)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_pose)
        self.timer.start(30)
        self.model = None
        self.model_angle = [0, 0]

    def load_model(self, filename):
        self.model = GLTFModel(filename)
        self.update()

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
        # 顔の向きをposeから反映
        if self.current_pose:
            nose_x, nose_y, lx, ly, rx, ry = self.current_pose
            dx = (lx + rx)/2 - nose_x
            dy = ((ly + ry)/2 - nose_y)
            glRotatef(dx * 200, 0, 1, 0)
            glRotatef(dy * 200, 1, 0, 0)
        # 3Dモデル描画（なければ球体）
        if self.model:
            self.model.draw()
        else:
            glColor3f(0.6, 0.8, 1.0)
            quad = gluNewQuadric()
            gluSphere(quad, 1.0, 32, 32)

class MainWindow(QMainWindow if QMainWindow is not None else object):
    def __init__(self, pose_queue):
        super().__init__()
        self.setWindowTitle("3Dアバター(GLTF)同期ビューア")
        self.viewer = Avatar3DGLTFViewer(pose_queue, self)
        self.setCentralWidget(self.viewer)
        self.load_btn = QPushButton("GLTFモデルを読み込み", self)
        self.load_btn.clicked.connect(self.open_gltf)
        self.load_btn.setGeometry(10, 10, 180, 30)

    def open_gltf(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'GLTF/GLBファイルを選択', os.getcwd(), 'GLTF Files (*.gltf *.glb)')
        if fname:
            self.viewer.load_model(fname)

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
