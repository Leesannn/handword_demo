"""Check selected videos, label intervals and coordinate names before preprocessing."""
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


def inspect_row(row, cv2):
    video = resolve_saved_path(row['video'])
    folder = resolve_saved_path(row['tracking_folder'])
    label_path = resolve_saved_path(row['label_path'])
    if not video.is_file() or not folder.is_dir() or not label_path.is_file():
        raise FileNotFoundError('영상 또는 좌표 폴더 또는 라벨 경로가 없습니다.')
    if row['angle'] != video.stem.rsplit('_', 1)[-1]:
        raise ValueError('목록의 각도와 파일명이 다릅니다.')
    labels = json.loads(label_path.read_text(encoding='utf-8-sig'))
    if Path(labels['metaData']['name']).name != video.name:
        raise ValueError('라벨의 영상 이름과 실제 파일명이 다릅니다.')
    segments = labels.get('data', [])
    if len(segments) != 1:
        raise ValueError(f'단어 구간이 {len(segments)}개입니다. 구간 선택 검토가 필요합니다.')
    segment = segments[0]
    start, end = float(segment['start']), float(segment['end'])
    if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
        raise ValueError('라벨 시작/종료 시각이 올바르지 않습니다.')
    cap = cv2.VideoCapture(str(video.resolve()))
    try:
        if not cap.isOpened():
            raise RuntimeError('영상을 열 수 없습니다.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        first_ok, _ = cap.read()
    finally:
        cap.release()
    if not first_ok or not math.isfinite(fps) or fps <= 0 or count <= 0 or width <= 0 or height <= 0:
        raise ValueError('첫 프레임 디코딩 또는 영상 메타데이터 확인 실패')
    if end > count / fps + 1 / fps:
        raise ValueError('라벨 종료 시각이 영상 범위를 벗어납니다.')
    pattern = re.compile(re.escape(video.stem) + r'_(\d+)_keypoints\.json$')
    ids = []
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name)
        if path.is_file() and match:
            ids.append(int(match.group(1)))
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('좌표 프레임이 없거나 동일 번호가 중복됩니다.')
    if max(ids) >= count:
        raise ValueError('좌표 번호가 영상 메타데이터 프레임 범위를 벗어납니다.')
    available = set(ids)
    selected = [i for i in range(count) if start <= i / fps < end]
    if not selected:
        raise ValueError('라벨 시간 구간에 프레임이 없습니다.')
    present = [i for i in selected if i in available]
    missing = [i for i in selected if i not in available]
    if not present:
        raise ValueError('동작 구간 전체에 좌표 파일이 없습니다.')
    # Sample one actual JSON in the selected interval; this is not full quality validation.
    sample = next(path for path in folder.iterdir()
                  if pattern.fullmatch(path.name) and int(pattern.fullmatch(path.name).group(1)) == present[0])
    data = json.loads(sample.read_text(encoding='utf-8-sig'))
    person = data['people']
    if isinstance(person, list):
        if len(person) != 1:
            raise ValueError('좌표 샘플의 사람 수가 한 명이 아닙니다.')
        person = person[0]
    for field, expected in [('hand_left_keypoints_2d', 63), ('hand_right_keypoints_2d', 63), ('pose_keypoints_2d', 75)]:
        values = person[field]
        if len(values) != expected or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in values):
            raise ValueError(f'좌표 샘플 구조가 예상과 다릅니다: {field}')
    warnings = []
    if missing:
        warnings.append('missing_coordinates_in_label_interval')
    if len(ids) < count:
        warnings.append('coordinate_files_fewer_than_video_frames')
    return {
        'status': 'checked_with_warning' if warnings else 'checked',
        'fps': fps, 'video_frames_metadata': count, 'width': width, 'height': height,
        'label_start_seconds': start, 'label_end_seconds': end,
        'source_label_names': '|'.join(str(a.get('name', '')) for a in segment.get('attributes', [])),
        'interval_first_frame_0based': selected[0], 'interval_last_frame_0based': selected[-1],
        'interval_frames_expected': len(selected), 'interval_frames_available': len(present),
        'interval_missing_indices_0based': '|'.join(map(str, missing)),
        'warnings': '|'.join(warnings), 'error': '',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--angle', default='F', choices=['F', 'D', 'L', 'R', 'U'])
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'aihub_preflight')
    args = parser.parse_args()
    import cv2
    with args.manifest.open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['angle'] == args.angle]
    if not rows:
        raise ValueError('해당 각도의 데이터가 없습니다.')
    if len({row['video'] for row in rows}) != len(rows):
        raise ValueError('중복 영상 경로가 있습니다.')
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report_path = args.output / f'input_check_{args.angle}_{stamp}.csv'
    extra = ['status', 'fps', 'video_frames_metadata', 'width', 'height', 'label_start_seconds',
             'label_end_seconds', 'source_label_names', 'interval_first_frame_0based',
             'interval_last_frame_0based', 'interval_frames_expected', 'interval_frames_available',
             'interval_missing_indices_0based', 'warnings', 'error']
    fields = list(rows[0]) + [name for name in extra if name not in rows[0]]
    result = []
    for index, row in enumerate(rows, 1):
        item = dict(row)
        try:
            item.update(inspect_row(row, cv2))
        except Exception as exc:
            item.update(status='needs_review', error=str(exc))
        result.append(item)
        print(f"[{index}/{len(rows)}] {resolve_saved_path(row['video']).stem}: {item['status']}", flush=True)
        with report_path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(result)
    counts = collections.Counter(row['status'] for row in result)
    summary = {
        'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'selected_angle': args.angle, 'sequences': len(rows), 'status_counts': dict(counts),
        'by_class': dict(collections.Counter(row['preparation_class_id'] for row in rows)),
        'opencv_version': cv2.__version__,
        'scope': 'Metadata, first video frame, label interval, keypoint filenames and one coordinate JSON per sequence checked. Not full video decode, VFR detection, temporal alignment or landmark quality validation.',
        'time_assumption': 'Constant frame rate; coordinate number 0 corresponds to video frame 0. Assumption not independently verified.',
        'missing_policy': 'Keep source indices. Missing coordinates remain a warning, not an automatic rejection. No arrays or masks generated by this check.',
        'report': str(report_path.resolve()),
    }
    report_path.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n=== 검사 요약 ===')
    print(f"대상 {len(rows)}개 / 검사 통과 {counts['checked']}개 / 경고 포함 {counts['checked_with_warning']}개 / 확인 필요 {counts['needs_review']}개")
    print(f'검사표: {report_path.resolve()}')
    print('누락 경고는 유지합니다. 아직 전처리 배열 생성이나 모델 학습을 실행하지 않았습니다.')


if __name__ == '__main__':
    main()
