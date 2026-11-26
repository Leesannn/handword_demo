"""카메라 없이 전처리 특징 JSON을 받아 실험용 단어 후보 반환."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path
import time
import uuid

BASE_VERSION='mediapipe-xy59-mask59-nearest30-assignment-v2-v1'
REQUEST_VERSION='sign-feature-request-experiment-v1'
NAMES={'coffee':'커피','milk':'우유','cold':'춥다','thanks':'감사','sleep_v1':'자다1',
       'sleep_v2':'자다2','sleep_v3':'자다3','sleep_v4':'자다4(잠자다)'}


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class SignFeaturePredictor:
    """서버 시작 시 한 번 생성하고 전처리 완료 입력마다 predict 호출."""
    def __init__(self,model_dir):
        import numpy as np
        self.model_dir=Path(model_dir).resolve()
        self.spec=json.loads((self.model_dir/'preprocessing.json').read_text(encoding='utf-8'))
        if self.spec.get('base_preprocessing_version')!=BASE_VERSION or self.spec.get('feature_variant')!='local_hands_keep_pose_add_wrists':
            raise ValueError('새 배정 규칙의 손 모양·위치 분리 모델이 필요합니다.')
        transform_file=Path(__file__).with_name('hand_local_features.py')
        if digest(transform_file)!=self.spec['transform_script_sha256']:
            raise ValueError('모델 생성 당시와 특징 변환 코드가 다릅니다.')
        path=self.model_dir/'knn_model.npz'
        self.model_hash=digest(path)
        with np.load(path,allow_pickle=False) as model:
            self.train_x=model['train_X'].astype(np.float64);self.train_y=model['train_y'].copy()
            self.classes=model['class_names'].tolist();self.k=int(model['k'])
        if self.classes!=self.spec['class_names'] or len(set(self.classes))!=len(self.classes):raise ValueError('클래스 구성이 다릅니다.')
        if self.train_x.ndim!=2 or self.train_x.shape[1]!=30*183 or len(self.train_y)!=len(self.train_x):raise ValueError('모델 입력 크기가 올바르지 않습니다.')
        if not np.isfinite(self.train_x).all() or not np.isin(self.train_y,np.arange(len(self.classes))).all() or not 1<=self.k<=len(self.train_y):
            raise ValueError('모델 수치·라벨·k가 올바르지 않습니다.')

    def predict(self,request):
        import numpy as np
        from hand_local_features import transform
        from train_aihub_knn import predict
        started=time.perf_counter()
        if not isinstance(request,dict) or request.get('schema_version')!=REQUEST_VERSION:raise ValueError('실험용 요청 버전이 다릅니다.')
        request_id=request.get('request_id')
        if not isinstance(request_id,str) or not request_id.strip():raise ValueError('request_id가 필요합니다.')
        if request.get('preprocessing_version')!=BASE_VERSION or request.get('input_kind')!='normalized_xy118_mask59':
            raise ValueError('전처리 버전 또는 입력 의미가 다릅니다. 원시 XYZ177개를 넣으면 안 됩니다.')
        values=np.asarray(request.get('features'))
        if values.shape!=(30,177) or values.dtype.kind not in 'fiu':raise ValueError('features는 숫자로 된 (30,177) 배열이어야 합니다.')
        base=values.astype(np.float32)
        transformed=transform(base,'local_hands_keep_pose_add_wrists')
        if not base[:,118:160].any():raise ValueError('선택된30프레임에 사용 가능한 손 좌표가 없습니다.')
        guessed,votes=predict(self.train_x,self.train_y,transformed.reshape(1,-1).astype(np.float64),self.k,len(self.classes))
        label=self.classes[int(guessed[0])];mask=base[:,118:].astype(bool)
        return {'schema_version':'sign-feature-response-experiment-v1','request_id':request_id,
                'status':'experimental_candidate','candidate':{'class_id':label,'display_name':NAMES.get(label,label)},
                'confidence':None,'neighbor_vote_fraction':float(votes[0]),'unknown_rejection_supported':False,
                'model':{'sha256':self.model_hash,'k':self.k,'variant':'local_hands_keep_pose_add_wrists'},
                'quality':{'frames':30,'left_hand_unavailable':int((~mask[:,:21].all(axis=1)).sum()),
                           'right_hand_unavailable':int((~mask[:,21:42].all(axis=1)).sum())},
                'feature_inference_ms':(time.perf_counter()-started)*1000,
                'notes':['확률 보정된 신뢰도는 없어 confidence는 null이다. 이웃 투표 비율은 정답 확률이 아니다.',
                         '원시 영상·좌표 추출·네트워크 지연은 이 시간 측정에 포함하지 않는다.',
                         '8개 임시 클래스 모델이며 자다 변형의 최종 지원 정책은 보류 상태다.']}


def main():
    import numpy as np
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--request',type=Path,help='이미 작성한 전처리 특징 요청 JSON')
    group.add_argument('--from-comparison',type=Path,help='기존 v2 비교 결과에서 요청 JSON 생성')
    group.add_argument('--example-cold',action='store_true',help='저장된 최신 v2 춥다 비교로 재현')
    parser.add_argument('--model-dir',type=Path)
    parser.add_argument('--data-root',type=Path,default=root.parent / '04_데이터'/'ksl_data')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/feature_inference_runs')
    args=parser.parse_args()
    comparison=None;comparison_path=None
    if args.example_cold:
        candidates=[]
        for p in (args.data_root/'new_video_predictions').glob('*/feature_comparison_*.json'):
            r=json.loads(p.read_text(encoding='utf-8'))
            if r.get('actual_class_user_supplied')=='cold' and r.get('hand_assignment_version')=='v2':candidates.append(p)
        if not candidates:raise FileNotFoundError('저장된 v2 춥다 비교 결과가 없습니다.')
        comparison_path=max(candidates,key=lambda p:p.stat().st_mtime).resolve()
    elif args.from_comparison:comparison_path=args.from_comparison.resolve()
    if comparison_path:
        comparison=json.loads(comparison_path.read_text(encoding='utf-8'))
        if comparison.get('base_preprocessing_version')!=BASE_VERSION:raise ValueError('v2 전처리 비교 결과를 사용하세요.')
        features_path=resolve_saved_path(comparison['source_prediction']).parent/'input_features.npz'
        if digest(features_path)!=comparison['source_features_sha256']:raise ValueError('기존 특징 파일이 변경됐습니다.')
        with np.load(features_path,allow_pickle=False) as saved:base=saved['X'].copy()
        request={'schema_version':REQUEST_VERSION,'request_id':str(uuid.uuid4()),
                 'preprocessing_version':BASE_VERSION,'input_kind':'normalized_xy118_mask59','features':base.tolist()}
    else:request=json.loads(args.request.read_text(encoding='utf-8'))
    if args.model_dir:model_dir=args.model_dir
    elif comparison:model_dir=resolve_saved_path(comparison['experimental']['model_folder'])
    else:
        candidates=[p for p in (args.data_root/'assignment_v2_feature_experiments').glob('*/comparison.json') if (p.parent/'local_hands_keep_pose_add_wrists/knn_model.npz').is_file()]
        if not candidates:raise FileNotFoundError('사용할 v2 분리 모델이 없습니다.')
        model_dir=max(candidates,key=lambda p:p.stat().st_mtime).parent/'local_hands_keep_pose_add_wrists'
    engine=SignFeaturePredictor(model_dir)
    if comparison and engine.model_hash!=comparison['experimental']['model_sha256']:raise ValueError('원래 비교에 사용한 모델과 다릅니다.')
    response=engine.predict(request)
    if comparison and response['candidate']['class_id']!=comparison['experimental']['candidate']:raise ValueError('기존 예측 재현 실패')
    output=args.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True,exist_ok=False)
    for filename,value in [('request.json',request),('response.json',response)]:
        path=output/filename
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('JSON 저장 후 재읽기 불일치')
    record={'purpose':'카메라·영상 추론 없이 전처리 특징 JSON과 저장 모델 연결 재현. 정확도 평가가 아님.',
            'reference_comparison':None if comparison_path is None else str(comparison_path),
            'reference_sha256':None if comparison_path is None else digest(comparison_path),
            'reference_candidate_matched':None if comparison is None else True,
            'request_sha256':digest(output/'request.json'),'response_sha256':digest(output/'response.json'),
            'model_folder':str(engine.model_dir),'training':False,'network_server_started':False,
            'interface_status':'전처리와 추론 사이의 내부 입출력 초안. 앱 업로드 규약 확정 전.'}
    (output/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n=== 특징 JSON 추론 완료 ===')
    print('단어 후보:',response['candidate']['display_name'])
    print('확률 신뢰도: 제공하지 않음 / 이웃 투표 비율:',response['neighbor_vote_fraction'])
    if comparison:print('기존 분리 모델 예측 재현: 통과')
    print('요청·응답 JSON 저장 후 재읽기: 통과')
    print('저장 폴더:',output.resolve())
    print('원시 XYZ 입력이나 실제 앱 서버가 아닙니다. 외부 전송·재학습 없음.')


if __name__=='__main__':main()
