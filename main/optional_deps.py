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
except ImportError:
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
try:
    import sounddevice as sd
except ImportError:
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
