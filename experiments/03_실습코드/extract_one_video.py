"""Extract raw hands + pose[0:17] from one video; no training or resampling."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    video = args.video.resolve()
    match = re.fullmatch(r'(\d+)_(\d+)\.[mM][pP]4', video.name)
    if not video.is_file() or not match:
        raise ValueError('영상 경로와 파일명(예: 00_01.MP4)을 확인하세요.')
    signer, class_text = match.groups()
    models = [root.parent / '04_데이터' / 'models' / name for name in
              ('hand_landmarker.task', 'pose_landmarker_lite.task')]
    for path in models:
        if not path.is_file():
            raise FileNotFoundError(f'모델 파일이 없습니다: {path}')

    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    target = root.parent / '04_데이터' / 'ksl_data' / 'raw_coordinates' / f'{int(class_text):02d}'
    paths = [target / f'{video.stem}{suffix}' for suffix in ('.npz', '.json')]
    if any(path.exists() for path in paths):
        raise FileExistsError('동일한 결과가 이미 있습니다. 기존 결과를 먼저 확인하세요.')
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise RuntimeError(f'영상을 열 수 없습니다: {video}')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0 or fps > 1000:
            raise ValueError(f'FPS 메타데이터를 확인할 수 없습니다: {fps}')
        hand_bytes, pose_bytes = [p.read_bytes() for p in models]
        hand_options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=hand_bytes),
            running_mode=vision.RunningMode.VIDEO, num_hands=2)
        pose_options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=pose_bytes),
            running_mode=vision.RunningMode.VIDEO, num_poses=1)
        frames, masks, times, visibilities = [], [], [], []
        issues = Counter()
        with vision.HandLandmarker.create_from_options(hand_options) as hand_model, \
                vision.PoseLandmarker.create_from_options(pose_options) as pose_model:
            while True:
                ok, bgr = cap.read()
                if not ok:
                    break
                index = len(frames)
                timestamp = round(index * 1000 / fps)
                image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
                hands = hand_model.detect_for_video(image, timestamp)
                pose = pose_model.detect_for_video(image, timestamp)
                coords = np.full((59, 3), np.nan, dtype=np.float32)
                visibility = np.full(17, np.nan, dtype=np.float32)
                candidates = {'Left': [], 'Right': []}
                for points, categories in zip(hands.hand_landmarks, hands.handedness):
                    if categories and categories[0].category_name in candidates:
                        candidates[categories[0].category_name].append(points)
                for side, offset in [('Left', 0), ('Right', 21)]:
                    if len(candidates[side]) == 1:
                        points = candidates[side][0]
                        if len(points) == 21:
                            coords[offset:offset + 21] = [[p.x, p.y, p.z] for p in points]
                    elif len(candidates[side]) > 1:
                        issues[f'ambiguous_{side}_frames'] += 1
                if pose.pose_landmarks and len(pose.pose_landmarks[0]) >= 17:
                    points = pose.pose_landmarks[0][:17]
                    coords[42:] = [[p.x, p.y, p.z] for p in points]
                    visibility[:] = [p.visibility for p in points]
                # Preserve missing values; low-visibility pose is NOT silently zeroed.
                valid = np.isfinite(coords).all(axis=1)
                coords[~valid] = np.nan
                frames.append(coords.reshape(177))
                masks.append(valid)
                times.append(index / fps)
                visibilities.append(visibility)
                if len(frames) % 30 == 0:
                    print(f'처리: {len(frames)} 프레임', flush=True)
        if not frames:
            raise RuntimeError('읽은 프레임이 없습니다. 동영상 재생 여부를 확인하세요.')
        if expected > 0 and len(frames) != expected:
            raise RuntimeError(f'읽은 프레임 {len(frames)} != 메타데이터 {expected}. 저장하지 않습니다. 영상 디코딩을 확인하세요.')
        values = np.stack(frames)
        present = np.stack(masks)
        pose_visibility = np.stack(visibilities)
        summary = {
            'frame_count': len(frames), 'features_per_frame': 177,
            'left_hand_present_frames': int(present[:, :21].all(axis=1).sum()),
            'right_hand_present_frames': int(present[:, 21:42].all(axis=1).sum()),
            'both_hands_missing_frames': int((~present[:, :42].any(axis=1)).sum()),
            'pose_present_frames': int(present[:, 42:].all(axis=1).sum()),
            'both_shoulders_visibility_ge_0_5_frames': int(
                (np.isfinite(pose_visibility[:, [11, 12]]).all(axis=1) &
                 (pose_visibility[:, [11, 12]] >= 0.5).all(axis=1)).sum()),
            'issues': dict(issues),
        }
        meta = {
            'schema_version': 'ksl-raw-hands-pose17-v1', 'source_video': str(video),
            'class_id': int(class_text), 'signer_id': signer,
            'signer_id_basis': 'filename prefix; same person across classes confirmed by user',
            'split': 'unassigned', 'mirrored_by_script': False,
            'fps_from_metadata': fps, 'timestamp_basis': 'frame_index / metadata_fps; assumes constant frame rate',
            'landmark_order': 'Left hand 0..20, Right hand 0..20, Pose 0..16; xyz',
            'coordinate_space': 'raw MediaPipe image landmarks; hand z and pose z have different origins',
            'missing_value': 'NaN in NPZ; landmark validity stored separately',
            'normalization': 'none', 'resampling': 'none',
            'versions': {'mediapipe': mp.__version__, 'opencv': cv2.__version__, 'numpy': np.__version__},
            'model_sha256': {path.name: hashlib.sha256(data).hexdigest()
                             for path, data in zip(models, [hand_bytes, pose_bytes])},
            'summary': summary,
        }
        target.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(paths[0], coordinates=values, landmark_valid=present,
                            timestamps_seconds=np.asarray(times), pose_visibility=pose_visibility)
        paths[1].write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        with np.load(paths[0], allow_pickle=False) as saved:
            if saved['coordinates'].shape != (len(frames), 177):
                raise ValueError('저장 후 배열 크기 검증 실패')
        print('\n좌표 추출 완료 — 학습 전 원시 좌표입니다.')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f'배열 크기: {values.shape}')
        for path in paths:
            print(f'저장: {path}')
    finally:
        cap.release()


if __name__ == '__main__':
    main()
