"""Run the existing single-video extractor sequentially; summarize raw coordinates."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path
import subprocess
import sys


def inspect_result(video, coordinates, metadata, model_hashes):
    import numpy as np
    meta = json.loads(metadata.read_text(encoding='utf-8'))
    if meta.get('schema_version') != 'ksl-raw-hands-pose17-v1':
        raise ValueError('기존 결과 스키마가 다릅니다.')
    if resolve_saved_path(meta['source_video']).resolve() != video.resolve():
        raise ValueError('기존 결과의 원본 영상 경로가 다릅니다.')
    signer, class_id = video.stem.split('_')
    if meta['signer_id'] != signer or int(meta['class_id']) != int(class_id):
        raise ValueError('기존 결과의 촬영자 또는 클래스가 다릅니다.')
    if meta.get('model_sha256') != model_hashes:
        raise ValueError('기존 결과와 현재 모델 파일이 다릅니다. 덮어쓰지 않습니다.')
    with np.load(coordinates, allow_pickle=False) as data:
        values = data['coordinates']
        mask = data['landmark_valid']
        timestamps = data['timestamps_seconds']
        visibility = data['pose_visibility']
        n = len(values)
        if not n or values.shape != (n, 177) or mask.shape != (n, 59) or visibility.shape != (n, 17) or timestamps.shape != (n,):
            raise ValueError('저장된 배열 크기가 올바르지 않습니다.')
        if not np.isfinite(timestamps).all() or (np.diff(timestamps) <= 0).any():
            raise ValueError('저장된 프레임 시각이 올바르지 않습니다.')
        if not np.array_equal(mask, np.isfinite(values.reshape(n, 59, 3)).all(axis=2)):
            raise ValueError('좌표와 검출 마스크가 일치하지 않습니다.')
        left = mask[:, :21].all(axis=1)
        right = mask[:, 21:42].all(axis=1)
        missing = ~left & ~right
        longest, run = 0, 0
        for flag in missing:
            run = run + 1 if flag else 0
            longest = max(longest, run)
        both_count = int(missing.sum())
        if meta['summary']['frame_count'] != n or meta['summary']['both_hands_missing_frames'] != both_count:
            raise ValueError('저장된 요약과 실제 배열이 다릅니다.')
        return {
            'frame_count': n,
            'left_present_pct': round(float(left.mean()) * 100, 2),
            'right_present_pct': round(float(right.mean()) * 100, 2),
            'both_missing_frames': both_count,
            'both_missing_pct': round(float(missing.mean()) * 100, 2),
            'longest_both_missing_run': longest,
            'pose_present_pct': round(float(mask[:, 42:].all(axis=1).mean()) * 100, 2),
            'shoulders_visible_pct': round(float((np.isfinite(visibility[:, [11, 12]]).all(axis=1) &
                (visibility[:, [11, 12]] >= 0.5).all(axis=1)).mean()) * 100, 2),
            'ambiguous_left_frames': meta['summary']['issues'].get('ambiguous_Left_frames', 0),
            'ambiguous_right_frames': meta['summary']['issues'].get('ambiguous_Right_frames', 0),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classes', nargs='+', type=int, default=[1, 13])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    extractor = root / 'extract_one_video.py'
    if not extractor.is_file():
        raise FileNotFoundError(f'먼저 extract_one_video.py를 복사하세요: {extractor}')
    model_hashes = {name: hashlib.sha256((root.parent / '04_데이터' / 'models' / name).read_bytes()).hexdigest()
                    for name in ('hand_landmarker.task', 'pose_landmarker_lite.task')}
    videos = []
    for class_id in sorted(set(args.classes)):
        directory = root.parent / '04_데이터' / 'ksl_data' / 'videos' / f'{class_id:02d}'
        members = sorted(p for p in directory.glob('*') if p.is_file() and p.suffix.lower() == '.mp4')
        if not members:
            raise FileNotFoundError(f'대상 영상이 없습니다: {directory}')
        videos.extend(members)
    report_path = root.parent / '04_데이터' / 'ksl_data' / 'extraction_report.csv'
    fields = ['video', 'class_id', 'signer_id', 'status', 'frame_count',
              'left_present_pct', 'right_present_pct', 'both_missing_frames',
              'both_missing_pct', 'longest_both_missing_run', 'pose_present_pct',
              'shoulders_visible_pct', 'ambiguous_left_frames', 'ambiguous_right_frames', 'error']
    rows = []
    print(f'대상: {len(videos)}개 / CPU 순차 처리 / 기존 좌표를 덮어쓰지 않습니다.', flush=True)
    for index, video in enumerate(videos, 1):
        row = {'video': str(video), 'status': 'failed', 'error': ''}
        print(f'\n[{index}/{len(videos)}] {video.parent.name}/{video.name}', flush=True)
        try:
            signer, class_text = video.stem.split('_')
            if int(class_text) != int(video.parent.name) or not signer.isdigit():
                raise ValueError('파일명과 분류 폴더를 확인하세요.')
            row.update(class_id=int(class_text), signer_id=signer)
            target = root.parent / '04_데이터' / 'ksl_data' / 'raw_coordinates' / f'{int(class_text):02d}'
            coordinates = target / f'{video.stem}.npz'
            metadata = coordinates.with_suffix('.json')
            exists = coordinates.exists() and metadata.exists()
            if not exists and (coordinates.exists() or metadata.exists()):
                raise ValueError('기존 결과가 일부만 있습니다. NPZ/JSON을 확인하세요. 자동 삭제하지 않습니다.')
            if not exists:
                process = subprocess.run([sys.executable, str(extractor), '--video', str(video)],
                                         capture_output=True, text=True, encoding='utf-8', errors='replace',
                                         env=child_environment())
                if process.returncode:
                    raise RuntimeError((process.stderr + '\n' + process.stdout)[-4000:])
            row.update(inspect_result(video, coordinates, metadata, model_hashes))
            row['status'] = 'reused' if exists else 'extracted'
            print(f"{row['status']} | {row['frame_count']}프레임 | 양손 미검출 {row['both_missing_pct']}%", flush=True)
        except Exception as exc:
            row['error'] = str(exc)
            print(f'실패: {exc}', flush=True)
        rows.append(row)
        # Save progress after every video; rerunning reuses completed outputs.
        ordered = sorted(rows, key=lambda r: (r['status'] != 'failed', -r.get('both_missing_pct', 0)))
        with report_path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ordered)
    failed = sum(row['status'] == 'failed' for row in rows)
    print(f'\n총 {len(rows)}개 / 성공 {len(rows) - failed}개 / 실패 {failed}개')
    print(f'검출 상태 표: {report_path}')
    print('표의 미검출률은 검토 우선순위이며, 수어 정확도나 자동 제외 기준이 아닙니다.')
    if failed:
        sys.exit(1)


def child_environment():
    import os
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


if __name__ == '__main__':
    main()
