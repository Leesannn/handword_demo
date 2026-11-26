from pathlib import Path
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


# 손 관절을 연결할 점 번호
CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17),
    (17, 18), (18, 19), (19, 20),
]


def main():
    model_path = (
        Path(__file__).resolve().parent.parent / '04_데이터'
        / "models"
        / "hand_landmarker.task"
    )

    if not model_path.is_file():
        print(f"모델 파일이 없습니다: {model_path}")
        return

    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_buffer=model_path.read_bytes()
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )

    camera = cv2.VideoCapture(0)

    try:
        if not camera.isOpened():
            print("웹캠을 열지 못했습니다.")
            return

        start_time = time.perf_counter()
        last_timestamp = -1
        last_print_time = start_time

        with vision.HandLandmarker.create_from_options(options) as detector:
            print("손을 카메라에 보여 주세요.")
            print("카메라 창에서 영문 q를 누르면 종료합니다.")

            while True:
                success, frame = camera.read()

                if not success:
                    print("카메라 화면을 읽지 못했습니다.")
                    break

                now = time.perf_counter()

                # VIDEO 모드는 증가하는 밀리초 시각이 필요합니다.
                timestamp = max(
                    int((now - start_time) * 1000),
                    last_timestamp + 1,
                )
                last_timestamp = timestamp

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb_frame,
                )

                result = detector.detect_for_video(image, timestamp)
                height, width = frame.shape[:2]

                for landmarks in result.hand_landmarks:
                    points = [
                        (int(point.x * width), int(point.y * height))
                        for point in landmarks
                    ]

                    for a, b in CONNECTIONS:
                        cv2.line(frame, points[a], points[b], (0, 255, 0), 2)

                    for point in points:
                        cv2.circle(frame, point, 4, (0, 0, 255), -1)

                # 터미널 출력은 약 1초 간격으로 제한합니다.
                if now - last_print_time >= 1.0:
                    if not result.hand_landmarks:
                        print("손 미검출")

                    for landmarks, handedness in zip(
                        result.hand_landmarks, result.handedness
                    ):
                        wrist = landmarks[0]
                        hand = handedness[0].category_name

                        print(
                            f"{hand} 손목: "
                            f"x={wrist.x:.3f}, "
                            f"y={wrist.y:.3f}, "
                            f"z={wrist.z:.3f}"
                        )

                    last_print_time = now

                cv2.putText(
                    frame,
                    f"Hands: {len(result.hand_landmarks)} | Q: quit",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )

                cv2.imshow("Hand Landmarker Test", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()