"""Replay saved hand coordinates on a blank canvas, without opening a camera."""

import argparse
import json
import math
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parent
CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]


def load_sequence(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "hand-sequence-1":
        raise ValueError("지원하지 않는 파일 형식입니다. sequence_*.json 파일을 선택하세요.")
    frames = data.get("frames", [])
    if not frames:
        raise ValueError("저장된 프레임이 없습니다.")
    previous = -1.0
    for frame in frames:
        timestamp = frame["relative_ms"]
        if not math.isfinite(timestamp) or timestamp <= previous:
            raise ValueError("프레임 시각이 올바르게 증가하지 않습니다.")
        previous = timestamp
        for side in ("Left", "Right"):
            hand = frame["hands"][side]
            if hand["present"]:
                points = hand["landmarks"]
                if len(points) != 21 or any(
                    len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points
                ):
                    raise ValueError("관절 좌표가 21개 x 3개 숫자 형식이 아닙니다.")
    return data


def main():
    import cv2
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="Optional JSON path; defaults to newest sequence")
    args = parser.parse_args()
    if args.file:
        path = Path(args.file).resolve()
    else:
        files = list((ROOT.parent / '04_데이터' / "sequences").glob("sequence_*.json"))
        if not files:
            print("sequences 폴더에 파일이 없습니다. 먼저 연속 좌표를 기록하세요.")
            return
        path = max(files, key=lambda p: p.stat().st_mtime)
    try:
        data = load_sequence(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"파일 읽기 실패: {error}")
        return

    frames = data["frames"]
    source_width = data["image"]["width"]
    source_height = data["image"]["height"]
    if source_width <= 0 or source_height <= 0:
        print("이미지 크기가 올바르지 않습니다.")
        return
    scale = min(960 / source_width, 640 / source_height)
    width = max(1, round(source_width * scale))
    height = max(1, round(source_height * scale))
    header = 100
    window = "Replay Coordinates - No Camera"
    colors = {"Left": (255, 220, 0), "Right": (0, 180, 255)}
    print(f"재생 파일: {path}")
    print(f"저장된 프레임: {len(frames)} / 손 좌표만 재생하며 사진과 영상은 사용하지 않습니다.")
    print("SPACE: 일시정지/재개 / R: 처음부터 / Q 또는 ESC: 종료")
    print("좌우 표시는 모델의 예측입니다. 실제 좌우 손이 맞는지는 직접 확인해야 합니다.")

    index = 0
    paused = False
    origin = time.perf_counter() - frames[0]["relative_ms"] / 1000
    paused_at = None
    try:
        while True:
            now = time.perf_counter()
            if not paused:
                elapsed_ms = (now - origin) * 1000
                while index + 1 < len(frames) and frames[index + 1]["relative_ms"] <= elapsed_ms:
                    index += 1

            frame = frames[index]
            canvas = np.zeros((height + header, width, 3), dtype=np.uint8)
            for side, color in colors.items():
                hand = frame["hands"][side]
                if not hand["present"]:
                    continue
                points = [(round(x * width), round(y * height) + header) for x, y, z in hand["landmarks"]]
                # Clip drawing to the image panel, keeping original JSON values untouched.
                panel = canvas[header:]
                local = [(x, y - header) for x, y in points]
                for a, b in CONNECTIONS:
                    cv2.line(panel, local[a], local[b], color, 2)
                for point in local:
                    cv2.circle(panel, point, 4, color, -1)
                x, y = local[0]
                cv2.putText(panel, side, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            status = "PAUSED" if paused else ("END - R to replay" if index == len(frames) - 1 else "PLAYING")
            lines = [
                f"{status} | Frame {index + 1}/{len(frames)} | {frame['relative_ms'] / 1000:.2f}s",
                "SPACE: pause/resume | R: restart | Q: quit",
                f"Left: {'present' if frame['hands']['Left']['present'] else 'missing'} | Right: {'present' if frame['hands']['Right']['present'] else 'missing'}",
            ]
            for row, text in enumerate(lines):
                cv2.putText(canvas, text, (10, 24 + row * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(10) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                index = 0
                origin = time.perf_counter() - frames[0]["relative_ms"] / 1000
                paused = False
            elif key == 32:
                if paused:
                    origin += time.perf_counter() - paused_at
                    paused = False
                else:
                    paused_at = time.perf_counter()
                    paused = True
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
