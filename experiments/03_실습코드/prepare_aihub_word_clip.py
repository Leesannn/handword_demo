"""Select a labeled time interval; preserve AI Hub coordinates separately from MediaPipe."""
import argparse
import io
import json
from pathlib import Path
import tarfile
import zipfile

from review_aihub_video import load_frames


def read_label(tar_path, stem):
    suffix = '/' + stem + '_morpheme.json'
    with tarfile.open(tar_path) as archive:
        members = [m for m in archive.getmembers() if m.isfile() and
                   ('morpheme.zip' in m.name)]
        if len(members) != 1:
            raise ValueError('라벨 ZIP이 한 개 들어 있는 TAR인지 확인하세요.')
        # Read the nested ZIP without extracting archive paths to disk.
        with archive.extractfile(members[0]) as stream:
            contents = io.BytesIO(stream.read())
        with zipfile.ZipFile(contents) as labels:
            matches = [name for name in labels.namelist() if name.endswith(suffix)]
            if len(matches) != 1:
                raise ValueError(f'해당 영상의 라벨이 정확히 한 개 필요합니다: {matches}')
            return json.loads(labels.read(matches[0]).decode('utf-8-sig')), matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--keypoints', type=Path, required=True)
    parser.add_argument('--labels-tar', type=Path, required=True)
    parser.add_argument('--label', default='감사')
    args = parser.parse_args()
    import cv2
    import numpy as np
    video = args.video.resolve()
    label, label_member = read_label(args.labels_tar, video.stem)
    if label['metaData']['name'] != video.name:
        raise ValueError('라벨의 영상 이름이 입력 영상과 다릅니다.')
    segments = [s for s in label['data'] if any(a.get('name') == args.label for a in s.get('attributes', []))]
    if len(segments) != 1:
        raise ValueError(f'선택한 단어 구간이 정확히 한 개 필요합니다. 발견: {len(segments)}')
    start, end = float(segments[0]['start']), float(segments[0]['end'])
    if not np.isfinite([start, end]).all() or not 0 <= start < end:
        raise ValueError('라벨의 시작/종료 시각이 올바르지 않습니다.')
    frames = load_frames(args.keypoints, video.stem)
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise RuntimeError('영상 메타데이터를 읽을 수 없습니다.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    if not np.isfinite(fps) or not 0 < fps <= 1000 or count != len(frames):
        raise ValueError('영상 FPS 또는 영상/좌표 프레임 수를 확인하세요.')
    if end > count / fps + 1 / fps:
        raise ValueError('라벨 종료 시각이 영상 범위를 벗어납니다.')
    times = np.arange(count, dtype=float) / fps
    indices = np.flatnonzero((times >= start) & (times < end))
    if not len(indices):
        raise ValueError('라벨 구간에 대응하는 프레임이 없습니다.')
    fields = [('hand_left', 21), ('hand_right', 21), ('pose', 25)]
    points2d, confidence2d, points3d, auxiliary3d = [], [], [], []
    for i in indices:
        frame2d, frame3d = [], []
        for field, joints in fields:
            a = np.asarray(frames[i][field + '_keypoints_2d'], dtype=np.float32)
            b = np.asarray(frames[i][field + '_keypoints_3d'], dtype=np.float32)
            if a.size != joints * 3 or b.size != joints * 4 or not np.isfinite(b).all():
                raise ValueError(f'좌표 형식 확인 필요: 프레임 {i + 1}, {field}')
            frame2d.append(a.reshape(joints, 3))
            frame3d.append(b.reshape(joints, 4))
        a, b = np.concatenate(frame2d), np.concatenate(frame3d)
        points2d.append(a[:, :2]); confidence2d.append(a[:, 2])
        points3d.append(b[:, :3]); auxiliary3d.append(b[:, 3])
    arrays = {'xy': np.stack(points2d), 'confidence_2d': np.stack(confidence2d),
              'xyz': np.stack(points3d), 'auxiliary_3d': np.stack(auxiliary3d),
              'source_frame_indices': indices, 'source_times_seconds': times[indices]}
    root = Path(__file__).resolve().parent
    output = root.parent / '04_데이터' / 'ksl_data' / 'aihub_word_clips' / f'{video.stem}.npz'
    metadata_path = output.with_suffix('.json')
    if output.exists() or metadata_path.exists():
        raise FileExistsError('동일한 구간 결과가 이미 있습니다. 기존 결과를 먼저 확인하세요.')
    meta = {'schema_version': 'aihub-word-clip-v1', 'label': args.label,
            'source_video': str(video), 'source_keypoints': str(args.keypoints.resolve()),
            'source_label_tar': str(args.labels_tar.resolve()), 'source_label_member': label_member,
            'video_fps': fps, 'label_start_seconds': start, 'label_end_seconds': end,
            'interval_rule': 'start <= frame_index / video_fps < end; assumes constant frame rate and aligned frame zero',
            'selected_frames': len(indices), 'first_frame_1based': int(indices[0] + 1),
            'last_frame_1based': int(indices[-1] + 1),
            'joint_order': 'Left hand 0..20, Right hand 0..20, Pose 0..24; face omitted',
            'coordinate_note': 'AI Hub source values; NOT MediaPipe 177 features; no normalization or resampling',
            'auxiliary_3d_note': 'Fourth source value preserved without assuming its semantics',
            'split': 'unassigned', 'shape_xy': list(arrays['xy'].shape),
            'shape_xyz': list(arrays['xyz'].shape)}
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **arrays)
    metadata_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with np.load(output, allow_pickle=False) as saved:
        for name, value in arrays.items():
            if not np.array_equal(saved[name], value, equal_nan=True):
                raise ValueError(f'저장 후 배열 비교 실패: {name}')
    print(f'단어: {args.label}')
    print(f'라벨 구간: {start:.3f} ~ {end:.3f}초')
    print(f'선택: {meta["first_frame_1based"]} ~ {meta["last_frame_1based"]}프레임 / {len(indices)}개')
    print(f'2D 좌표: {arrays["xy"].shape} / 3D 좌표: {arrays["xyz"].shape}')
    print('원본 좌표 유지. 정규화/30프레임 변환/모델 학습은 실행하지 않았습니다.')
    print(f'저장: {output}')
    print(f'메타데이터: {metadata_path}')


if __name__ == '__main__':
    main()
