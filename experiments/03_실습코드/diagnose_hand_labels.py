"""Print raw handedness results; do not overwrite existing coordinates."""
import argparse
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--start', type=int, default=30, help='1-based inclusive frame')
    parser.add_argument('--end', type=int, default=39, help='1-based inclusive frame')
    args = parser.parse_args()
    if not 1 <= args.start <= args.end:
        raise ValueError('프레임 범위를 확인하세요.')
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model = Path(__file__).resolve().parent.parent / '04_데이터' / 'models' / 'hand_landmarker.task'
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=vision.RunningMode.VIDEO, num_hands=2)
    cap = cv2.VideoCapture(str(args.video.resolve()))
    try:
        if not cap.isOpened():
            raise RuntimeError('영상을 열 수 없습니다.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or not 0 < fps <= 1000:
            raise ValueError('영상 FPS를 확인하세요.')
        print('점수는 handedness 분류 점수이며 손 검출 정확도가 아닙니다.')
        print('frame | raw_hands | handedness(score) | duplicate_label')
        count = 0
        # Read from the beginning to reproduce the VIDEO tracking history.
        with vision.HandLandmarker.create_from_options(options) as detector:
            while count < args.end:
                ok, frame = cap.read()
                if not ok:
                    break
                timestamp = round(count * 1000 / fps)
                image = mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                result = detector.detect_for_video(image, timestamp)
                count += 1
                if count < args.start:
                    continue
                labels = []
                descriptions = []
                for categories in result.handedness:
                    if categories:
                        category = categories[0]
                        labels.append(category.category_name)
                        descriptions.append(f'{category.category_name}({category.score:.3f})')
                    else:
                        descriptions.append('no_category')
                duplicates = [label for label, n in Counter(labels).items() if n > 1]
                print(f'{count:3} | {len(result.hand_landmarks):9} | '
                      f'{", ".join(descriptions) or "none"} | {", ".join(duplicates) or "none"}')
        if count < args.end:
            print(f'영상 읽기가 {count}프레임에서 끝났습니다. 요청 범위 또는 디코딩 상태를 확인하세요.')
        print('진단 완료. 기존 좌표 파일은 변경하지 않았습니다.')
    finally:
        cap.release()


if __name__ == '__main__':
    main()
