"""
カメラトラッキングサンプル (MediaPipe FaceMesh)

pip install opencv-python mediapipe で利用可能になります。
"""
try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore
try:
    import mediapipe as mp
except ImportError:
    mp = None  # type: ignore


def run_tracking():
    """Webcam face mesh tracking loop."""
    if cv2 is None or mp is None:
        print("cv2 / mediapipe が未インストールです: pip install opencv-python mediapipe")
        return

    mp_face_mesh = mp.solutions.face_mesh
    mp_drawing = mp.solutions.drawing_utils

    cap = cv2.VideoCapture(0)
    try:
        with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as face_mesh:
            while cap.isOpened():
                success, image = cap.read()
                if not success:
                    break
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(image)
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                if results.multi_face_landmarks:
                    for face_landmarks in results.multi_face_landmarks:
                        mp_drawing.draw_landmarks(
                            image=image,
                            landmark_list=face_landmarks,
                            connections=mp_face_mesh.FACEMESH_TESSELATION,
                            landmark_drawing_spec=None,
                            connection_drawing_spec=mp_drawing.DrawingSpec(
                                color=(0, 255, 0), thickness=1, circle_radius=1
                            ),
                        )
                cv2.imshow("Webcam FaceMesh", image)
                if cv2.waitKey(5) & 0xFF == 27:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_tracking()
