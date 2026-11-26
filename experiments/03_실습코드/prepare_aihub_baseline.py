"""Prepare an experimental AI Hub 2D baseline; independent of the MediaPipe contract."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

CLASSES = ['coffee', 'milk', 'sleep_v1', 'sleep_v2', 'sleep_v3', 'sleep_v4', 'cold', 'thanks']
VERSION = 'aihub-2d-upper50-nearest30-v1'


def split_for(code):
    code = int(code)
    if 1 <= code <= 10:
        return 'train'
    if 11 <= code <= 12:
        return 'validation'
    if 13 <= code <= 16:
        return 'test'
    raise ValueError('예상 범위 밖 촬영 코드입니다.')


def preprocess(xy, valid):
    import numpy as np
    if xy.ndim != 3 or xy.shape[1:] != (67, 2) or valid.shape != xy.shape[:2] or not len(xy):
        raise ValueError('원시 2D 배열 크기가 올바르지 않습니다.')
    # Original order: hands 0..41, BODY_25 pose 42..66.
    # BODY_25 shoulders: pose 2 (R), pose 5 (L).
    reference = xy[:, [44, 47], :]
    shoulder_width = np.linalg.norm(reference[:, 0] - reference[:, 1], axis=1)
    usable = valid[:, [44, 47]].all(axis=1) & np.isfinite(reference).all(axis=(1, 2)) & (shoulder_width > 1.0)
    if not usable.any():
        raise ValueError('정규화할 수 있는 어깨 기준 프레임이 없습니다.')
    selected = xy[:, :50, :].astype(np.float32, copy=True)
    mask = valid[:, :50].astype(bool) & np.isfinite(selected).all(axis=2) & usable[:, None]
    normalized = np.full_like(selected, np.nan)
    center = reference.mean(axis=1)
    normalized[usable] = (selected[usable] - center[usable, None, :]) / shoulder_width[usable, None, None]
    normalized[~mask] = np.nan
    # Nearest temporal selection: never interpolates missing positions.
    positions = np.rint(np.linspace(0, len(xy) - 1, 30)).astype(np.int64)
    output_mask = mask[positions]
    output_xy = normalized[positions]
    model_xy = np.where(output_mask[:, :, None], output_xy, 0.0).astype(np.float32)
    features = np.concatenate([model_xy.reshape(30, 100), output_mask.astype(np.float32)], axis=1)
    if not np.isfinite(features).all():
        raise ValueError('모델 입력에 비정상 수치가 있습니다.')
    return features, output_mask, positions, usable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--segments', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'aihub_word_segments')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'aihub_baseline_v1')
    args = parser.parse_args()
    import numpy as np
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError('출력 폴더에 결과가 있습니다. 확인하거나 다른 --output 경로를 사용하세요.')
    inputs = sorted(args.segments.rglob('*.npz'))
    if not inputs:
        raise FileNotFoundError('동작 구간 NPZ가 없습니다.')
    samples, features, masks, chosen_frames, chosen_times = [], [], [], [], []
    errors = []
    seen = set()
    for path in inputs:
        try:
            meta_path = path.with_suffix('.json')
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if meta['schema_version'] != 'aihub-word-segment-v1' or meta['angle'] != 'F':
                raise ValueError('이번 실험의 구간 스키마 또는 F 각도가 아닙니다.')
            if meta['class_id'] not in CLASSES:
                raise ValueError('이번 8개 임시 분류에 없는 클래스입니다.')
            if meta['sequence_id'] in seen:
                raise ValueError('중복 시퀀스입니다.')
            seen.add(meta['sequence_id'])
            code = meta['source_subject_code']
            group = f'REAL{int(code):02d}'
            if meta['signer_group'] != group:
                raise ValueError('촬영 코드와 그룹이 일치하지 않습니다.')
            with np.load(path, allow_pickle=False) as data:
                xy = data['xy']; valid = data['valid_2d']; file_present = data['file_present']
                frame_ids = data['source_frame_indices']; frame_times = data['source_times_seconds']
                if len(frame_ids) != len(xy) or len(file_present) != len(xy) or not np.all(np.diff(frame_ids) == 1):
                    raise ValueError('원본 시간축 슬롯이 보존되지 않았습니다.')
                if not np.isnan(xy[~file_present]).all() or valid[~file_present].any():
                    raise ValueError('누락 프레임의 NaN/마스크를 확인하세요.')
                x, mask, positions, usable = preprocess(xy, valid)
                features.append(x); masks.append(mask); chosen_frames.append(frame_ids[positions]); chosen_times.append(frame_times[positions])
                samples.append({
                    'sequence_id': meta['sequence_id'], 'class_id': meta['class_id'],
                    'label_index': CLASSES.index(meta['class_id']), 'subject_group': group,
                    'split': split_for(code), 'source_npz': str(path.resolve()),
                    'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'metadata_sha256': hashlib.sha256(meta_path.read_bytes()).hexdigest(),
                    'raw_frames': len(xy), 'raw_missing_file_slots': int((~file_present).sum()),
                    'raw_normalizable_frames': int(usable.sum()),
                    'sampled_frames_with_any_missing_joint': int((~mask.all(axis=1)).sum()),
                })
        except Exception as exc:
            errors.append({'path': str(path), 'error': str(exc)})
    # No silent sample drops: an error stops the build before model arrays are saved.
    if errors:
        print(json.dumps(errors, ensure_ascii=False, indent=2))
        raise RuntimeError(f'{len(errors)}개 입력 확인 필요. 학습 배열은 저장하지 않았습니다.')
    membership = {name: {s['subject_group'] for s in samples if s['split'] == name} for name in ['train','validation','test']}
    if membership['train'] & membership['validation'] or membership['train'] & membership['test'] or membership['validation'] & membership['test']:
        raise ValueError('촬영 코드 그룹이 분할 사이에 중복됩니다.')
    for split in membership:
        present_classes = {s['class_id'] for s in samples if s['split'] == split}
        if present_classes != set(CLASSES):
            raise ValueError(f'{split}에 8개 클래스가 모두 있지 않습니다.')
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / 'dataset.npz'
    arrays = {'X': np.stack(features), 'joint_mask': np.stack(masks),
              'y': np.asarray([s['label_index'] for s in samples], dtype=np.int64),
              'split': np.asarray([s['split'] for s in samples]),
              'subject_group': np.asarray([s['subject_group'] for s in samples]),
              'sequence_id': np.asarray([s['sequence_id'] for s in samples]),
              'sampled_source_frame_indices': np.stack(chosen_frames),
              'sampled_source_times_seconds': np.stack(chosen_times)}
    np.savez_compressed(target, **arrays)
    with np.load(target, allow_pickle=False) as saved:
        for key, value in arrays.items():
            if not np.array_equal(saved[key], value):
                raise ValueError(f'배열 저장 후 비교 실패: {key}')
    with (args.output / 'sample_manifest.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(samples[0])); writer.writeheader(); writer.writerows(samples)
    spec = {
        'preprocessing_version': VERSION, 'class_names': CLASSES,
        'representation': 'AI Hub 2D experimental baseline; not the 177-value MediaPipe serving interface',
        'joints': 'Left hand21, Right hand21, BODY_25 pose indices0..7 (8); total50',
        'body25_index_reference': 'https://cmu-perceptual-computing-lab.github.io/openpose/web/html/doc/md_doc_02_output.html',
        'mapping_assumption': 'AI Hub pose25 fields use BODY_25 order; semantic mapping should be visually reviewed',
        'normalization': 'per-frame shoulder midpoint and Euclidean shoulder width in source pixel XY; no fitted dataset statistics',
        'shoulder_indices_pose': [2,5], 'shoulder_min_width_pixels': 1.0,
        'temporal': '30 evenly spaced positions, rounded to nearest source slot; no interpolation',
        'missing': 'If joint/reference unavailable, XY=0 at final model input and its joint_mask=0. Raw files untouched.',
        'features_per_frame': 150, 'feature_order': '50x2 normalized XY followed by50 joint-mask values',
        'data_split': {'train':['REAL01..REAL10'],'validation':['REAL11','REAL12'],'test':['REAL13..REAL16']},
        'identity_caveat': 'Source codes are group identifiers; actual distinct-person identities not yet independently verified.',
        'evaluation_caveat': 'Small exploratory holdout. No accuracy claim; further grouped evaluation and independent camera data required.',
        'model_training': False,
    }
    (args.output / 'preprocessing.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'sequences':len(samples),'shape_X':list(arrays['X'].shape),
               'split_counts':dict(collections.Counter(s['split'] for s in samples)),
               'split_class_counts':{split:dict(collections.Counter(s['class_id'] for s in samples if s['split']==split)) for split in membership},
               'groups':{k:sorted(v) for k,v in membership.items()},'source_missing_file_slots':sum(s['raw_missing_file_slots'] for s in samples),
               'scope':'Prepared features and source-code-group holdout only. No model training or performance evaluation.'}
    (args.output/'preparation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n=== 기준선 입력 준비 완료 ===')
    print(f'전체: {len(samples)}개 / X 크기: {arrays["X"].shape}')
    for name in ['train','validation','test']:
        print(f'{name}: {summary["split_counts"].get(name,0)}개 / 그룹 {", ".join(sorted(membership[name]))}')
    print('분할 간 촬영 코드 그룹 중복: 0개')
    print(f'저장: {target.resolve()}')
    print('AI Hub 2D 실험용 입력입니다. 모델 학습은 아직 하지 않았습니다.')


if __name__ == '__main__':
    main()
