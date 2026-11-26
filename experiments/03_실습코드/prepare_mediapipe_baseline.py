"""124개 MediaPipe 배치 결과의 검사·품질 집계·기존 촬영 코드 분할 유지."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import numpy as np
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--data-root',type=Path,default=root.parent / '04_데이터'/'ksl_data')
    parser.add_argument('--batch-report',type=Path)
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/mediapipe_baseline_v1')
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError('결과 폴더가 이미 있습니다. 확인 후 다른 --output 경로를 사용하세요.')
    if args.batch_report:batch_path=args.batch_report.resolve()
    else:
        reports=[]
        for p in (args.data_root/'mediapipe_batch_v1').glob('batch_*.json'):
            d=json.loads(p.read_text(encoding='utf-8'))
            if d.get('scope')=='all' and d['planned']==d['processed']==124 and len(d['results'])==124 and all(r['status'] in ('created','reused') for r in d['results']):reports.append(p)
        if not reports:raise ValueError('완료된 전체 124개 배치 보고서가 없습니다.')
        batch_path=max(reports,key=lambda p:p.stat().st_mtime).resolve()
    batch=json.loads(batch_path.read_text(encoding='utf-8'))
    old_root=args.data_root/'aihub_baseline_v1'
    old_spec_path=old_root/'preprocessing.json';old_path=old_root/'dataset.npz'
    old_spec=json.loads(old_spec_path.read_text(encoding='utf-8'))
    classes=old_spec['class_names']
    with np.load(old_path,allow_pickle=False) as old:
        ids=old['sequence_id'].copy();splits=old['split'].copy();groups=old['subject_group'].copy();labels=old['y'].copy()
    if len(set(ids.tolist()))!=124 or len(ids)!=124:raise ValueError('기존 124개 분할을 확인하세요.')
    by_id={r['sequence_id']:r for r in batch['results']}
    if len(by_id)!=124 or set(by_id)!=set(ids.tolist()):raise ValueError('기존 실험과 배치의 표본 구성이 다릅니다.')
    all_x,all_masks,all_frames,all_times,rows,provenance=[],[],[],[],[],[]
    for i,sequence in enumerate(ids):
        row=by_id[str(sequence)]
        if row['status'] not in ('created','reused') or row['class_id']!=classes[int(labels[i])] or row['signer_group']!=str(groups[i]):
            raise ValueError(f'라벨·그룹·상태 불일치: {sequence}')
        path=resolve_saved_path(row['final_npz']).resolve()
        receipt_path=args.data_root/'mediapipe_batch_v1'/str(sequence)/'complete.json'
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if resolve_saved_path(receipt['final_npz']).resolve()!=path:raise ValueError(f'완료 기록과 최종 파일이 다릅니다: {sequence}')
        for p,h in receipt['outputs_sha256'].items():
            if not resolve_saved_path(p).is_file() or digest(resolve_saved_path(p))!=h:raise ValueError(f'입력·출력 파일 변경: {p}')
        meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if meta['schema_version']!='mediapipe59-xy-nearest30-pilot-v1' or digest(path)!=meta['output_sha256']:raise ValueError('최종 결과의 형식·해시 불일치')
        with np.load(path,allow_pickle=False) as saved:
            xy=saved['normalized_xy'].copy();mask=saved['joint_mask'].copy();zero=saved['xy_zero_filled'].copy()
            frames=saved['source_frame_indices'].copy();times=saved['timestamps_seconds'].copy()
            usable=saved['normalizable_frame'].copy()
        if xy.shape!=(30,59,2) or mask.shape!=(30,59) or zero.shape!=xy.shape:raise ValueError('배열 크기 불일치')
        if not np.array_equal(mask,np.isfinite(xy).all(axis=2)) or not np.isnan(xy[~mask]).all():raise ValueError('미검출 정보 불일치')
        if not np.array_equal(zero,np.where(mask[...,None],xy,0)) or not np.isfinite(zero).all():raise ValueError('0 채움 정보 불일치')
        if frames.shape!=(30,) or times.shape!=(30,) or not np.isfinite(times).all() or np.any(np.diff(frames)<0) or np.any(np.diff(times)<0):raise ValueError('원본 시각·프레임 순서 불일치')
        features=np.concatenate([zero.reshape(30,118),mask.astype(np.float32)],axis=1)
        all_x.append(features);all_masks.append(mask);all_frames.append(frames);all_times.append(times)
        raw_paths=[resolve_saved_path(p) for p in receipt['outputs_sha256'] if 'raw_hand_diagnostics' in resolve_saved_path(p).parts]
        pilot_paths=[resolve_saved_path(p) for p in receipt['outputs_sha256'] if 'hand_tracking_pilot' in resolve_saved_path(p).parts]
        if len(raw_paths)!=1 or len(pilot_paths)!=1:raise ValueError('진단 파일 경로를 특정할 수 없습니다.')
        raw=json.loads(raw_paths[0].read_text(encoding='utf-8'));pilot=json.loads(pilot_paths[0].read_text(encoding='utf-8'))
        first,last=int(frames[0])+1,int(frames[-1])+1
        word_pairs=[(r,p) for r,p in zip(raw['frames'],pilot['frames']) if first<=r['frame_number']<=last]
        quality={'sequence_id':str(sequence),'class_id':row['class_id'],'subject_group':str(groups[i]),'split':str(splits[i]),
                 'word_frames':meta['summary']['input_word_frames'],'normalizable_selected_frames':int(usable.sum()),
                 'raw_zero_hands_word_frames':sum(len(r['detections'])==0 for r,p in word_pairs),
                 'raw_one_hand_word_frames':sum(len(r['detections'])==1 for r,p in word_pairs),
                 'unassigned_detection_word_frames':sum(len(p['assignments'])<len(r['detections']) for r,p in word_pairs),
                 'selected_left_hand_missing':int((~mask[:,:21].all(axis=1)).sum()),
                 'selected_right_hand_missing':int((~mask[:,21:42].all(axis=1)).sum()),
                 'selected_both_hands_missing':int((~mask[:,:42].any(axis=1)).sum()),'source_npz':str(path)}
        rows.append(quality)
        provenance.append({'sequence_id':str(sequence),'source_npz':str(path),'source_sha256':digest(path),'receipt_sha256':digest(receipt_path)})
    sets={name:set(groups[splits==name].tolist()) for name in ('train','validation','test')}
    if sets['train']&sets['validation'] or sets['train']&sets['test'] or sets['validation']&sets['test']:raise ValueError('촬영 코드가 분할 사이에 중복됩니다.')
    if set(splits.tolist())!=set(sets) or any(set(labels[splits==s].tolist())!=set(range(len(classes))) for s in sets):raise ValueError('분할별 클래스 구성 불일치')
    arrays={'X':np.stack(all_x).astype(np.float32),'joint_mask':np.stack(all_masks),'y':labels,'split':splits,'subject_group':groups,'sequence_id':ids,
            'sampled_source_frame_indices':np.stack(all_frames),'sampled_source_times_seconds':np.stack(all_times)}
    if arrays['X'].shape!=(124,30,177) or not np.isfinite(arrays['X']).all():raise ValueError('기준선 배열 크기·유효성 불일치')
    args.output.mkdir(parents=True,exist_ok=True)
    output=args.output/'dataset.npz';np.savez_compressed(output,**arrays)
    with np.load(output,allow_pickle=False) as saved:
        for k,v in arrays.items():
            if not np.array_equal(saved[k],v):raise ValueError(f'재읽기 불일치: {k}')
    with (args.output/'quality_report.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    spec={'preprocessing_version':'mediapipe-xy59-mask59-nearest30-v1','class_names':classes,'input_shape':[30,177],
          'feature_order':'118 normalized XY values (59 joints) followed by 59 availability masks; NOT 177 raw XYZ values',
          'z_policy':'Excluded from this experimental baseline; raw XYZ retained separately',
          'split_policy':'Reuse exact sequence labels, source-code groups and split from original AIHub baseline',
          'mask_semantics':'Finite-coordinate availability, not localization correctness; mask appended with weight 1',
          'sampling':'Nearest 30 in label interval; no interpolation','unknown_class':False,'production_contract_change':False}
    (args.output/'preprocessing.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'samples':124,'shape':list(arrays['X'].shape),'split_counts':dict(Counter(splits.tolist())),
             'groups':{k:sorted(v) for k,v in sets.items()},'samples_with_any_unassigned_word_detection':sum(r['unassigned_detection_word_frames']>0 for r in rows),
             'samples_with_any_selected_hand_missing':sum(r['selected_left_hand_missing']>0 or r['selected_right_hand_missing']>0 for r in rows),
             'samples_with_all_selected_frames_normalizable':sum(r['normalizable_selected_frames']==30 for r in rows),
             'batch_report':str(batch_path),'batch_sha256':digest(batch_path),'original_split_sha256':digest(old_path),
             'dataset_sha256':digest(output),'source_files':provenance,'training':False,
             'limitations':['No quality-based exclusions; source tracking errors retained with masks where unavailable.',
                            'Masks do not flag incorrect but finite landmarks, including user-reported sleep_v2 frames 51/52.',
                            'Existing exploratory test set has already been inspected; not a new blind evaluation.',
                            'Eight provisional classes, no unknown class, no live app evaluation.']}
    (args.output/'preparation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('전체 124개 결과와 해시 검사: 통과')
    print('배열 크기:',arrays['X'].shape)
    print('분할:',summary['split_counts'])
    print('동작 중 검출됐지만 배정 보류가 있는 영상:',summary['samples_with_any_unassigned_word_detection'])
    print('선택된 30프레임 중 손 누락이 있는 영상:',summary['samples_with_any_selected_hand_missing'])
    print('정규화 가능 30/30인 영상:',summary['samples_with_all_selected_frames_normalizable'])
    print('저장 후 재읽기 검사: 통과')
    print('결과:',args.output.resolve())
    print('자동 제외·모델 학습 없음. 177개 특징은 XY 118개와 마스크 59개입니다.')


if __name__=='__main__':main()
