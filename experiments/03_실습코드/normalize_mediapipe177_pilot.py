"""Experimental shoulder-centered XY normalization; preserves source177 file."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def normalize(points,valid,visibility,width,height):
    import numpy as np
    if points.ndim!=3 or points.shape[1:]!=(59,3) or valid.shape!=points.shape[:2] or visibility.shape!=(len(points),17):
        raise ValueError('좌표 또는 보조 정보 크기가 다릅니다.')
    if width<=0 or height<=0:raise ValueError('영상 크기가 올바르지 않습니다.')
    pixels=points[:,:,:2].astype(np.float64)*np.array([width,height])
    shoulders=pixels[:,[53,54]]  # 42 hand points + Pose[11,12]
    center=shoulders.mean(axis=1)
    scale=np.linalg.norm(shoulders[:,0]-shoulders[:,1],axis=1)
    usable=valid[:,[53,54]].all(axis=1)&np.isfinite(shoulders).all(axis=(1,2))&np.isfinite(visibility[:,[11,12]]).all(axis=1)&(visibility[:,[11,12]]>=.5).all(axis=1)&(scale>1.)
    mask=valid&np.isfinite(pixels).all(axis=2)&usable[:,None]
    xy=np.full(pixels.shape,np.nan,dtype=np.float32)
    xy[usable]=((pixels[usable]-center[usable,None,:])/scale[usable,None,None]).astype(np.float32)
    xy[~mask]=np.nan
    inverse=xy.astype(np.float64)*scale[:,None,None]+center[:,None,:]
    errors=np.linalg.norm(inverse-pixels,axis=2)[mask]
    if not errors.size:raise ValueError('정규화할 유효 관절이 없습니다.')
    maximum=float(errors.max())
    if maximum>.02:raise ValueError(f'복원 차이가 실험 허용값 0.02px를 넘었습니다: {maximum}')
    return {'normalized_xy':xy,'joint_mask':mask,'normalizable_frame':usable,'shoulder_center_pixels':center,'shoulder_width_pixels':scale},maximum


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--coordinates',type=Path)
    args=parser.parse_args()
    if args.coordinates:path=args.coordinates.resolve()
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/mediapipe177_pilot').rglob('NIA_SL_WORD0815_REAL12_F.npz'))
        if not files:raise FileNotFoundError('177개 좌표 결과가 없습니다.')
        path=max(files,key=lambda p:p.stat().st_mtime).resolve()
    source_meta=path.with_suffix('.json')
    meta=json.loads(source_meta.read_text(encoding='utf-8'))
    source_hash=digest(path)
    if meta.get('schema_version')!='mediapipe177-assigned-pilot-v1' or source_hash!=meta['array_sha256']:
        raise ValueError('원본 좌표 형식 또는 해시를 확인하세요.')
    import numpy as np
    with np.load(path,allow_pickle=False) as saved:
        raw={k:saved[k].copy() for k in saved.files}
    points=raw['coordinates'].reshape(-1,59,3)
    if not np.array_equal(raw['landmark_valid'],np.isfinite(points).all(axis=2)):
        raise ValueError('원본 검출 마스크가 좌표와 다릅니다.')
    video=resolve_saved_path(meta['source_video'])
    if digest(video)!=meta['video_sha256']:raise ValueError('원본 영상이 변경됐습니다.')
    import cv2
    cap=cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():raise RuntimeError('영상 크기를 확인할 수 없습니다.')
        width,height=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:cap.release()
    arrays,error=normalize(points,raw['landmark_valid'],raw['pose_visibility'],width,height)
    for key in ('source_frame_indices','timestamps_seconds','word_interval_mask'):
        arrays[key]=raw[key]
    word=arrays['word_interval_mask'];mask=arrays['joint_mask']
    n=len(points)
    left=mask[:,:21].all(axis=1);right=mask[:,21:42].all(axis=1)
    summary={'frames_total':n,'joints_per_frame':59,'xy_values_per_frame':118,'word_frames':int(word.sum()),
             'normalizable_word_frames':int(arrays['normalizable_frame'][word].sum()),
             'word_left_hand_missing_frames':int((~left[word]).sum()),'word_right_hand_missing_frames':int((~right[word]).sum()),
             'max_inverse_difference_pixels':error}
    target=root.parent / '04_데이터'/'ksl_data/normalized_xy_pilot'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True,exist_ok=False)
    output=target/f'{path.stem}.npz'
    np.savez_compressed(output,**arrays)
    with np.load(output,allow_pickle=False) as saved:
        for key,value in arrays.items():
            if not np.array_equal(saved[key],value,equal_nan=True):raise ValueError(f'재읽기 불일치: {key}')
    if digest(path)!=source_hash:raise ValueError('작업 중 원본 좌표가 변경됐습니다.')
    info={'schema_version':'mediapipe59-xy-shoulder-pilot-v1','source_coordinates':str(path),'source_sha256':source_hash,
          'source_metadata_sha256':digest(source_meta),'video_width':width,'video_height':height,
          'joint_order':meta['landmark_order'],'coordinate_order':'59 joints, xy only; shape(T,59,2)',
          'center':'Per-frame midpoint of MediaPipe Pose[11,12], in pixels',
          'scale':'Per-frame Euclidean shoulder width in pixels; aspect ratio accounted for',
          'shoulder_gate':{'visibility_min':.5,'width_pixels_min_exclusive':1.,'validated_for_classification':False},
          'missing_policy':'NaN plus joint_mask; invalid shoulder reference makes whole frame unavailable; no interpolation or forward filling',
          'z_policy':'Not included in this XY experiment; all original xyz preserved in source NPZ. No common hand/pose z origin assumed.',
          'resampling':'none','training':False,'production_contract_change':False,'summary':summary,
          'output_sha256':digest(output),'save_reload_verified':True}
    output.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== XY 정규화 실험 완료 ===')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('배열 크기:',arrays['normalized_xy'].shape)
    print('저장 후 재읽기 검사: 통과')
    print('원본 177개 좌표 변경 없음. z 변환·30프레임 변환·학습 없음.')
    print('저장:',output)


if __name__=='__main__':main()
