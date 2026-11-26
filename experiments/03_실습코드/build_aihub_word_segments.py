"""Build raw word-interval arrays from preflight candidates; no normalization/training."""
import argparse
import collections
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from project_paths import resolve_saved_path
import re


def build(row, output_root):
    import numpy as np
    if row.get('status') not in ('checked', 'checked_with_warning'):
        raise ValueError('사전 검사 통과 또는 경고 후보만 처리할 수 있습니다.')
    video = resolve_saved_path(row['video'])
    folder = resolve_saved_path(row['tracking_folder'])
    label_path = resolve_saved_path(row['label_path'])
    label_bytes = label_path.read_bytes()
    label = json.loads(label_bytes.decode('utf-8-sig'))
    if Path(label['metaData']['name']).name != video.name:
        raise ValueError('라벨의 영상 이름이 다릅니다.')
    if len(label.get('data', [])) != 1:
        raise ValueError('동작 구간 수가 한 개가 아닙니다.')
    segment = label['data'][0]
    start, end = float(segment['start']), float(segment['end'])
    fps = float(row['fps'])
    video_count = int(row['video_frames_metadata'])
    if not all(math.isfinite(v) for v in (start, end, fps)) or not (0 <= start < end and fps > 0 and video_count > 0):
        raise ValueError('시간 구간 또는 FPS가 올바르지 않습니다.')
    if abs(start-float(row['label_start_seconds'])) > 1e-6 or abs(end-float(row['label_end_seconds'])) > 1e-6:
        raise ValueError('사전 검사 이후 라벨 구간이 변경됐습니다. 검사를 다시 실행하세요.')
    indices = np.asarray([i for i in range(video_count) if start <= i / fps < end], dtype=np.int64)
    if len(indices) != int(row['interval_frames_expected']) or not len(indices):
        raise ValueError('사전 검사와 선택 프레임 수가 다릅니다.')
    pattern = re.compile(re.escape(video.stem) + r'_(\d+)_keypoints\.json$')
    available = {}
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name)
        if path.is_file() and match:
            index = int(match.group(1))
            if index in available:
                raise ValueError('같은 좌표 번호의 파일이 중복됩니다.')
            available[index] = path
    n = len(indices)
    xy = np.full((n, 67, 2), np.nan, dtype=np.float32)
    confidence = np.full((n, 67), np.nan, dtype=np.float32)
    xyz = np.full((n, 67, 3), np.nan, dtype=np.float32)
    auxiliary = np.full((n, 67), np.nan, dtype=np.float32)
    file_present = np.zeros(n, dtype=bool)
    digest = hashlib.sha256()
    digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    digest.update(label_bytes)
    fields = [('hand_left', 21), ('hand_right', 21), ('pose', 25)]
    for j, index in enumerate(indices):
        digest.update(f'frame:{int(index)}\n'.encode('ascii'))
        path = available.get(int(index))
        if path is None:
            digest.update(b'MISSING\n')
            continue
        raw = path.read_bytes()
        digest.update(raw)
        person = json.loads(raw.decode('utf-8-sig'))['people']
        if isinstance(person, list):
            if len(person) != 1:
                raise ValueError(f'프레임 {index}: 사람 수 확인 필요')
            person = person[0]
        offset = 0
        for field, count in fields:
            a = np.asarray(person[field + '_keypoints_2d'], dtype=np.float32)
            b = np.asarray(person[field + '_keypoints_3d'], dtype=np.float32)
            if a.shape != (count * 3,) or b.shape != (count * 4,):
                raise ValueError(f'프레임 {index}: {field} 좌표 형식 확인 필요')
            a, b = a.reshape(count, 3), b.reshape(count, 4)
            xy[j, offset:offset+count] = a[:, :2]
            confidence[j, offset:offset+count] = a[:, 2]
            xyz[j, offset:offset+count] = b[:, :3]
            auxiliary[j, offset:offset+count] = b[:, 3]
            offset += count
        file_present[j] = True
    missing = indices[~file_present].tolist()
    previous_missing = [int(i) for i in row['interval_missing_indices_0based'].split('|') if i]
    if missing != previous_missing:
        raise ValueError('사전 검사 이후 누락 좌표가 변경됐습니다. 검사를 다시 실행하세요.')
    valid2d = np.isfinite(xy).all(axis=2) & np.isfinite(confidence) & (confidence > 0)
    finite3d = np.isfinite(xyz).all(axis=2)
    arrays = {'xy': xy, 'confidence_2d': confidence, 'xyz': xyz, 'auxiliary_3d': auxiliary,
              'file_present': file_present, 'valid_2d': valid2d, 'finite_3d': finite3d,
              'source_frame_indices': indices, 'source_times_seconds': indices / fps}
    target = output_root / row['preparation_class_id'] / f'{video.stem}.npz'
    meta_path = target.with_suffix('.json')
    checksum = digest.hexdigest()
    reused = target.exists() and meta_path.exists()
    if not reused and (target.exists() or meta_path.exists()):
        raise FileExistsError('이름이 같은 결과가 일부만 있습니다. 자동 덮어쓰기는 하지 않습니다.')
    if reused:
        oldmeta = json.loads(meta_path.read_text(encoding='utf-8'))
        if oldmeta.get('input_sha256') != checksum or oldmeta.get('schema_version') != 'aihub-word-segment-v1':
            raise ValueError('기존 결과와 입력 또는 스키마가 다릅니다. 별도 출력 폴더를 사용하세요.')
    else:
        meta = {
            'schema_version': 'aihub-word-segment-v1', 'sequence_id': video.stem,
            'class_id': row['preparation_class_id'], 'class_mapping_status': row['selection_status'],
            'source_word_code': row['code'], 'source_subject_code': row['subject_code'], 'angle': row['angle'],
            'signer_group': row['signer_group'], 'signer_identity_verified': False,
            'recording_group': row['recording_group'], 'split': 'unassigned',
            'source_video': str(video), 'source_label': str(label_path), 'source_keypoints': str(folder),
            'input_sha256': checksum, 'fps_from_preflight': fps,
            'label_start_seconds': start, 'label_end_seconds': end,
            'source_labels': [a.get('name', '') for a in segment.get('attributes', [])],
            'joint_order': 'Left hand 0..20, Right hand 0..20, Pose 0..24; no face',
            'time_assumption': 'constant FPS and coordinate frame zero aligned to video frame zero; not independently verified',
            'interval_rule': 'start <= frame_index / fps < end',
            'missing_policy': 'Retain source time slots. Missing coordinate files -> NaN arrays and false masks.',
            'valid_2d_definition': 'Finite XY and finite source 2D confidence > 0; not a verified anatomical correctness mask',
            'finite_3d_definition': 'Finite XYZ only; NOT verified 3D detection confidence or correct tracking',
            'auxiliary_3d_note': 'Fourth original 3D value preserved; semantics unverified',
            'normalization': 'none', 'resampling': 'none', 'model_training': False,
            'frames_total': n, 'frames_with_coordinate_file': int(file_present.sum()),
            'missing_source_frame_indices_0based': missing,
            'shape_xy': list(xy.shape), 'shape_xyz': list(xyz.shape),
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, **arrays)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with np.load(target, allow_pickle=False) as saved:
        if set(saved.files) != set(arrays):
            raise ValueError('저장된 배열 이름이 다릅니다.')
        for name, expected in arrays.items():
            if not np.array_equal(saved[name], expected, equal_nan=True):
                raise ValueError(f'저장 후 비교 실패: {name}')
    return {
        'sequence_id': video.stem, 'class_id': row['preparation_class_id'],
        'subject_code': row['subject_code'], 'angle': row['angle'],
        'status': 'reused' if reused else 'created', 'frames_total': n,
        'frames_with_coordinate_file': int(file_present.sum()), 'missing_frame_slots': len(missing),
        'missing_indices_0based': '|'.join(map(str, missing)),
        'npz_path': str(target.resolve()), 'metadata_path': str(meta_path.resolve()), 'error': '',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'aihub_word_segments')
    args = parser.parse_args()
    with args.manifest.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows or len({r['video'] for r in rows}) != len(rows):
        raise ValueError('목록이 비었거나 영상 경로가 중복됩니다.')
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = args.output / f'segment_report_{stamp}.csv'
    fields = ['sequence_id', 'class_id', 'subject_code', 'angle', 'status', 'frames_total',
              'frames_with_coordinate_file', 'missing_frame_slots', 'missing_indices_0based',
              'npz_path', 'metadata_path', 'error']
    results = []
    for index, row in enumerate(rows, 1):
        try:
            item = build(row, args.output)
        except Exception as exc:
            item = {'sequence_id': resolve_saved_path(row['video']).stem, 'class_id': row['preparation_class_id'],
                    'subject_code': row['subject_code'], 'angle': row['angle'], 'status': 'failed', 'error': str(exc)}
        results.append(item)
        print(f"[{index}/{len(rows)}] {item['sequence_id']}: {item['status']}", flush=True)
        with report.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(results)
    counts = collections.Counter(r['status'] for r in results)
    success = counts['created'] + counts['reused']
    missing_total = sum(r.get('missing_frame_slots', 0) for r in results if r['status'] != 'failed')
    summary = {'input_sequences': len(rows), 'success': success, 'failed': counts['failed'],
               'created': counts['created'], 'reused': counts['reused'], 'missing_frame_slots_preserved': missing_total,
               'successful_by_class': dict(collections.Counter(r['class_id'] for r in results if r['status'] != 'failed')),
               'report': str(report.resolve()), 'scope': 'Raw word intervals only. No normalization, 30-frame conversion, data split or model training.'}
    report.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n=== 동작 구간 저장 요약 ===')
    print(f"대상 {len(rows)}개 / 성공 {success}개 / 실패 {counts['failed']}개")
    print(f'누락 위치 유지: {missing_total}프레임')
    print(f'결과표: {report.resolve()}')
    print('원시 좌표 저장 단계입니다. 정규화/30프레임 변환/모델 학습은 실행하지 않았습니다.')


if __name__ == '__main__':
    main()
