"""Experimental anatomical hand assignment using Pose wrists, without training."""
import argparse
from collections import Counter
import csv
import hashlib
import itertools
import json
from pathlib import Path
from project_paths import resolve_saved_path


def choose_assignment(wrists, references, scale, max_distance=0.75, min_margin=0.25):
    """Inputs are pixel XY; return (detection index, anatomical side index).

    Side 0 = Pose Left wrist, side 1 = Pose Right wrist.
    Both references must already have passed reliability checks.
    Thresholds are unvalidated experiment settings, in shoulder-width units.
    """
    import numpy as np
    if len(wrists) not in (1, 2) or not np.isfinite(scale) or scale <= 1:
        return [], 'no_valid_detections_or_scale'
    costs = []
    for sides in itertools.permutations((0, 1), len(wrists)):
        distances = [float(np.linalg.norm(wrist - references[side]) / scale)
                     for wrist, side in zip(wrists, sides)]
        costs.append((sum(distances), sides, distances))
    costs.sort(key=lambda item: item[0])
    best, second = costs
    if any(value > max_distance for value in best[2]):
        return [], 'too_far_from_pose_wrist'
    if second[0] - best[0] < min_margin:
        return [], 'ambiguous_pose_matching'
    return list(enumerate(best[1])), 'pose_matched'


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--coordinates', type=Path, required=True)
    args = parser.parse_args()
    import cv2
    import numpy as np
    raw = json.loads(args.raw.read_text(encoding='utf-8'))
    meta = json.loads(args.coordinates.with_suffix('.json').read_text(encoding='utf-8'))
    video = resolve_saved_path(meta['source_video'])
    if raw.get('schema_version') != 'raw-hand-review-v1' or meta.get('schema_version') != 'ksl-raw-hands-pose17-v1':
        raise ValueError('입력 스키마가 올바르지 않습니다.')
    if raw['video_sha256'] != sha256(video) or resolve_saved_path(raw['source_video']).resolve() != video.resolve():
        raise ValueError('원시 진단 결과와 원본 영상이 다릅니다.')
    if raw['hand_model_sha256'] != meta['model_sha256']['hand_landmarker.task']:
        raise ValueError('두 추출 결과의 손 모델이 다릅니다.')
    with np.load(args.coordinates, allow_pickle=False) as data:
        original = data['coordinates'].copy()
        visibility = data['pose_visibility'].copy()
        times = data['timestamps_seconds'].copy()
    n = len(original)
    if original.shape != (n, 177) or visibility.shape != (n, 17) or len(raw['frames']) != n or times.shape != (n,):
        raise ValueError('프레임 수 또는 배열 크기가 다릅니다.')
    if not np.allclose([f['timestamp_ms'] for f in raw['frames']], times * 1000, atol=0.51):
        raise ValueError('두 추출 결과의 시각이 일치하지 않습니다.')
    if [f['frame_number'] for f in raw['frames']] != list(range(1, n + 1)):
        raise ValueError('원시 검출 프레임 번호가 순서대로 있지 않습니다.')
    cap = cv2.VideoCapture(str(video))
    try:
        ok, image = cap.read()
        if not ok:
            raise RuntimeError('원본 영상 크기를 확인할 수 없습니다.')
        height, width = image.shape[:2]
    finally:
        cap.release()
    pixel_scale = np.array([width, height], dtype=float)
    result = original.reshape(n, 59, 3).copy()
    result[:, :42] = np.nan
    rows = []
    for index, frame in enumerate(raw['frames']):
        row = {'frame': index + 1, 'raw_hands': len(frame['detections']),
               'duplicate_labels': '|'.join(frame['duplicate_labels']),
               'left_detection': '', 'right_detection': '', 'status': ''}
        pose = result[index, 42:]
        reference_indices = [11, 12, 15, 16]
        if not np.isfinite(pose[reference_indices, :2]).all() or not np.isfinite(visibility[index, reference_indices]).all() or (visibility[index, reference_indices] < 0.5).any():
            row['status'] = 'pose_reference_unreliable'
        else:
            references = pose[[15, 16], :2] * pixel_scale
            shoulder_width = float(np.linalg.norm((pose[11, :2] - pose[12, :2]) * pixel_scale))
            points, ids = [], []
            for detection in frame['detections']:
                array = np.asarray(detection['landmarks'], dtype=float)
                if array.shape == (21, 3) and np.isfinite(array).all():
                    points.append(array)
                    ids.append(detection['detection_index'])
            assignment, status = choose_assignment([p[0, :2] * pixel_scale for p in points], references, shoulder_width)
            row['status'] = status
            for detection_position, side in assignment:
                result[index, side * 21:(side + 1) * 21] = points[detection_position]
                row['left_detection' if side == 0 else 'right_detection'] = ids[detection_position]
        rows.append(row)
    mask = np.isfinite(result).all(axis=2)
    oldmask = np.isfinite(original.reshape(n, 59, 3)).all(axis=2)

    def counts(m):
        return {'left_present_frames': int(m[:, :21].all(axis=1).sum()),
                'right_present_frames': int(m[:, 21:42].all(axis=1).sum()),
                'both_missing_frames': int((~m[:, :42].any(axis=1)).sum())}

    comparison = {'before': counts(oldmask), 'experiment': counts(mask)}
    root = Path(__file__).resolve().parent
    output = root.parent / '04_데이터' / 'ksl_data' / 'assignment_experiment' / f"{int(meta['class_id']):02d}" / args.coordinates.name
    outputs = [output, output.with_suffix('.json'), output.with_suffix('.csv')]
    if any(path.exists() for path in outputs):
        raise FileExistsError('실험 결과가 이미 있습니다. 기존 결과를 먼저 확인하세요.')
    newmeta = dict(meta)
    newmeta.update(schema_version='ksl-pose-assignment-experiment-v1',
                   assignment_method='independent per-frame Pose wrist matching; no temporal tracking',
                   experimental_settings={'pose_visibility_min': 0.5, 'max_wrist_distance_shoulder_units': 0.75,
                                          'min_cost_margin_shoulder_units': 0.25, 'validated': False},
                   input_raw_sha256=sha256(args.raw), input_coordinates_sha256=sha256(args.coordinates),
                   comparison=comparison,
                   summary={'frame_count': n, 'assignment_status_counts': dict(Counter(row['status'] for row in rows))})
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, coordinates=result.reshape(n, 177), landmark_valid=mask,
                        timestamps_seconds=times, pose_visibility=visibility)
    outputs[1].write_text(json.dumps(newmeta, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with outputs[2].open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with np.load(output, allow_pickle=False) as saved:
        if not np.array_equal(saved['coordinates'], result.reshape(n, 177), equal_nan=True):
            raise ValueError('배열 저장 후 비교 실패')
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print('정확도는 측정하지 않았습니다. 누락 감소만으로 성공이라고 판단하지 마세요.')
    print('배정 보류는 좌표 없음으로 저장되며 원시 검출은 별도 JSON에 보존됩니다.')
    for path in outputs:
        print(f'저장: {path}')


if __name__ == '__main__':
    main()
