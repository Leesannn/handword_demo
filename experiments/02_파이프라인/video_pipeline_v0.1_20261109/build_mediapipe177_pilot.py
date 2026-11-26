"""Combine reviewed hand assignments with newly extracted Pose[0:17].

One experimental video, no normalization, interpolation, resampling or training.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def assemble_hands(raw, pilot):
    import numpy as np
    if len(raw['frames']) != len(pilot['frames']):
        raise ValueError('원시 검출과 손 배정의 프레임 수가 다릅니다.')
    n = len(raw['frames'])
    hands = np.full((n,42,3), np.nan, dtype=np.float32)
    detection_ids = np.full((n,2), -1, dtype=np.int16)
    for i,(frame,row) in enumerate(zip(raw['frames'],pilot['frames'])):
        if frame['frame_number'] != i+1 or row['frame_number'] != i+1:
            raise ValueError('프레임 번호가 순서대로 연결되지 않습니다.')
        detections = {d['detection_index']:d for d in frame['detections']}
        if len(detections) != len(frame['detections']):
            raise ValueError('중복 검출 번호입니다.')
        used_sides, used_ids = set(),set()
        for a in row['assignments']:
            side,det_id = a['side'],a['detection_index']
            if side not in ('Left','Right') or side in used_sides or det_id in used_ids or det_id not in detections:
                raise ValueError(f'{i+1}번의 손 배정이 올바르지 않습니다.')
            points = np.asarray(detections[det_id]['landmarks'],dtype=np.float32)
            if points.shape != (21,3) or not np.isfinite(points).all():
                raise ValueError('배정된 손 좌표 형식이 올바르지 않습니다.')
            slot = 0 if side == 'Left' else 1
            hands[i,slot*21:(slot+1)*21] = points
            detection_ids[i,slot] = det_id
            used_sides.add(side); used_ids.add(det_id)
    return hands,detection_ids


def validate_arrays(arrays, hands):
    import numpy as np
    n = len(hands)
    coords = arrays['coordinates']
    if coords.shape != (n,177) or arrays['landmark_valid'].shape != (n,59):
        raise ValueError('177개 좌표 또는 59개 마스크 크기가 다릅니다.')
    points = coords.reshape(n,59,3)
    if not np.array_equal(points[:,:42],hands,equal_nan=True):
        raise ValueError('원시 손 좌표와 저장할 손 좌표가 다릅니다.')
    if not np.array_equal(arrays['landmark_valid'],np.isfinite(points).all(axis=2)):
        raise ValueError('좌표와 검출 마스크가 일치하지 않습니다.')
    if not np.isnan(points[~arrays['landmark_valid']]).all():
        raise ValueError('미검출은 세 좌표 모두 NaN이어야 합니다.')
    if arrays['pose_visibility'].shape != (n,17) or arrays['pose_presence'].shape != (n,17):
        raise ValueError('상체 보조 정보 크기가 다릅니다.')


def main():
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument('--raw',type=Path,default=root/'ksl_data/raw_hand_diagnostics/12/NIA_SL_WORD0815_REAL12_F.json')
    parser.add_argument('--pilot',type=Path,help='생략하면 같은 영상의 가장 최근 배정 결과 사용')
    parser.add_argument('--segment',type=Path,help='기존 라벨 구간 메타데이터 JSON')
    args = parser.parse_args()
    raw_path = args.raw.resolve()
    raw = json.loads(raw_path.read_text(encoding='utf-8'))
    if raw.get('schema_version') != 'raw-hand-review-v1':
        raise ValueError('지원하지 않는 원시 진단 형식입니다.')
    sequence = raw_path.stem
    if args.pilot:
        pilot_path = args.pilot.resolve()
    else:
        candidates = list((root/'ksl_data/hand_tracking_pilot').glob(f'{sequence}_*.json'))
        if not candidates: raise FileNotFoundError('먼저 손 배정 실험을 실행하세요.')
        pilot_path = max(candidates,key=lambda p:p.stat().st_mtime).resolve()
    pilot = json.loads(pilot_path.read_text(encoding='utf-8'))
    if Path(pilot['source_raw']).resolve() != raw_path:
        raise ValueError('손 배정 결과가 참조하는 원시 파일이 다릅니다.')
    if args.segment:
        segment_path = args.segment.resolve()
    else:
        candidates = list((root/'ksl_data/aihub_word_segments').rglob(f'{sequence}.json'))
        if len(candidates) != 1: raise ValueError('라벨 구간 메타데이터를 하나로 특정할 수 없습니다.')
        segment_path = candidates[0].resolve()
    segment = json.loads(segment_path.read_text(encoding='utf-8'))
    video = Path(raw['source_video']).resolve()
    model_path = root/'models/pose_landmarker_lite.task'
    if not model_path.is_file(): raise FileNotFoundError(model_path)
    if Path(segment['source_video']).resolve() != video or segment['sequence_id'] != sequence:
        raise ValueError('라벨 구간의 영상이 다릅니다.')
    if sha256(video) != raw['video_sha256']:
        raise ValueError('손 추출 이후 원본 영상 내용이 변경됐습니다.')
    source_hashes = {str(p):sha256(p) for p in (raw_path,pilot_path,segment_path,model_path)}
    hands,det_ids = assemble_hands(raw,pilot)
    n = len(hands)
    if n == 0: raise ValueError('빈 영상입니다.')
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    cap = cv2.VideoCapture(str(video))
    pose = np.full((n,17,3),np.nan,dtype=np.float32)
    visibility = np.full((n,17),np.nan,dtype=np.float32)
    presence = np.full((n,17),np.nan,dtype=np.float32)
    model_bytes = model_path.read_bytes()
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_buffer=model_bytes),
        running_mode=vision.RunningMode.VIDEO,num_poses=1)
    try:
        if not cap.isOpened(): raise RuntimeError('영상 열기 실패')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or not 0 < fps <= 240 or abs(fps-raw['fps'])>1e-5 or abs(fps-segment['fps_from_preflight'])>1e-5:
            raise ValueError('영상 FPS와 기존 결과가 다릅니다.')
        count = 0
        with vision.PoseLandmarker.create_from_options(options) as detector:
            while True:
                ok,bgr = cap.read()
                if not ok: break
                if count>=n: raise ValueError('손 결과보다 영상 프레임이 많습니다.')
                timestamp = round(count*1000/fps)
                if raw['frames'][count]['timestamp_ms'] != timestamp:
                    raise ValueError('손과 상체 추출의 프레임 시각이 다릅니다.')
                image = mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)))
                result = detector.detect_for_video(image,timestamp)
                if result.pose_landmarks:
                    points = result.pose_landmarks[0]
                    if len(points)<17: raise ValueError('상체 관절 수가 부족합니다.')
                    pose[count] = [[p.x,p.y,p.z] for p in points[:17]]
                    visibility[count] = [p.visibility if p.visibility is not None else np.nan for p in points[:17]]
                    presence[count] = [p.presence if p.presence is not None else np.nan for p in points[:17]]
                count+=1
                if count%30==0: print(f'상체 추출: {count}/{n}프레임',flush=True)
        if count!=n: raise ValueError(f'영상 {count}프레임, 손 결과 {n}프레임: 저장하지 않습니다.')
    finally:
        cap.release()
    pose[~np.isfinite(pose).all(axis=2)] = np.nan
    combined = np.concatenate((hands,pose),axis=1)
    times = np.arange(n,dtype=np.float64)/fps
    in_word = (times>=segment['label_start_seconds']) & (times<segment['label_end_seconds'])
    arrays = {'coordinates':combined.reshape(n,177),'landmark_valid':np.isfinite(combined).all(axis=2),
              'pose_visibility':visibility,'pose_presence':presence,'source_frame_indices':np.arange(n,dtype=np.int64),
              'timestamps_seconds':times,'word_interval_mask':in_word,'hand_detection_indices':det_ids}
    validate_arrays(arrays,hands)
    if not in_word.any(): raise ValueError('단어 구간이 비어 있습니다.')
    for p,h in source_hashes.items():
        if sha256(Path(p))!=h: raise ValueError('추출 중 입력 파일이 변경됐습니다.')
    if sha256(video)!=raw['video_sha256']: raise ValueError('추출 중 영상이 변경됐습니다.')
    valid = arrays['landmark_valid']
    summary = {'frames_total':n,'features_per_frame':177,'word_frames':int(in_word.sum()),
               'word_left_hand_missing_frames':int((~valid[in_word,:21].all(axis=1)).sum()),
               'word_right_hand_missing_frames':int((~valid[in_word,21:42].all(axis=1)).sum()),
               'word_both_hands_missing_frames':int((~valid[in_word,:42].any(axis=1)).sum()),
               'word_pose17_finite_frames':int(valid[in_word,42:].all(axis=1).sum()),
               'word_shoulders_visibility_ge_0_5_frames':int((np.isfinite(visibility[in_word][:,[11,12]]).all(axis=1)&(visibility[in_word][:,[11,12]]>=.5).all(axis=1)).sum())}
    metadata = {'schema_version':'mediapipe177-assigned-pilot-v1','source_video':str(video),'video_sha256':raw['video_sha256'],
                'sequence_id':sequence,'class_id':segment['class_id'],'signer_group':segment['signer_group'],
                'signer_identity_verified':False,'split':'unassigned','fps':fps,'timestamp_basis':'frame_index / metadata FPS; assumes constant frame rate',
                'landmark_order':'Left hand 0..20, Right hand 0..20, MediaPipe Pose 0..16; each xyz',
                'coordinate_space':'MediaPipe image landmarks, no mirroring; raw hand and pose z have different origins; not a common metric 3D skeleton',
                'missing_value':'NaN; landmark_valid is finite-coordinate availability, NOT geometric accuracy',
                'pose_policy':'finite coordinates retained; visibility and presence saved separately; no visibility filtering',
                'hand_assignment_settings':pilot['settings'],'hand_assignment_limitation':'Model-seeded anatomical labels and heuristic temporal matching; not fully validated. Pilot lacked extraction-time source hash.',
                'inputs_sha256':source_hashes,'hand_model_sha256_from_raw':raw['hand_model_sha256'],
                'versions':{'numpy':np.__version__,'opencv':cv2.__version__,'mediapipe':mp.__version__},
                'label_start_seconds':segment['label_start_seconds'],'label_end_seconds':segment['label_end_seconds'],
                'normalization':'none','resampling':'none','interpolation':'none','training':False,'summary':summary}
    output = root/'ksl_data/mediapipe177_pilot'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True,exist_ok=False)
    npz_path = output/f'{sequence}.npz'
    np.savez_compressed(npz_path,**arrays)
    with np.load(npz_path,allow_pickle=False) as loaded:
        for key,value in arrays.items():
            if not np.array_equal(loaded[key],value,equal_nan=True):
                raise ValueError(f'저장 후 재읽기 불일치: {key}')
    metadata['array_sha256'] = sha256(npz_path)
    metadata['save_reload_verified'] = True
    json_path = output/f'{sequence}.json'
    json_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== 177개 원시 좌표 저장 완료 ===')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('배열 크기:',arrays['coordinates'].shape)
    print('저장 후 재읽기 검사: 통과')
    print('NPZ:',npz_path)
    print('JSON:',json_path)
    print('전체 영상과 단어 구간 마스크를 보존했습니다. 정규화·30프레임 변환·학습은 하지 않았습니다.')


if __name__=='__main__':main()
