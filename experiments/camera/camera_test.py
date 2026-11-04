import cv2


def check_camera():
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Не удалось открыть камеру. Проверьте доступ к камере в настройках macOS.")
        camera.release()
        return

    print("Камера открыта. Нажмите Q в окне камеры, чтобы выйти.")
    try:
        while True:
            success, frame = camera.read()
            if not success:
                print("Не удалось получить изображение с камеры.")
                break
            cv2.imshow("DOTA MAGIC - camera test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    check_camera()
