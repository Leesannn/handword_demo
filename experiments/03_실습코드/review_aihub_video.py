"""Overlay AI Hub 2D keypoints on the matching original video; read-only."""
import argparse
import json
import math
from pathlib import Path
import re

HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6),
              (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
              (9, 13), (13, 14), (14, 15), (15, 16), (13, 17),
              (0, 17), (17, 18), (18, 19), (19, 20)]
FIELDS = [('hand_left_keypoints_2d', 21, (255, 220, 0)),
          ('hand_right_keypoints_2d', 21, (0, 180, 255)),
          ('pose_keypoints_2d', 25, (80, 220, 80))]


def load_frames(folder, stem):
    pattern = re.compile(re.escape(stem) + r'_(\d+)_keypoints\.json$')
    found = []
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name)
        if path.is_file() and match:
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: item[0])
    if not found or [i for i, _ in found] != list(range(len(found))):
        raise ValueError('좌표 파일 번호가 0부터 연속인지, 영상 이름과 일치하는지 확인하세요.')
    frames = []
    for index, path in found:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        person = data['people']
        if isinstance(person, list):
            if len(person) != 1:
                raise ValueError(f'사람 수를 확인해야 합니다: {path.name}')
            person = person[0]
        for field, count, _ in FIELDS:
            values = person[field]
            if len(values) != count * 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                raise ValueError(f'2D 좌표 형식이 올바르지 않습니다: {path.name} / {field}')
        frames.append(person)
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--keypoints', type=Path, required=True)
    parser.add_argument('--start', type=int, default=1)
    args = parser.parse_args()
    frames = load_frames(args.keypoints, args.video.stem)
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(args.video.resolve()))
    try:
        if not cap.isOpened():
            raise RuntimeError(f'원본 영상을 열 수 없습니다: {args.video}')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0 or fps > 1000:
            raise ValueError('영상 FPS를 확인하세요.')
        if expected != len(frames):
            raise ValueError(f'영상 메타데이터 프레임 {expected}개 != 좌표 {len(frames)}개. 동기화를 확인해야 합니다.')
        if not 1 <= args.start <= len(frames):
            raise ValueError('시작 프레임이 범위를 벗어납니다.')
        print(f'영상/좌표: {expected}/{len(frames)}프레임 | 영상 FPS: {fps}')
        print('원본 크기:', int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'x', int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        print('가정: 좌표 번호 0을 영상 첫 프레임에 연결하며, 2D XY를 원본 픽셀 좌표로 사용합니다.')
        print('재생 창은 프레임을 1부터 표시합니다. 원본 파일은 수정하지 않습니다.')
        index, cached_index, cached = args.start - 1, -1, None
        playing, overlay = False, True
        window = 'AI Hub video + supplied 2D keypoints'
        while True:
            if index != cached_index:
                if cached is None or index != cached_index + 1:
                    if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                        raise RuntimeError('프레임 이동을 지원하지 않습니다.')
                ok, image = cap.read()
                if not ok:
                    raise RuntimeError(f'{index + 1}프레임을 읽지 못했습니다.')
                cached, cached_index = image, index
            height, width = cached.shape[:2]
            scale = min(960 / width, 640 / height, 1.0)
            image = cv2.resize(cached, (round(width * scale), round(height * scale)))
            outside = 0
            for field, count, color in FIELDS:
                points = np.asarray(frames[index][field], dtype=float).reshape(count, 3)
                pixels = []
                for x, y, confidence in points:
                    if confidence <= 0:
                        pixels.append(None)
                    elif not (0 <= x < width and 0 <= y < height):
                        outside += 1
                        pixels.append(None)
                    else:
                        pixels.append((round(x * scale), round(y * scale)))
                if not overlay:
                    continue
                if field.startswith('hand_'):
                    for a, b in HAND_EDGES:
                        if pixels[a] is not None and pixels[b] is not None:
                            cv2.line(image, pixels[a], pixels[b], color, 2)
                for p in pixels:
                    if p is not None:
                        cv2.circle(image, p, 3, color, -1)
            h, w = image.shape[:2]
            canvas = np.zeros((h + 125, max(w, 800), 3), dtype=np.uint8)
            canvas[125:, :w] = image
            lines = [f'{"PLAY" if playing else "PAUSE"} | Frame {index + 1}/{len(frames)} | video time {index / fps:.3f}s',
                     'Supplied Left: cyan | Right: orange | Pose: green dots',
                     f'Overlay: {"ON" if overlay else "OFF"} | XY outside source image: {outside}',
                     'SPACE: play/pause | A/D: step | O: overlay | R: first | Q: quit']
            for row, line in enumerate(lines):
                cv2.putText(canvas, line, (10, 24 + row * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(max(1, round(1000 / fps)) if playing else 30) & 0xFF
            if key in (ord('q'), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord(' '):
                playing = not playing
            elif key in (ord('a'), ord('d')):
                index = max(0, min(len(frames) - 1, index + (1 if key == ord('d') else -1)))
                playing = False
            elif key == ord('o'):
                overlay = not overlay
            elif key == ord('r'):
                index, playing = 0, False
            elif playing:
                if index < len(frames) - 1:
                    index += 1
                else:
                    playing = False
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
