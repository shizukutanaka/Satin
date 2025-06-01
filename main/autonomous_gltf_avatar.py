import sys
import random
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, QOpenGLWidget, QFileDialog, QPushButton, QLabel
from PyQt5.QtCore import Qt, QTimer
from OpenGL.GL import *
from OpenGL.GLU import *
import pygltflib
import os

class GLTFModel:
    def __init__(self, filename):
        self.filename = filename
        self.vertices = []
        self.faces = []
        self.animations = []
        self.current_animation = 0
        self.current_time = 0.0
        self.load_gltf()

    def load_gltf(self):
        # 頂点・面・アニメーションの簡易ローダー
        gltf = pygltflib.GLTF2().load(self.filename)
        if not gltf.meshes:
            return
        mesh = gltf.meshes[0]
        accessor = gltf.accessors[mesh.primitives[0].attributes.POSITION]
        buffer_view = gltf.bufferViews[accessor.bufferView]
        buffer = gltf.buffers[buffer_view.buffer]
        data = np.frombuffer(buffer.data, dtype=np.float32)
        self.vertices = data.reshape(-1, 3)
        if mesh.primitives[0].indices is not None:
            idx_accessor = gltf.accessors[mesh.primitives[0].indices]
            idx_buffer_view = gltf.bufferViews[idx_accessor.bufferView]
            idx_buffer = gltf.buffers[idx_buffer_view.buffer]
            idx_data = np.frombuffer(idx_buffer.data, dtype=np.uint16)
            self.faces = idx_data.reshape(-1, 3)
        else:
            self.faces = np.arange(len(self.vertices)).reshape(-1, 3)
        # アニメーション情報の読み込み（超簡易: channel/keyframe情報のみ）
        self.animations = []
        for anim in gltf.animations or []:
            # 位置・回転・スケールのサンプル
            channels = []
            for ch in anim.channels:
                sampler = anim.samplers[ch.sampler]
                # 入力(時間)・出力(値)
                input_acc = gltf.accessors[sampler.input]
                output_acc = gltf.accessors[sampler.output]
                input_view = gltf.bufferViews[input_acc.bufferView]
                output_view = gltf.bufferViews[output_acc.bufferView]
                input_buf = gltf.buffers[input_view.buffer]
                output_buf = gltf.buffers[output_view.buffer]
                times = np.frombuffer(input_buf.data, dtype=np.float32)
                values = np.frombuffer(output_buf.data, dtype=np.float32)
                channels.append({'target': ch.target.path, 'times': times, 'values': values, 'interpolation': sampler.interpolation})
            self.animations.append({'channels': channels})

    def advance_animation(self, dt, anim_idx=0):
        # 現在はダミー: 本格的なスキニング・ボーン変形は未対応
        self.current_time += dt
        if self.animations:
            # 最初のチャンネルの時間でループ
            times = self.animations[anim_idx]['channels'][0]['times']
            if self.current_time > times[-1]:
                self.current_time = 0.0

    def draw(self):
        if len(self.vertices) == 0 or len(self.faces) == 0:
            return
        # 本格的なアニメーション反映は未対応（今後拡張）
        glBegin(GL_TRIANGLES)
        for face in self.faces:
            for idx in face:
                v = self.vertices[idx]
                glVertex3f(v[0], v[1], v[2])
        glEnd()


