"""Batch raw hand preservation + experimental Pose assignment, not training."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

from assign_hands_experiment import sha256


def run_script(root, name, arguments):
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run([sys.executable, str(root / name), *map(str, arguments)],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', env=env)
    if result.returncode:
        raise RuntimeError((result.stderr + '\n' + result.stdout)[-4000:])


def validate_existing(output, raw_path, source):
    import numpy as np
    meta = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
    if meta.get('schema_version') != 'ksl-pose-assignment-experiment-v1':
        raise ValueError('실험 결과 스키마가 다릅니다.')
    if meta.get('input_raw_sha256') != sha256(raw_path) or meta.get('input_coordinates_sha256') != sha256(source):
        raise ValueError('기존 실험의 입력이 변경됐습니다. 자동 덮어쓰기를 하지 않습니다.')
    expected_settings = {'pose_visibility_min': 0.5, 'max_wrist_distance_shoulder_units': 0.75,
                         'min_cost_margin_shoulder_units': 0.25, 'validated': False}
    if meta.get('experimental_settings') != expected_settings:
        raise ValueError('기존 실험 설정이 다릅니다.')
    with np.load(output, allow_pickle=False) as data, np.load(source, allow_pickle=False) as old:
        coords, mask = data['coordinates'], data['landmark_valid']
        n = len(coords)
        if not n or coords.shape != (n, 177) or mask.shape != (n, 59) or old['coordinates'].shape != coords.shape:
            raise ValueError('실험 배열 크기가 올바르지 않습니다.')
        if not np.array_equal(mask, np.isfinite(coords.reshape(n, 59, 3)).all(axis=2)):
            raise ValueError('실험 좌표와 검출 마스크가 다릅니다.')
        if not np.array_equal(coords[:, 126:], old['coordinates'][:, 126:], equal_nan=True):
            raise ValueError('보존해야 할 상체 좌표가 변경됐습니다.')
        if not np.array_equal(data['timestamps_seconds'], old['timestamps_seconds']):
            raise ValueError('실험 시각과 기존 시각이 다릅니다.')

        def counts(array):
            valid = np.isfinite(array.reshape(n, 59, 3)).all(axis=2)
            return {'left_present_frames': int(valid[:, :21].all(axis=1).sum()),
                    'right_present_frames': int(valid[:, 21:42].all(axis=1).sum()),
                    'both_missing_frames': int((~valid[:, :42].any(axis=1)).sum())}

        before, after = counts(old['coordinates']), counts(coords)
        if meta['comparison'] != {'before': before, 'experiment': after}:
            raise ValueError('비교 요약과 좌표가 일치하지 않습니다.')
    return n, before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classes', type=int, nargs='+', default=[1, 13])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    for name in ('review_raw_hands.py', 'assign_hands_experiment.py'):
        if not (root / name).is_file():
            raise FileNotFoundError(f'필요한 스크립트가 없습니다: {name}')
    videos = []
    for class_id in sorted(set(args.classes)):
        directory = root.parent / '04_데이터' / 'ksl_data' / 'videos' / f'{class_id:02d}'
        group = sorted(p for p in directory.glob('*') if p.is_file() and p.suffix.lower() == '.mp4')
        if not group:
            raise FileNotFoundError(f'영상이 없습니다: {directory}')
        videos.extend(group)
    fields = ['class_id', 'signer_id', 'video', 'status', 'frame_count',
              'before_both_missing', 'after_both_missing', 'recovered_frames_net',
              'before_left_present', 'after_left_present', 'before_right_present', 'after_right_present',
              'raw_zero_detection_frames', 'raw_duplicate_label_frames', 'error']
    report = root.parent / '04_데이터' / 'ksl_data' / 'assignment_comparison.csv'
    rows = []
    print(f'대상 {len(videos)}개 / 실험 결과 별도 저장 / 학습 실행 안 함', flush=True)
    for index, video in enumerate(videos, 1):
        row = {'video': str(video), 'status': 'failed', 'error': ''}
        print(f'\n[{index}/{len(videos)}] {video.parent.name}/{video.name}', flush=True)
        try:
            signer, class_id = video.stem.split('_')
            if not signer.isdigit() or int(class_id) != int(video.parent.name):
                raise ValueError('파일명과 분류 폴더가 일치하지 않습니다.')
            row.update(class_id=int(class_id), signer_id=signer)
            directory = f'{int(class_id):02d}'
            source = root.parent / '04_데이터' / 'ksl_data' / 'raw_coordinates' / directory / f'{video.stem}.npz'
            if not source.is_file() or not source.with_suffix('.json').is_file():
                raise FileNotFoundError('기존 좌표 또는 메타데이터가 없습니다.')
            # Reuses only when the raw review tool validates video/model hashes.
            run_script(root, 'review_raw_hands.py', ['--video', video, '--no-preview'])
            raw_path = root.parent / '04_데이터' / 'ksl_data' / 'raw_hand_diagnostics' / directory / f'{video.stem}.json'
            output = root.parent / '04_데이터' / 'ksl_data' / 'assignment_experiment' / directory / source.name
            expected = [output, output.with_suffix('.json'), output.with_suffix('.csv')]
            reused = all(path.is_file() for path in expected)
            if not reused and any(path.exists() for path in expected):
                raise ValueError('실험 결과 일부만 있습니다. 파일을 확인하세요. 자동 삭제하지 않습니다.')
            if not reused:
                run_script(root, 'assign_hands_experiment.py', ['--raw', raw_path, '--coordinates', source])
            n, before, after = validate_existing(output, raw_path, source)
            raw = json.loads(raw_path.read_text(encoding='utf-8'))
            row.update(status='reused' if reused else 'created', frame_count=n,
                       before_both_missing=before['both_missing_frames'], after_both_missing=after['both_missing_frames'],
                       recovered_frames_net=before['both_missing_frames'] - after['both_missing_frames'],
                       before_left_present=before['left_present_frames'], after_left_present=after['left_present_frames'],
                       before_right_present=before['right_present_frames'], after_right_present=after['right_present_frames'],
                       raw_zero_detection_frames=raw['summary']['raw_zero_detection_frames'],
                       raw_duplicate_label_frames=raw['summary']['duplicate_label_frames'])
            print(f"{row['status']} | 양손 좌표 없음 {row['before_both_missing']} -> {row['after_both_missing']} | 순감소 {row['recovered_frames_net']}", flush=True)
        except Exception as exc:
            row['error'] = str(exc)
            print(f'실패: {exc}', flush=True)
        rows.append(row)
        # Negative reductions (worse coverage) appear first among completed videos.
        ordered = sorted(rows, key=lambda r: (r['status'] != 'failed', r.get('recovered_frames_net', 0)))
        with report.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ordered)
    failed = sum(row['status'] == 'failed' for row in rows)
    print(f'\n총 {len(rows)}개 / 성공 {len(rows) - failed}개 / 실패 {failed}개')
    print(f'비교표: {report}')
    print('recovered_frames_net은 양손 좌표 없음의 순감소입니다. 양손 복구 수나 인식 정확도가 아닙니다.')
    print('미검증 실험: 자동 학습 포함/제외 판정은 하지 않습니다.')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
