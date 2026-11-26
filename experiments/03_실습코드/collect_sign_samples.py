"""Labelled collection: SPACE to prepare for 3 s, then record coordinates.

No images are written. Use --inspect to read the latest sequence JSON.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
PREPARE_SECONDS = 3.0
RECORD_SECONDS = 3.0
WORD_ID = None
WORD_LABEL = None
PERSON_ID = None
SESSION_ID = None
WORDS = {"hello": "안녕하세요", "thanks": "고맙습니다"}


def sample_folder():
    return ROOT / "dataset" / WORD_ID / PERSON_ID / SESSION_ID

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]


def pack_hands(result):
    hands = {side: {"present": False, "landmarks": None} for side in ("Left", "Right")}
    issues = []
    seen = set()
    if len(result.hand_landmarks) != len(result.handedness):
        return hands, ["result_length_mismatch"]
    for points, categories in zip(result.hand_landmarks, result.handedness):
        if not categories or len(points) != 21:
            issues.append("incomplete_hand")
            continue
        category = categories[0]
        side = category.category_name
        if side not in hands:
            issues.append("unknown_handedness")
            continue
        if side in seen:
            hands[side] = {"present": False, "landmarks": None}
            issues.append(f"ambiguous_{side}")
            continue
        seen.add(side)
        coords = [[float(p.x), float(p.y), float(p.z)] for p in points]
        if not all(math.isfinite(v) for point in coords for v in point):
            issues.append(f"nonfinite_{side}")
            continue
        hands[side] = {
            "present": True,
            "handedness_score": float(category.score),
            "landmarks": coords,
        }
    return hands, issues


def summarize(frames):
    n = len(frames)
    span_ms = frames[-1]["relative_ms"] - frames[0]["relative_ms"] if n > 1 else 0
    return {
        "frame_count": n,
        "captured_frame_span_ms": span_ms,
        "observed_processed_fps": round((n - 1) * 1000 / span_ms, 2) if span_ms > 0 else None,
        "left_present_frames": sum(f["hands"]["Left"]["present"] for f in frames),
        "right_present_frames": sum(f["hands"]["Right"]["present"] for f in frames),
        "both_present_frames": sum(all(h["present"] for h in f["hands"].values()) for f in frames),
        "no_hand_frames": sum(not any(h["present"] for h in f["hands"].values()) for f in frames),
        "frames_with_issues": sum(bool(f["issues"]) for f in frames),
        "xy_outside_image_count": sum(
            not (0 <= x <= 1 and 0 <= y <= 1)
            for f in frames for hand in f["hands"].values()
            if hand["present"] for x, y, z in hand["landmarks"]
        ),
    }


def save_sequence(frames, elapsed, width, height, model_hash, mp_version):
    if not frames:
        print("기록된 프레임이 없어 저장하지 않았습니다.")
        return None
    sample_id = str(uuid4())
    payload = {
        "schema_version": "hand-sequence-1",
        "collection_version": "two-sign-practice-1",
        "sample_id": sample_id,
        "label": WORD_LABEL,
        "word_id": WORD_ID,
        "person_id": PERSON_ID,
        "session_id": SESSION_ID,
        "purpose": "labelled_practice_not_yet_split",
        "split": "unassigned",
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_record_seconds": RECORD_SECONDS,
        "recording_elapsed_seconds": round(elapsed, 4),
        "timestamp_definition": "monotonic time immediately after camera.read; not sensor exposure time",
        "image": {"width": width, "height": height, "mirrored_by_script": False},
        "coordinate_space": "mediapipe_image_landmarks",
        "coordinate_order": ["x", "y", "z"],
        "hand_order": ["Left", "Right"],
        "mediapipe_version": mp_version,
        "hand_model_sha256": model_hash,
        "summary": summarize(frames),
        "frames": frames,
    }
    folder = sample_folder()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"sequence_{sample_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"\n저장 완료: {path}")
    print_summary(payload)
    return path


def print_summary(data):
    summary = data["summary"]
    n = summary["frame_count"]
    print(f"기록 프레임 수: {n}")
    print(f"실제 기록 종료까지 경과: {data['recording_elapsed_seconds']:.3f}초")
    print(f"첫~마지막 프레임 간격: {summary['captured_frame_span_ms'] / 1000:.3f}초")
    print(f"관측 처리 FPS: {summary['observed_processed_fps']}")
    for key, name in [("left_present_frames", "왼손"), ("right_present_frames", "오른손"), ("both_present_frames", "양손 동시"), ("no_hand_frames", "양손 모두 미검출")]:
        print(f"{name}: {summary[key]}/{n} 프레임")
    print(f"검출 정보 이상 프레임: {summary['frames_with_issues']}")
    print(f"화면 범위 밖 좌표 수: {summary['xy_outside_image_count']}")
    print(f"단어: {data['label']} ({data['word_id']})")
    print(f"촬영자: {data['person_id']} / 촬영 세션: {data['session_id']}")
    if summary["left_present_frames"] + summary["right_present_frames"] == 0:
        print("주의: 손이 검출된 프레임이 없습니다. 학습에 사용하지 말고 다시 촬영하세요.")
    print("라벨은 촬영자가 지정한 값입니다. 올바른 수어 수행과 학습 적합성을 자동 검증한 것은 아닙니다.")


def inspect_latest():
    files = list(sample_folder().glob("sequence_*.json"))
    if not files:
        print("저장된 시퀀스가 없습니다. 카메라 창에서 스페이스바로 먼저 기록하세요.")
        return
    path = max(files, key=lambda p: p.stat().st_mtime)
    data = json.loads(path.read_text(encoding="utf-8"))
    actual = summarize(data["frames"])
    if actual != data["summary"]:
        raise ValueError("저장된 요약과 프레임 내용이 일치하지 않습니다.")
    times = [f["relative_ms"] for f in data["frames"]]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("프레임 시각이 순서대로 증가하지 않습니다.")
    print(f"다시 읽은 파일: {path}")
    print_summary(data)


def record():
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = ROOT.parent / '04_데이터' / "models" / "hand_landmarker.task"
    if not model_path.is_file():
        print(f"모델 파일이 없습니다: {model_path}")
        return
    model_bytes = model_path.read_bytes()
    model_hash = hashlib.sha256(model_bytes).hexdigest()
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model_bytes),
        running_mode=vision.RunningMode.VIDEO, num_hands=2,
    )
    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            print("웹캠을 열지 못했습니다. 다른 카메라 창을 종료하세요.")
            return
        state = "READY"
        frames = []
        origin = time.perf_counter()
        last_timestamp = -1
        deadline = 0.0
        recording_start = 0.0
        dimensions = None
        saved_at = 0.0
        with vision.HandLandmarker.create_from_options(options) as detector:
            print(f"수집 단어: {WORD_LABEL} ({WORD_ID})")
            print(f"촬영자: {PERSON_ID} / 세션: {SESSION_ID}")
            print(f"현재 폴더 샘플 수: {len(list(sample_folder().glob('sequence_*.json')))}")
            print(f"카메라 창 클릭 → 스페이스바 → 3초 준비 → 약 {RECORD_SECONDS:g}초 자동 기록")
            print("Q: 종료. 준비/기록 중에는 스페이스바를 무시합니다.")
            print("사진·영상은 저장하지 않습니다. Q로 중단한 기록은 저장하지 않습니다.")
            while True:
                success, frame = camera.read()
                now = time.perf_counter()
                if not success:
                    print("카메라 읽기 실패. 진행 중이던 기록은 저장하지 않습니다.")
                    break
                height, width = frame.shape[:2]
                if state == "PREPARE" and now >= deadline:
                    state = "RECORDING"
                    recording_start = now
                    frames = []
                    dimensions = (width, height)
                    print("기록 시작: 양손 동작을 하세요.")
                if state == "RECORDING" and now - recording_start >= RECORD_SECONDS:
                    save_sequence(frames, now - recording_start, *dimensions, model_hash, mp.__version__)
                    state = "READY"
                    saved_at = time.perf_counter()
                if state == "RECORDING" and dimensions != (width, height):
                    print("카메라 크기가 바뀌어 기록을 취소했습니다.")
                    state = "READY"
                    frames = []

                timestamp = max(int((now - origin) * 1000), last_timestamp + 1)
                last_timestamp = timestamp
                result = detector.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), timestamp
                )
                hands, issues = pack_hands(result)
                if state == "RECORDING":
                    frames.append({"relative_ms": round((now - recording_start) * 1000, 4), "hands": hands, "issues": issues})
                for hand in hands.values():
                    if hand["present"]:
                        points = [(int(x * width), int(y * height)) for x, y, z in hand["landmarks"]]
                        for a, b in CONNECTIONS:
                            cv2.line(frame, points[a], points[b], (0, 255, 0), 2)
                        for point in points:
                            cv2.circle(frame, point, 4, (0, 0, 255), -1)
                message = f"{WORD_ID} | READY | SPACE: start | Q: quit"
                color = (0, 255, 0)
                if state == "PREPARE":
                    message = f"{WORD_ID} | GET READY: {max(1, math.ceil(deadline - now))}"
                    color = (0, 255, 255)
                elif state == "RECORDING":
                    message = f"{WORD_ID} | RECORDING: {max(0, RECORD_SECONDS - (now - recording_start)):.1f}s | Frames: {len(frames)}"
                    color = (0, 0, 255)
                elif saved_at and time.perf_counter() - saved_at < 2:
                    message = f"{WORD_ID} | SAVED | SPACE: again | Q: quit"
                cv2.putText(frame, message, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
                cv2.putText(frame, f"Hands: {sum(h['present'] for h in hands.values())}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
                cv2.imshow("Record Hand Sequence", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q")):
                    if state != "READY":
                        print("준비 또는 기록을 취소했습니다. 진행 중 데이터는 저장하지 않습니다.")
                    break
                if key == 32 and state == "READY":
                    state = "PREPARE"
                    deadline = time.perf_counter() + PREPARE_SECONDS
                    print("3초 뒤 자동 기록합니다. 양손을 준비하세요.")
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="Read the latest saved sequence without opening the camera")
    parser.add_argument("--word", choices=WORDS, required=True, help="hello or thanks")
    parser.add_argument("--person", required=True, help="Pseudonymous performer ID, e.g. p01")
    parser.add_argument("--session", required=True, help="Capture session ID, e.g. s01")
    parser.add_argument("--seconds", type=float, default=3.0, help="Recording duration between 0.5 and 3 seconds")
    args = parser.parse_args()
    for name, value in [("person", args.person), ("session", args.session)]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", value):
            parser.error(f"--{name}: use 1-48 English letters, numbers, underscore or hyphen")
    if not 0.5 <= args.seconds <= 3.0:
        parser.error("--seconds must be between 0.5 and 3.0")
    WORD_ID = args.word
    WORD_LABEL = WORDS[WORD_ID]
    PERSON_ID = args.person
    SESSION_ID = args.session
    RECORD_SECONDS = args.seconds
    if args.inspect:
        inspect_latest()
    else:
        record()
