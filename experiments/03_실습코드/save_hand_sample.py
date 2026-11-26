"""Press S to save one hand-landmark snapshot; Q to quit."""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


ROOT = Path(__file__).resolve().parent
CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]


def save_snapshot(result, width, height, timestamp_ms):
    if not result.hand_landmarks:
        print("저장하지 않았습니다: 손이 검출되지 않았습니다.")
        return None

    hands = {
        "Left": {"present": False, "landmarks": None},
        "Right": {"present": False, "landmarks": None},
    }
    outside_count = 0

    for landmarks, categories in zip(result.hand_landmarks, result.handedness):
        if not categories or len(landmarks) != 21:
            print("저장하지 않았습니다: 관절 또는 좌우 손 정보가 불완전합니다.")
            return None

        category = categories[0]
        side = category.category_name
        if side not in hands or hands[side]["present"]:
            print("저장하지 않았습니다: 좌우 손 구분이 불명확합니다. 다시 시도하세요.")
            return None

        coordinates = [[float(p.x), float(p.y), float(p.z)] for p in landmarks]
        outside_count += sum(
            not (0 <= x <= 1 and 0 <= y <= 1) for x, y, z in coordinates
        )
        hands[side] = {
            "present": True,
            "handedness_score": float(category.score),
            "landmarks": coordinates,
        }

    sample_id = str(uuid4())
    payload = {
        "schema_version": "hand-snapshot-1",
        "sample_id": sample_id,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "frame_timestamp_ms": timestamp_ms,
        "image": {"width": width, "height": height, "mirrored_by_script": False},
        "coordinate_space": "mediapipe_image_landmarks",
        "coordinate_order": ["x", "y", "z"],
        "hand_count": sum(hand["present"] for hand in hands.values()),
        "hands": hands,
        "quality": {"xy_outside_image_count": outside_count},
        "mediapipe_version": mp.__version__,
    }
    output_dir = ROOT.parent / '04_데이터' / "samples"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"hand_{sample_id}.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"저장 완료: {output_path}")
    print(f"검출 손: {payload['hand_count']}개 / 화면 범위 밖 관절: {outside_count}개")
    return output_path


def main():
    model_path = ROOT.parent / '04_데이터' / "models" / "hand_landmarker.task"
    if not model_path.is_file():
        print(f"모델 파일이 없습니다: {model_path}")
        return

    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model_path.read_bytes()),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )
    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            print("웹캠을 열지 못했습니다. 다른 카메라 창을 종료하세요.")
            return

        start_time = time.perf_counter()
        last_timestamp = -1
        saved_count = 0
        with vision.HandLandmarker.create_from_options(options) as detector:
            print("카메라 창을 선택하고 영문 S: 좌표 1장 저장 / Q: 종료")
            print("사진과 영상은 저장하지 않습니다. 이번 파일은 수어 학습용 시퀀스가 아닙니다.")
            while True:
                success, frame = camera.read()
                if not success:
                    print("카메라 화면을 읽지 못했습니다.")
                    break

                timestamp = max(int((time.perf_counter() - start_time) * 1000), last_timestamp + 1)
                last_timestamp = timestamp
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp
                )
                height, width = frame.shape[:2]
                for landmarks in result.hand_landmarks:
                    points = [(int(p.x * width), int(p.y * height)) for p in landmarks]
                    for a, b in CONNECTIONS:
                        cv2.line(frame, points[a], points[b], (0, 255, 0), 2)
                    for point in points:
                        cv2.circle(frame, point, 4, (0, 0, 255), -1)

                cv2.putText(
                    frame, f"Hands: {len(result.hand_landmarks)} | S: save | Q: quit | Saved: {saved_count}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2,
                )
                cv2.imshow("Save Hand Coordinates", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("s"), ord("S")):
                    if save_snapshot(result, width, height, timestamp) is not None:
                        saved_count += 1
                elif key in (ord("q"), ord("Q")):
                    break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
