from pathlib import Path
import math
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


def fingers_touch(hand, width, height):
    def distance(a, b):
        return math.hypot((hand[a].x - hand[b].x) * width,
                          (hand[a].y - hand[b].y) * height)

    palm_size = distance(0, 9)
    return palm_size > 1 and distance(4, 8) / palm_size < 0.35


def main():
    model = Path(__file__).parent / "models" / "hand_landmarker.task"
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Не удалось открыть камеру. Проверьте разрешения macOS.")
        camera.release()
        return

    try:
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            print("Покажите руку камере. Для выхода нажмите Q в окне видео.")
            last_timestamp = -1
            touch_since = None
            while True:
                success, frame = camera.read()
                if not success:
                    print("Не удалось получить кадр с камеры.")
                    break
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                timestamp = max(time.monotonic_ns() // 1_000_000, last_timestamp + 1)
                last_timestamp = timestamp
                result = landmarker.detect_for_video(image, timestamp)
                height, width = frame.shape[:2]
                touching = any(fingers_touch(hand, width, height) for hand in result.hand_landmarks)
                if touching:
                    if touch_since is None:
                        touch_since = time.monotonic()
                    if time.monotonic() - touch_since >= 0.3:
                        cv2.putText(frame, "FINGERS TOGETHER", (20, 50),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 100), 2, cv2.LINE_AA)
                else:
                    touch_since = None
                for hand in result.hand_landmarks:
                    points = [(int(p.x * width), int(p.y * height)) for p in hand]
                    for connection in vision.HandLandmarksConnections.HAND_CONNECTIONS:
                        cv2.line(frame, points[connection.start], points[connection.end], (0, 220, 0), 2)
                    for point in points:
                        cv2.circle(frame, point, 4, (0, 100, 255), -1)
                cv2.imshow("DOTA MAGIC - hand tracking", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
