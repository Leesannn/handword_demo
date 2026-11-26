"""단어 구간에서 30프레임 선택. 미검출 보존, 보간·학습 없음."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_frames(data, count=30):
    import numpy as np
    xy,mask=data['normalized_xy'],data['joint_mask']
    n=len(xy)
    if xy.shape!=(n,59,2) or mask.shape!=(n,59) or mask.dtype!=np.bool_:
        raise ValueError('좌표 또는 검출 마스크 크기·형식이 다릅니다.')
    if not np.array_equal(mask,np.isfinite(xy).all(axis=2)) or not np.isnan(xy[~mask]).all():
        raise ValueError('좌표와 미검출 마스크가 일치하지 않습니다.')
    for key in ('word_interval_mask','normalizable_frame','source_frame_indices','timestamps_seconds'):
        if data[key].shape!=(n,):raise ValueError(f'프레임 수 불일치: {key}')
    if data['word_interval_mask'].dtype!=np.bool_:raise ValueError('단어 구간 마스크는 불리언이어야 합니다.')
    if not np.isfinite(data['timestamps_seconds']).all():raise ValueError('프레임 시각에 비정상 값이 있습니다.')
    if np.any(np.diff(data['source_frame_indices'])<=0) or np.any(np.diff(data['timestamps_seconds'])<=0):
        raise ValueError('원본 프레임 번호 또는 시각이 증가하지 않습니다.')
    word=np.flatnonzero(data['word_interval_mask'])
    if not len(word):raise ValueError('단어 구간이 비어 있습니다.')
    if len(word)>1 and np.any(np.diff(word)!=1):raise ValueError('단어 구간이 연속적이지 않습니다.')
    positions=np.rint(np.linspace(0,len(word)-1,count)).astype(np.int64)
    selected=word[positions]
    result={'normalized_xy':xy[selected].copy(),'joint_mask':mask[selected].copy(),
            'normalizable_frame':data['normalizable_frame'][selected].copy(),
            'source_frame_indices':data['source_frame_indices'][selected].copy(),
            'timestamps_seconds':data['timestamps_seconds'][selected].copy(),
            'selected_input_row_indices':selected,'selected_word_row_indices':positions}
    # NaN 좌표와 별도로, 마스크와 함께 사용할 0 채움 후보 배열을 만든다.
    result['xy_zero_filled']=np.where(result['joint_mask'][...,None],result['normalized_xy'],0).astype(np.float32)
    if not np.isfinite(result['xy_zero_filled']).all():raise ValueError('0 채움 배열에 비정상 값이 있습니다.')
    if result['normalized_xy'].shape!=(count,59,2):raise ValueError('30프레임 크기가 올바르지 않습니다.')
    return result,word


def main():
    import numpy as np
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--normalized',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.normalized:path=args.normalized.resolve()
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/normalized_xy_pilot').rglob('NIA_SL_WORD0815_REAL12_F.npz'))
        if not files:raise FileNotFoundError('정규화 결과가 없습니다.')
        path=max(files,key=lambda p:p.stat().st_mtime).resolve()
    meta_path=path.with_suffix('.json')
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    source_hash=digest(path)
    if meta.get('schema_version')!='mediapipe59-xy-shoulder-pilot-v1' or meta['output_sha256']!=source_hash:
        raise ValueError('정규화 형식 또는 해시가 다릅니다.')
    with np.load(path,allow_pickle=False) as saved:data={k:saved[k].copy() for k in saved.files}
    result,word=select_frames(data)
    def counts(mask):
        return {'left_hand_unavailable':int((~mask[:,:21].all(axis=1)).sum()),
                'right_hand_unavailable':int((~mask[:,21:42].all(axis=1)).sum()),
                'both_hands_unavailable':int((~mask[:,:42].any(axis=1)).sum())}
    summary={'input_total_frames':len(data['normalized_xy']),'input_word_frames':len(word),'output_frames':30,
             'distinct_selected_frames':int(len(np.unique(result['source_frame_indices']))),
             'normalizable_selected_frames':int(result['normalizable_frame'].sum()),
             'before_selection':counts(data['joint_mask'][word]),'after_selection':counts(result['joint_mask']),
             'selected_source_frames_1based':(result['source_frame_indices']+1).tolist()}
    target=args.output or root.parent / '04_데이터'/'ksl_data/xy30_pilot'
    target=target/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True,exist_ok=False)
    output=target/f'{path.stem}.npz'
    np.savez_compressed(output,**result)
    with np.load(output,allow_pickle=False) as saved:
        for key,value in result.items():
            if not np.array_equal(saved[key],value,equal_nan=True):raise ValueError(f'재읽기 불일치: {key}')
    if digest(path)!=source_hash:raise ValueError('원본 정규화 파일이 변경됐습니다.')
    info={'schema_version':'mediapipe59-xy-nearest30-pilot-v1','source_normalized':str(path),
          'source_sha256':source_hash,'source_metadata_sha256':digest(meta_path),'output_sha256':digest(output),
          'sampling':'단어 구간의 처음부터 끝까지 균등한 30개 위치를 np.rint로 가장 가까운 원본 행에 대응. 30프레임보다 짧으면 같은 행을 반복 선택.',
          'missing_policy':'원래 NaN 좌표와 마스크 보존. 별도의 xy_zero_filled는 반드시 joint_mask와 함께 사용. 미검출 좌표 복원 없음.',
          'timing_policy':'원본 프레임 번호와 시각 보존. 선택 결과는 고정 30FPS 영상이 아님.',
          'z_policy':meta['z_policy'],'training':False,'production_contract_change':False,
          'summary':summary,'save_reload_verified':True}
    output.with_suffix('.json').write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== 30프레임 선택 완료 ===')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('배열 크기:',result['normalized_xy'].shape)
    print('저장 후 재읽기 검사: 통과')
    print('원본 변경·좌표 보간·모델 학습 없음. 선택되지 않은 프레임의 누락이 사라져도 검출 개선은 아닙니다.')
    print('저장:',output)


if __name__=='__main__':main()
