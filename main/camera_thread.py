"""
共有 CameraThread — FaceMesh ポーズ推定をバックグラウンドスレッドで実行。

avatar_3d_sync / avatar_3d_gltf_viewer / avatar_3d_autonomous_or_camera が
同一実装を重複して持っていたため、このモジュールに一本化した。
"""
from __future__ import annotations

import threading
from typing import Optional

try:
    import cv2 as cv2
except ImportError:
    cv2 = None  # type: ignore

try:
    import mediapipe as mp
    mp_face_mesh = mp.solutions.face_mesh
    mp_drawing = mp.solutions.drawing_utils
except ImportError:
    mp = None  # type: ignore
    mp_face_mesh = None  # type: ignore
    mp_drawing = None  # type: ignore


class CameraThread(threading.Thread):
    """WebCam から顔ランドマーク座標を取得し pose_queue へ送り込む。

    cv2 または mediapipe が未インストールの場合は即座に返る(no-op)。
    """

    def __init__(self, pose_queue: "queue.Queue") -> None:  # noqa: F821
        super().__init__(daemon=True)
        self.pose_queue = pose_queue
        self.running = True

    def run(self) -> None:
        if cv2 is None or mp_face_mesh is None:
            return
        cap = cv2.VideoCapture(0)
        try:
            with mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            ) as face_mesh:
                while self.running and cap.isOpened():
                    success, image = cap.read()
                    if not success:
                        continue
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    results = face_mesh.process(image_rgb)
                    pose: Optional[tuple] = None
                    if results.multi_face_landmarks:
                        face_landmarks = results.multi_face_landmarks[0]
                        nose = face_landmarks.landmark[1]
                        left_eye = face_landmarks.landmark[33]
                        right_eye = face_landmarks.landmark[263]
                        pose = (
                            nose.x, nose.y,
                            left_eye.x, left_eye.y,
                            right_eye.x, right_eye.y,
                        )
                    self.pose_queue.put(pose)
                    # オーバーレイ表示（顔検出時のみ — 未検出時は face_landmarks が
                    # 未定義で NameError になるためガードが必要）
                    if results.multi_face_landmarks:
                        mp_drawing.draw_landmarks(
                            image, face_landmarks, mp_face_mesh.FACEMESH_TESSELATION
                        )
                    cv2.imshow("Webcam FaceMesh", image)
                    if cv2.waitKey(1) & 0xFF == 27:
                        self.running = False
                        break
        finally:
            cap.release()
            cv2.destroyAllWindows()

    def stop(self) -> None:
        self.running = False
