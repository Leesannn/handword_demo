"""Review existing coordinates over the original video without changing data."""
import argparse
import json
from pathlib import Path
from project_paths import resolve_saved_path

HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6),
              (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
              (9, 13), (13, 14), (14, 15), (15, 16), (13, 17),
              (0, 17), (17, 18), (18, 19), (19, 20)]
POSE_EDGES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


def ranges(flags):
    result = []
    start = None
    for index, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            result.append((start, index - 1))
            start = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinates', type=Path, required=True)
    parser.add_argument('--video', type=Path, help='Override original video location')
    args = parser.parse_args()
    import cv2
    import numpy as np

    path = args.coordinates.resolve()
    meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    with np.load(path, allow_pickle=False) as data:
        coords = data['coordinates'].copy()
        valid = data['landmark_valid'].copy()
        times = data['timestamps_seconds'].copy()
    n = len(coords)
    if not n or coords.shape != (n, 177) or valid.shape != (n, 59) or times.shape != (n,):
        raise ValueError('배열 크기가 예상한 원시 좌표 형식과 다릅니다.')
    if not np.isfinite(times).all() or (np.diff(times) <= 0).any():
        raise ValueError('프레임 시각이 올바르지 않습니다.')
    if not np.array_equal(valid, np.isfinite(coords.reshape(n, 59, 3)).all(axis=2)):
        raise ValueError('좌표와 검출 마스크가 일치하지 않습니다.')
    left = valid[:, :21].all(axis=1)
    right = valid[:, 21:42].all(axis=1)
    missing_either = ~left | ~right
    missing_both = ~left & ~right
    for name, flags in [('왼손 좌표 없음', ~left), ('오른손 좌표 없음', ~right),
                        ('양손 좌표 모두 없음', missing_both)]:
        print(f'\n{name}: {int(flags.sum())}/{n} 프레임')
        for start, end in ranges(flags):
            print(f'  프레임 {start + 1}~{end + 1} / {times[start]:.3f}~{times[end]:.3f}초 (프레임 시각)')
    print('\nN: 다음 한쪽 이상 미검출 구간 / B: 다음 양손 미검출 구간')
    print('A/D: 이전/다음 프레임 / SPACE: 재생/정지 / R: 처음 / Q: 종료')
    print('손 좌우는 저장된 MediaPipe 분류입니다. 충돌 발생 프레임 번호는 기존 파일에 없어 특정할 수 없습니다.')

    video = args.video.resolve() if args.video else resolve_saved_path(meta['source_video'])
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise RuntimeError(f'원본 영상을 열 수 없습니다: {video}')
        fps = float(meta['fps_from_metadata'])
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError('저장된 FPS가 올바르지 않습니다.')
        index, cached_index = 0, -1
        playing = False
        cached_frame = None
        window = 'KSL coordinate review'
        while True:
            if index != cached_index:
                # Sequential playback reads sequentially; jumps seek to a frame.
                if index != cached_index + 1 or cached_frame is None:
                    if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                        raise RuntimeError('이 영상의 프레임 이동을 지원하지 않습니다.')
                ok, bgr = cap.read()
                if not ok:
                    raise RuntimeError(f'{index + 1}번째 프레임을 읽지 못했습니다.')
                scale = min(960 / bgr.shape[1], 640 / bgr.shape[0], 1.0)
                cached_frame = cv2.resize(bgr, (round(bgr.shape[1] * scale), round(bgr.shape[0] * scale)))
                cached_index = index
            image = cached_frame.copy()
            height, width = image.shape[:2]
            points = coords[index].reshape(59, 3)

            def pixel(k):
                if not valid[index, k] or not (0 <= points[k, 0] <= 1 and 0 <= points[k, 1] <= 1):
                    return None
                return (round(float(points[k, 0]) * (width - 1)),
                        round(float(points[k, 1]) * (height - 1)))

            for offset, count, edges, color in [
                (42, 17, POSE_EDGES, (80, 220, 80)),
                (0, 21, HAND_EDGES, (255, 220, 0)),
                (21, 21, HAND_EDGES, (0, 180, 255)),
            ]:
                for a, b in edges:
                    p, q = pixel(offset + a), pixel(offset + b)
                    if p is not None and q is not None:
                        cv2.line(image, p, q, color, 2)
                for k in range(offset, offset + count):
                    p = pixel(k)
                    if p is not None:
                        cv2.circle(image, p, 3, color, -1)
            # Header outside the source image keeps coordinates aligned.
            canvas = np.zeros((height + 125, max(width, 720), 3), dtype=np.uint8)
            canvas[125:, :width] = image
            lines = [
                f'{"PLAY" if playing else "PAUSE"} | Frame {index + 1}/{n} | {times[index]:.3f}s',
                f'Left(cyan): {"present" if left[index] else "MISSING"} | Right(orange): {"present" if right[index] else "MISSING"}',
                'SPACE: play/pause | A/D: step | R: restart | Q: quit',
                'N: next missing-hand interval | B: next both-missing interval',
            ]
            for row, line in enumerate(lines):
                cv2.putText(canvas, line, (10, 25 + row * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(max(1, round(1000 / fps)) if playing else 30) & 0xFF
            if key in (ord('q'), 27):
                break
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord(' '):
                playing = not playing
            elif key in (ord('a'), ord('d')):
                index = max(0, min(n - 1, index + (1 if key == ord('d') else -1)))
                playing = False
            elif key == ord('r'):
                index, playing = 0, False
            elif key in (ord('n'), ord('b')):
                flags = missing_either if key == ord('n') else missing_both
                starts = [start for start, end in ranges(flags)]
                later = [start for start in starts if start > index]
                if starts:
                    index = later[0] if later else starts[0]
                else:
                    print('해당 미검출 구간이 없습니다.')
                playing = False
            elif playing:
                if index < n - 1:
                    index += 1
                else:
                    playing = False
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