class AutonomousGLTFAvatarViewer(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.mode = 'idle'  # 'run', 'rest', 'talk'
        self.position = [0.0, 0.0]
        self.direction = random.uniform(0, 360)
        self.ticks = 0
        self.talk_text = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_autonomous)
        self.timer.start(50)
        self.is_autonomous = False
        self.model = None
        self.model_angle = [0, 0]
        self.talks = [
            'こんにちは！',
            '今日はいい天気ですね。',
            'ちょっと休憩します…',
            '走るの大好き！',
            'あなたも一緒にどう？'
        ]
        self.anim_state = QLabel('', self)
        self.anim_state.setGeometry(10, 50, 400, 30)
        self.anim_state.setStyleSheet('font-size:14px; color:#444; background:#f8f8f8;')

    def load_model(self, filename):
        self.model = GLTFModel(filename)
        self.update()

    def start_autonomous(self):
        self.is_autonomous = True
        self.mode = 'run'
        self.ticks = 0
        self.direction = random.uniform(0, 360)
        self.talk_text = ''

    def stop_autonomous(self):
        self.is_autonomous = False
        self.mode = 'idle'
        self.talk_text = ''
        self.update()

    def update_autonomous(self):
        if not self.is_autonomous:
            return
        self.ticks += 1
        # 状態ごとにアニメーションを進める
        if self.model and self.model.animations:
            if self.mode == 'run':
                self.model.current_animation = 0
            elif self.mode == 'rest':
                self.model.current_animation = 1 if len(self.model.animations) > 1 else 0
            elif self.mode == 'talk':
                self.model.current_animation = 2 if len(self.model.animations) > 2 else 0
            self.model.advance_animation(0.05, self.model.current_animation)
        if self.mode == 'run':
            # 駆け回る
            speed = 0.03
            self.position[0] += speed * np.cos(np.radians(self.direction))
            self.position[1] += speed * np.sin(np.radians(self.direction))
            # 画面端で反射
            for i in range(2):
                if abs(self.position[i]) > 1.2:
                    self.direction += 180
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
            if self.ticks == 1:
                self.talk_text = random.choice(self.talks)
            if self.ticks > 40 + random.randint(0, 20):
                self.mode = 'run'
                self.talk_text = ''
                self.ticks = 0
        # UIアニメーション状態表示
        if self.model and self.model.animations:
            anim_name = ['歩行','待機','トーク']
            idx = self.model.current_animation
            self.anim_state.setText(f"アニメーション: {anim_name[idx] if idx < len(anim_name) else 'その他'}")
        else:
            self.anim_state.setText('アニメーション: なし')
        self.update()

    def initializeGL(self):
        glClearColor(0.8, 0.9, 1.0, 1.0)
        glEnable(GL_DEPTH_TEST)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, w / h if h != 0 else 1, 0.1, 100)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        # カメラ位置
        gluLookAt(0, 1.5, 4, 0, 0, 0, 0, 1, 0)
        # アバターの位置・向き
        glTranslatef(self.position[0], 0, self.position[1])
        glRotatef(-self.direction, 0, 1, 0)
        glScalef(1.0, 1.0, 1.0)
        if self.model:
            self.model.draw()
        # 吹き出しテキスト
        if self.talk_text:
            self.renderText(0, 2.0, 0, self.talk_text)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自律3Dアバター(GLTF)ビューア")
        self.viewer = AutonomousGLTFAvatarViewer(self)
        self.setCentralWidget(self.viewer)
        self.load_btn = QPushButton("GLTFモデルを読み込み", self)
        self.load_btn.setGeometry(10, 10, 180, 30)
        self.load_btn.clicked.connect(self.open_gltf)
        self.autonomous_btn = QPushButton('自律モードON', self)
        self.autonomous_btn.setGeometry(200, 10, 120, 30)
        self.autonomous_btn.clicked.connect(self.toggle_autonomous)
        self.talk_label = QLabel('', self)
        self.talk_label.setGeometry(340, 10, 400, 30)
        self.talk_label.setStyleSheet('font-size:18px; color:#222; background:#eee;')
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self.update_talk_text)
        self.text_timer.start(100)

    def open_gltf(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'GLTFファイルを選択', '', 'GLTF Files (*.gltf *.glb)')
        if fname:
            self.viewer.load_model(fname)

    def toggle_autonomous(self):
        if not self.viewer.is_autonomous:
            self.viewer.start_autonomous()
            self.autonomous_btn.setText('自律モードOFF')
        else:
            self.viewer.stop_autonomous()
            self.autonomous_btn.setText('自律モードON')

    def update_talk_text(self):
        self.talk_label.setText(self.viewer.talk_text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(900, 600)
    win.show()
    sys.exit(app.exec_())
