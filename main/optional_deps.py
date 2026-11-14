"""
オプション依存パッケージの一括インポート。

各アバターモジュールが同一の try/except ImportError ブロックを
重複して持っていたため、このモジュールに集約した。
未インストールのパッケージは None として公開する。
"""
from __future__ import annotations

# ── NumPy ──────────────────────────────────────────────────────────────────
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

# ── OpenCV ─────────────────────────────────────────────────────────────────
try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore

# ── MediaPipe ──────────────────────────────────────────────────────────────
try:
    import mediapipe as _mp

    mp_face_mesh = _mp.solutions.face_mesh
    mp_drawing = _mp.solutions.drawing_utils
except Exception:
    # ImportError だけでなく AttributeError も対象: mediapipe 1.x では
    # legacy solutions API が削除され、`_mp.solutions` へのアクセス自体が
    # AttributeError になる（requirements は mediapipe>=0.10 で上限が無いため
    # 新規インストールでは 1.x が入る）。このモジュールの契約どおり、
    # 利用できない依存は None として公開し、顔トラッキングだけを無効化する。
    _mp = None  # type: ignore
    mp_face_mesh = None  # type: ignore
    mp_drawing = None  # type: ignore

# ── PyQt5 ──────────────────────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QOpenGLWidget,
        QPushButton,
    )
    from PyQt5.QtCore import Qt, QTimer
except ImportError:
    QApplication = QComboBox = QFileDialog = QLabel = QLineEdit = None  # type: ignore
    QMainWindow = QOpenGLWidget = QPushButton = Qt = QTimer = None  # type: ignore

# ── PyOpenGL ───────────────────────────────────────────────────────────────
try:
    from OpenGL.GL import *  # noqa: F401,F403
    from OpenGL.GLU import *  # noqa: F401,F403
    _OPENGL_AVAILABLE = True
except ImportError:
    _OPENGL_AVAILABLE = False

# ── pyttsx3 ────────────────────────────────────────────────────────────────
try:
    import pyttsx3
except ImportError:
    pyttsx3 = None  # type: ignore

# ── sounddevice ────────────────────────────────────────────────────────────
# sounddevice は PortAudio のシステムライブラリが無いと ImportError ではなく
# OSError を送出する（satin_launcher._check_deps と同じ理由）。このモジュール
# の契約は「未利用可能なら None」なので、OSError も欠落として扱う。
try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None  # type: ignore

# ── pygltflib ──────────────────────────────────────────────────────────────
try:
    import pygltflib
except ImportError:
    pygltflib = None  # type: ignore

__all__ = [
    "np",
    "cv2",
    "mp_face_mesh",
    "mp_drawing",
    "QApplication",
    "QComboBox",
    "QFileDialog",
    "QLabel",
    "QLineEdit",
    "QMainWindow",
    "QOpenGLWidget",
    "QPushButton",
    "Qt",
    "QTimer",
    "pyttsx3",
    "sd",
    "pygltflib",
]
