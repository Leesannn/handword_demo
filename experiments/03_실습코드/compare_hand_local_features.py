"""사전에 정한 세 특징 구성을 학습·검증 데이터로 비교. 테스트 평가는 생략."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import numpy as np
    from hand_local_features import VARIANTS,transform
    from train_aihub_knn import predict,metrics
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=root.parent / '04_데이터'/'ksl_data/mediapipe_baseline_v1')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/feature_experiments')
    parser.add_argument('--probe-report',type=Path,help='이미 관찰한 오답의 참고 비교. 검증 점수에 포함하지 않음')
    parser.add_argument('--probe-truth',help='참고 영상의 사용자 확인 정답')
    args=parser.parse_args()
    if bool(args.probe_report)!=bool(args.probe_truth):raise ValueError('참고 예측 기록과 실제 단어를 함께 지정하세요.')
    dataset_path=args.dataset/'dataset.npz';spec_path=args.dataset/'preprocessing.json'
    spec=json.loads(spec_path.read_text(encoding='utf-8'));classes=spec['class_names']
    if spec.get('preprocessing_version') not in ('mediapipe-xy59-mask59-nearest30-v1','mediapipe-xy59-mask59-nearest30-assignment-v2-v1'):
        raise ValueError('지원하지 않는 기준선 데이터입니다.')
    with np.load(dataset_path,allow_pickle=False) as data:
        # 테스트 입력·정답은 이 실험의 거리 계산이나 모델 선택에 사용하지 않는다.
        split=data['split'];train=split=='train';validation=split=='validation'
        train_x=data['X'][train].copy();train_y=data['y'][train].copy()
        val_x=data['X'][validation].copy();val_y=data['y'][validation].copy()
        train_groups=set(data['subject_group'][train].tolist());val_groups=set(data['subject_group'][validation].tolist())
        train_ids=data['sequence_id'][train].copy();val_ids=data['sequence_id'][validation].copy()
    if train_groups&val_groups:raise ValueError('학습·검증 촬영 코드가 중복됩니다.')
    if set(train_y.tolist())!=set(range(len(classes))) or set(val_y.tolist())!=set(range(len(classes))):raise ValueError('학습·검증에 모든 클래스가 있어야 합니다.')
    probe=None;probe_meta=None;probe_identity=None
    if args.probe_report:
        if args.probe_truth not in classes:raise ValueError('참고 영상의 실제 단어를 클래스 이름으로 지정하세요.')
        probe_meta=json.loads(args.probe_report.read_text(encoding='utf-8'))
        if probe_meta['preprocessing_version']!=spec['preprocessing_version']:raise ValueError('참고 영상의 기본 전처리가 다릅니다.')
        probe_path=args.probe_report.parent/'input_features.npz'
        with np.load(probe_path,allow_pickle=False) as p:probe=p['X'].copy()
        probe_identity={'report':str(args.probe_report.resolve()),'report_sha256':digest(args.probe_report),'features_sha256':digest(probe_path),
                        'user_confirmed_truth':args.probe_truth,'known_before_design':True,'used_for_k_selection':False}
    target=args.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True,exist_ok=False)
    results=[]
    started=time.perf_counter()
    for variant in VARIANTS:
        tx=transform(train_x,variant).reshape(len(train_x),-1).astype(np.float64)
        vx=transform(val_x,variant).reshape(len(val_x),-1).astype(np.float64)
        trials=[];predictions={}
        for k in (1,3,5):
            guess,vote=predict(tx,train_y,vx,k,len(classes))
            score=metrics(val_y,guess,classes)
            trials.append({'k':k,'correct':score['correct'],'samples':score['samples'],'accuracy':score['accuracy'],'macro_f1':score['macro_f1']})
            predictions[k]=guess
        best=min(trials,key=lambda r:(-r['accuracy'],r['k']))
        chosen=best['k'];result={'variant':variant,'features_per_frame':tx.shape[1]//30,'selected_k':chosen,
                               'validation_trials':trials,'validation':metrics(val_y,predictions[chosen],classes),
                               'validation_predictions':[{'sequence_id':str(s),'actual':classes[int(y)],'predicted':classes[int(p)]} for s,y,p in zip(val_ids,val_y,predictions[chosen])]}
        folder=target/variant;folder.mkdir()
        model_path=folder/'knn_model.npz'
        np.savez_compressed(model_path,train_X=tx.astype(np.float32),train_y=train_y,k=np.asarray(chosen,dtype=np.int64),class_names=np.asarray(classes),train_sequence_id=train_ids)
        with np.load(model_path,allow_pickle=False) as model:
            restored,_=predict(model['train_X'].astype(np.float64),model['train_y'],vx,int(model['k']),len(classes))
            if not np.array_equal(restored,predictions[chosen]):raise ValueError('저장 모델 재읽기 예측 불일치')
        if probe is not None:
            px=transform(probe,variant).reshape(1,-1).astype(np.float64)
            guess,vote=predict(tx,train_y,px,chosen,len(classes))
            result['known_error_probe']={'actual':args.probe_truth,'candidate':classes[int(guess[0])],
                                         'neighbor_vote_fraction':float(vote[0]),'evaluation_evidence':False}
            result['known_error_probe_fixed_k']={}
            for fixed_k in (1,3,5):
                fixed_guess,_=predict(tx,train_y,px,fixed_k,len(classes))
                result['known_error_probe_fixed_k'][str(fixed_k)]=classes[int(fixed_guess[0])]
        variant_spec={**spec,'base_preprocessing_version':spec['preprocessing_version'],
                      'preprocessing_version':f'hand-local-experiment-{variant}-v1','feature_variant':variant,
                      'input_shape':[30,tx.shape[1]//30],'feature_weights':'각 좌표·마스크 항의 계수 1. 통계적 표준화와 가중치 탐색 없음.',
                      'layout':'앞 118개는 손목 상대 손 XY와 어깨 기준 Pose XY, 다음 59개는 해당 마스크. add_wrists는 마지막에 어깨 기준 양손목 XY 4개와 마스크 2개 추가. original은 기존 특징 그대로.',
                      'transform_script_sha256':digest(Path(__file__).with_name('hand_local_features.py')),
                      'test_evaluated':False,'promoted_to_production':False}
        (folder/'preprocessing.json').write_text(json.dumps(variant_spec,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        results.append(result)
        score=result['validation'];probe_note='' if probe is None else f' / 기존 커피 참고 후보: {result["known_error_probe"]["candidate"]}'
        print(f'{variant}: 검증 {score["correct"]}/{score["samples"]} ({score["accuracy"]:.1%}), k={chosen}{probe_note}',flush=True)
    report={'dataset':str(dataset_path.resolve()),'dataset_sha256':digest(dataset_path),'class_names':classes,
            'train_samples':len(train_x),'validation_samples':len(val_x),'train_groups':sorted(train_groups),'validation_groups':sorted(val_groups),
            'candidate_variants_fixed_before_run':list(VARIANTS),'k_candidates':[1,3,5],'k_rule':'검증 정확도 우선, 동률이면 작은 k',
            'probe_identity':probe_identity,'results':results,'elapsed_seconds':time.perf_counter()-started,
            'test_evaluated':False,'existing_model_changed':False,
            'limitations':['현재 특징 설계는 이미 본 커피 오답의 영향을 받았다. 그 영상을 맞히는 것은 독립 성능 입증이 아니다.',
                           '검증 16개와 8개 임시 클래스의 작은 탐색 실험이다. 반복 탐색은 검증에도 과적합될 수 있다.',
                           'local_hands_keep_pose도 어깨 기준 Pose 손목·팔 좌표를 남기므로 순수 손 모양만의 모델은 아니다.',
                           '시간축 정렬·새 촬영자 일반화·unknown 거부는 해결하지 않았다.',
                           '별도 모델 폴더에 저장했으며 기존 새 영상 예측 도구에는 자동 적용하지 않았다.']}
    output=target/'comparison.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('비교 결과:',output.resolve())
    print('테스트 재평가·기존 모델 변경 없음. 별도 모델의 입력 규약이 달라 기존 예측 도구에 바로 연결하지 마세요.')


if __name__=='__main__':main()
