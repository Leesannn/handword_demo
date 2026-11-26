"""Preserve raw hand results independently of handedness and review on video."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6),
         (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17),
         (0, 17), (17, 18), (18, 19), (19, 20)]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def finite_or_null(value):
    value = float(value)
    return value if math.isfinite(value) else None


def pack_result(result, index, timestamp):
    detections = []
    for i, landmarks in enumerate(result.hand_landmarks):
        categories = result.handedness[i] if i < len(result.handedness) else []
        detections.append({
            'detection_index': i,
            'categories': [{'name': c.category_name, 'score': finite_or_null(c.score)} for c in categories],
            'landmarks': [[finite_or_null(p.x), finite_or_null(p.y), finite_or_null(p.z)] for p in landmarks],
        })
    names = [d['categories'][0]['name'] for d in detections if d['categories']]
    return {'frame_number': index + 1, 'timestamp_ms': timestamp,
            'detections': detections,
            'duplicate_labels': [name for name, count in Counter(names).items() if count > 1]}


def extract(video, model, output):
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    identity = {'video_sha256': digest(video), 'hand_model_sha256': digest(model)}
    if output.exists():
        saved = json.loads(output.read_text(encoding='utf-8'))
        if saved.get('schema_version') != 'raw-hand-review-v1' or any(saved.get(k) != v for k, v in identity.items()):
            raise ValueError(f'기존 진단 결과와 원본/모델이 다릅니다: {output}')
        if not saved.get('frames') or len(saved['frames']) != saved['summary']['frame_count']:
            raise ValueError('기존 진단 파일의 프레임 수가 올바르지 않습니다.')
        print(f'기존 원시 진단 결과 재사용: {output}')
        return saved
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise RuntimeError(f'영상을 열 수 없습니다: {video}')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or not 0 < fps <= 1000:
            raise ValueError('영상 FPS를 확인하세요.')
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=model.read_bytes()),
            running_mode=vision.RunningMode.VIDEO, num_hands=2)
        frames = []
        with vision.HandLandmarker.create_from_options(options) as detector:
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                index = len(frames)
                timestamp = round(index * 1000 / fps)
                rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                frames.append(pack_result(result, index, timestamp))
                if len(frames) % 30 == 0:
                    print(f'원시 검출 처리: {len(frames)}프레임', flush=True)
        if not frames or (expected > 0 and len(frames) != expected):
            raise RuntimeError(f'영상 읽기 상태 확인 필요: 읽은 프레임 {len(frames)}, 메타데이터 {expected}. 저장하지 않습니다.')
        saved = {
            'schema_version': 'raw-hand-review-v1', 'source_video': str(video), **identity,
            'fps': fps, 'timestamp_basis': 'frame_index / metadata fps; assumes constant frame rate',
            'mirrored_by_script': False, 'mediapipe_version': mp.__version__, 'opencv_version': cv2.__version__,
            'note': 'Detection indices are per-frame positions, NOT persistent identities or anatomical left/right.',
            'summary': {'frame_count': len(frames),
                        'raw_zero_detection_frames': sum(not f['detections'] for f in frames),
                        'raw_two_detection_frames': sum(len(f['detections']) == 2 for f in frames),
                        'duplicate_label_frames': sum(bool(f['duplicate_labels']) for f in frames)},
            'frames': frames,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(saved, stream, ensure_ascii=False, indent=2, allow_nan=False)
        reread = json.loads(output.read_text(encoding='utf-8'))
        if reread != saved:
            raise RuntimeError('저장 후 다시 읽기 검증 실패')
        return saved
    finally:
        cap.release()


def review(video, saved, start):
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    frames = saved['frames']
    if not 1 <= start <= len(frames):
        cap.release()
        raise ValueError('시작 프레임이 영상 범위를 벗어납니다.')
    index, cached_index, cached = start - 1, -1, None
    playing = False
    window = 'Raw hand review - indices are NOT identities'
    try:
        if not cap.isOpened():
            raise RuntimeError('원본 영상을 다시 열 수 없습니다.')
        while True:
            if index != cached_index:
                if cached is None or index != cached_index + 1:
                    if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                        raise RuntimeError('프레임 이동을 지원하지 않습니다.')
                ok, image = cap.read()
                if not ok:
                    raise RuntimeError(f'{index + 1}프레임 읽기 실패')
                scale = min(960 / image.shape[1], 640 / image.shape[0], 1.0)
                cached = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)))
                cached_index = index
            image = cached.copy()
            h, w = image.shape[:2]
            frame = frames[index]
            descriptions = []
            for detection in frame['detections']:
                i = detection['detection_index']
                color = (255, 220, 0) if i == 0 else (0, 180, 255)
                points = detection['landmarks']
                category = detection['categories'][0] if detection['categories'] else None
                descriptions.append(f'D{i}: ' + (f"{category['name']} ({category['score']})" if category else 'no label'))
                pixels = [None if p[0] is None or p[1] is None or not (0 <= p[0] <= 1 and 0 <= p[1] <= 1)
                          else (round(p[0] * (w - 1)), round(p[1] * (h - 1))) for p in points]
                for a, b in EDGES:
                    if a < len(pixels) and b < len(pixels) and pixels[a] is not None and pixels[b] is not None:
                        cv2.line(image, pixels[a], pixels[b], color, 2)
                for p in pixels:
                    if p is not None:
                        cv2.circle(image, p, 3, color, -1)
                if pixels and pixels[0] is not None:
                    cv2.putText(image, f'D{i}', pixels[0], cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            canvas = np.zeros((h + 150, max(800, w), 3), dtype=np.uint8)
            canvas[150:, :w] = image
            lines = [f'{"PLAY" if playing else "PAUSE"} | Frame {index + 1}/{len(frames)} | raw detections: {len(frame["detections"])}',
                     ' | '.join(descriptions) or 'No hand detections',
                     'D0 cyan / D1 orange: indices may switch between frames',
                     'SPACE: play/pause | A/D: step | R: first | Q: quit',
                     'C: next duplicate-label frame | N: next zero-detection frame']
            for row, line in enumerate(lines):
                cv2.putText(canvas, line, (10, 24 + 28 * row), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(max(1, round(1000 / saved['fps'])) if playing else 30) & 0xFF
            if key in (ord('q'), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord(' '):
                playing = not playing
            elif key in (ord('a'), ord('d')):
                index = max(0, min(len(frames) - 1, index + (1 if key == ord('d') else -1)))
                playing = False
            elif key == ord('r'):
                index, playing = 0, False
            elif key in (ord('c'), ord('n')):
                candidates = [i for i, f in enumerate(frames) if (bool(f['duplicate_labels']) if key == ord('c') else not f['detections'])]
                later = [i for i in candidates if i > index]
                if candidates:
                    index = later[0] if later else candidates[0]
                else:
                    print('해당 프레임이 없습니다.')
                playing = False
            elif playing:
                index = min(index + 1, len(frames) - 1)
                if index == len(frames) - 1:
                    playing = False
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--start', type=int, default=30)
    parser.add_argument('--no-preview', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    video = args.video.resolve()
    if not video.is_file():
        raise FileNotFoundError(video)
    output = root / 'ksl_data' / 'raw_hand_diagnostics' / video.parent.name / f'{video.stem}.json'
    saved = extract(video, root / 'models' / 'hand_landmarker.task', output)
    print(json.dumps(saved['summary'], ensure_ascii=False, indent=2))
    print(f'원시 진단 저장: {output}')
    print('기존 177개 좌표 파일과 단어 라벨은 변경하지 않았습니다.')
    if not args.no_preview:
        review(video, saved, args.start)


if __name__ == '__main__':
    main()
