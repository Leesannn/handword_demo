"""기존 원시 손·상체 결과를 재사용해 새 손 배정 규칙의 기준선 데이터 구성."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def read_checked(path,expected):
    path=Path(path)
    if digest(path)!=expected:raise ValueError(f'입력 파일 해시 불일치: {path}')
    return path


def main():
    import numpy as np
    from track_hands_v2_experiment import assign_v2
    from build_mediapipe177_pilot import assemble_hands
    from normalize_mediapipe177_pilot import normalize
    from resample_xy30_pilot import select_frames
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,default=root.parent / '04_데이터'/'ksl_data')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/assignment_v2_baseline_v1')
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError('결과가 이미 있습니다. 확인 후 다른 --output 경로를 사용하세요.')
    original=args.data_root/'mediapipe_baseline_v1'
    original_summary=json.loads((original/'preparation_summary.json').read_text(encoding='utf-8'))
    spec=json.loads((original/'preprocessing.json').read_text(encoding='utf-8'))
    if spec['preprocessing_version']!='mediapipe-xy59-mask59-nearest30-v1':raise ValueError('기존 데이터 버전을 확인하세요.')
    original_path=read_checked(original/'dataset.npz',original_summary['dataset_sha256'])
    with np.load(original_path,allow_pickle=False) as data:old={k:data[k].copy() for k in data.files}
    sources={r['sequence_id']:r for r in original_summary['source_files']}
    if len(sources)!=124 or len(old['X'])!=124:raise ValueError('기존124개 목록을 확인하세요.')
    features=[];masks=[];quality=[];provenance=[]
    for i,sequence in enumerate(old['sequence_id']):
        entry=sources[str(sequence)]
        final=read_checked(entry['source_npz'],entry['source_sha256'])
        final_meta=json.loads(final.with_suffix('.json').read_text(encoding='utf-8'))
        normalized=read_checked(final_meta['source_normalized'],final_meta['source_sha256'])
        read_checked(normalized.with_suffix('.json'),final_meta['source_metadata_sha256'])
        normalized_meta=json.loads(normalized.with_suffix('.json').read_text(encoding='utf-8'))
        combined=read_checked(normalized_meta['source_coordinates'],normalized_meta['source_sha256'])
        read_checked(combined.with_suffix('.json'),normalized_meta['source_metadata_sha256'])
        combined_meta=json.loads(combined.with_suffix('.json').read_text(encoding='utf-8'))
        raw_paths=[resolve_saved_path(p) for p in combined_meta['inputs_sha256'] if 'raw_hand_diagnostics' in resolve_saved_path(p).parts]
        if len(raw_paths)!=1:raise ValueError('원시 손 검출 파일을 특정할 수 없습니다.')
        raw_path=raw_paths[0];read_checked(raw_path,combined_meta['inputs_sha256'][str(raw_path)])
        raw=json.loads(raw_path.read_text(encoding='utf-8'))
        if raw['video_sha256']!=combined_meta['video_sha256']:raise ValueError('손·상체의 원본 영상이 다릅니다.')
        width,height=normalized_meta['video_width'],normalized_meta['video_height']
        assigned=assign_v2(raw['frames'],height/width)
        hands,_=assemble_hands(raw,{'frames':assigned})
        with np.load(combined,allow_pickle=False) as stored:
            points=stored['coordinates'].reshape(-1,59,3).copy()
            visibility=stored['pose_visibility'].copy()
            times=stored['timestamps_seconds'].copy();ids=stored['source_frame_indices'].copy();word=stored['word_interval_mask'].copy()
        if len(points)!=len(hands):raise ValueError('손·상체 프레임 수 불일치')
        original_pose=points[:,42:].copy();points[:,:42]=hands
        if not np.array_equal(points[:,42:],original_pose,equal_nan=True):raise ValueError('상체 좌표가 변경됐습니다.')
        valid=np.isfinite(points).all(axis=2)
        normalized_arrays,_=normalize(points,valid,visibility,width,height)
        normalized_arrays.update(source_frame_indices=ids,timestamps_seconds=times,word_interval_mask=word)
        selected,_=select_frames(normalized_arrays)
        if not np.array_equal(selected['source_frame_indices'],old['sampled_source_frame_indices'][i]):raise ValueError('선택 프레임 번호가 바뀌었습니다.')
        if not np.array_equal(selected['timestamps_seconds'],old['sampled_source_times_seconds'][i]):raise ValueError('선택 시각이 바뀌었습니다.')
        x=np.concatenate([selected['xy_zero_filled'].reshape(30,118),selected['joint_mask'].astype(np.float32)],axis=1)
        features.append(x);masks.append(selected['joint_mask'])
        def missing(mask):
            return int((~mask[:,:21].all(axis=1)).sum()),int((~mask[:,21:42].all(axis=1)).sum())
        before=missing(old['joint_mask'][i]);after=missing(selected['joint_mask'])
        quality.append({'sequence_id':str(sequence),'class_id':spec['class_names'][int(old['y'][i])],
                        'split':str(old['split'][i]),'subject_group':str(old['subject_group'][i]),
                        'before_left_missing':before[0],'before_right_missing':before[1],
                        'after_left_missing':after[0],'after_right_missing':after[1],
                        'net_hand_frame_gain':sum(before)-sum(after)})
        provenance.append({'sequence_id':str(sequence),'raw_path':str(raw_path),'raw_sha256':digest(raw_path),
                           'pose_source_npz':str(combined),'pose_source_sha256':digest(combined),
                           'original_final_npz':str(final),'original_final_sha256':digest(final)})
        if (i+1)%20==0:print(f'저장된 좌표로 새 배정 구성: {i+1}/124',flush=True)
    arrays={**old,'X':np.stack(features).astype(np.float32),'joint_mask':np.stack(masks)}
    if arrays['X'].shape!=(124,30,177) or not np.isfinite(arrays['X']).all():raise ValueError('새 기준선 배열 검증 실패')
    args.output.mkdir(parents=True,exist_ok=True)
    dataset=args.output/'dataset.npz';np.savez_compressed(dataset,**arrays)
    with np.load(dataset,allow_pickle=False) as saved:
        for k,v in arrays.items():
            if not np.array_equal(saved[k],v):raise ValueError(f'저장 후 재읽기 불일치: {k}')
    new_spec={**spec,'preprocessing_version':'mediapipe-xy59-mask59-nearest30-assignment-v2-v1',
              'source_preprocessing_version':spec['preprocessing_version'],
              'assignment_version':'single-label-restart-shadow-v2',
              'assignment_script_sha256':digest(root/'track_hands_v2_experiment.py'),
              'assignment_settings':{'max_gap':5,'max_distance':.25,'min_margin':.04,'label_score_min':.7},
              'production_contract_change':False}
    (args.output/'preprocessing.json').write_text(json.dumps(new_spec,ensure_ascii=False,indent=2),encoding='utf-8')
    with (args.output/'quality_comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(quality[0]));writer.writeheader();writer.writerows(quality)
    summary={'samples':124,'source_dataset_sha256':digest(original_path),'dataset_sha256':digest(dataset),
             'split_counts':dict(Counter(old['split'].tolist())),
             'samples_with_more_hand_observations':sum(r['net_hand_frame_gain']>0 for r in quality),
             'samples_with_fewer_hand_observations':sum(r['net_hand_frame_gain']<0 for r in quality),
             'net_hand_frame_gain':sum(r['net_hand_frame_gain'] for r in quality),'sources':provenance,
             'new_mediapipe_inference':False,'training':False,'original_dataset_changed':False,
             'limitations':['보존한 좌표 증가가 좌표 정확도나 분류 성능 향상을 보장하지 않음.',
                            '공간 정규화·동작 구간·선택 프레임·촬영 코드 분할을 유지하고 손 배정만 변경함.',
                            '학습과 새 영상 예측 양쪽에 같은 버전을 적용해야 하며 아직 기존 예측 도구에는 연결하지 않음.']}
    (args.output/'preparation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('구성 완료:',arrays['X'].shape,'/ 저장 후 재읽기 통과')
    print('손 관측 증가 영상:',summary['samples_with_more_hand_observations'],'/ 감소 영상:',summary['samples_with_fewer_hand_observations'])
    print('선택 프레임의 손 관측 순증가:',summary['net_hand_frame_gain'])
    print('결과:',args.output.resolve())
    print('영상 재추론·기존 모델 변경·학습 없음.')


if __name__=='__main__':main()
