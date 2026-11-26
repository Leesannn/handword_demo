"""좌표·전처리·두 모델 입력·예측을 하나의 실험 기록 JSON으로 저장."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from project_paths import resolve_saved_path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def json_safe(value):
    import numpy as np
    if isinstance(value,np.ndarray):return json_safe(value.tolist())
    if isinstance(value,np.generic):return json_safe(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    return value


def build_bundle(comparison_path):
    import numpy as np
    from hand_local_features import transform
    from compare_new_video_models import load_model
    comparison_path=comparison_path.resolve()
    comparison=json.loads(comparison_path.read_text(encoding='utf-8'))
    prediction_path=resolve_saved_path(comparison['source_prediction']).resolve()
    prediction=json.loads(prediction_path.read_text(encoding='utf-8'))
    features_path=prediction_path.parent/'input_features.npz'
    raw_path=prediction_path.parent/'raw_hands.json'
    raw=json.loads(raw_path.read_text(encoding='utf-8'))
    video=resolve_saved_path(comparison['video']).resolve()
    if digest(prediction_path)!=comparison['source_prediction_sha256'] or digest(features_path)!=comparison['source_features_sha256']:
        raise ValueError('원래 예측 기록 또는 특징 파일이 변경됐습니다.')
    if digest(video)!=comparison['video_sha256'] or raw['video_sha256']!=comparison['video_sha256'] or prediction['video_sha256']!=comparison['video_sha256']:
        raise ValueError('원본 영상의 연결 정보가 일치하지 않습니다.')
    with np.load(features_path,allow_pickle=False) as saved:arrays={k:saved[k].copy() for k in saved.files}
    base=arrays['X'];xy=arrays['normalized_xy'];mask=arrays['joint_mask']
    if base.shape!=(30,177) or xy.shape!=(30,59,2) or mask.shape!=(30,59):raise ValueError('입력 배열 크기가 다릅니다.')
    if not np.array_equal(mask,np.isfinite(xy).all(axis=2)) or not np.isnan(xy[~mask]).all():raise ValueError('좌표와 미검출 마스크가 다릅니다.')
    if not np.array_equal(base[:,:118],np.where(mask[...,None],xy,0).reshape(30,118)) or not np.array_equal(base[:,118:],mask.astype(base.dtype)):
        raise ValueError('기존 모델 입력과 정규화 좌표·마스크가 다릅니다.')
    selected=(arrays['source_frame_indices']+1).tolist()
    if selected!=comparison.get('selected_source_frames_1based',selected):raise ValueError('선택 프레임 번호가 다릅니다.')
    if [f['frame_number'] for f in raw['frames']]!=list(range(1,len(raw['frames'])+1)):
        raise ValueError('원시 프레임 순서가 올바르지 않습니다.')
    if selected[0]<1 or selected[-1]>len(raw['frames']):raise ValueError('선택 프레임이 원시 영상 범위를 벗어납니다.')
    experiment_folder=resolve_saved_path(comparison['experimental']['model_folder'])
    experiment_spec_path=experiment_folder/'preprocessing.json'
    spec=json.loads(experiment_spec_path.read_text(encoding='utf-8'))
    transform_path=Path(__file__).with_name('hand_local_features.py')
    if spec['transform_script_sha256']!=digest(transform_path):raise ValueError('특징 변환 코드가 모델 생성 당시와 다릅니다.')
    transformed=transform(base,spec['feature_variant'])
    for name,features in [('original',base),('experimental',transformed)]:
        folder=resolve_saved_path(comparison[name]['model_folder'])
        if digest(folder/'knn_model.npz')!=comparison[name]['model_sha256']:raise ValueError(f'{name} 모델이 변경됐습니다.')
        replay=load_model(folder,features,spec['class_names'])
        if replay['candidate']!=comparison[name]['candidate'] or replay['k']!=comparison[name]['k']:
            raise ValueError(f'{name} 예측 재현 실패')
    capture_path=video.with_suffix('.json')
    capture=json.loads(capture_path.read_text(encoding='utf-8')) if capture_path.is_file() else None
    provenance={str(p):digest(p) for p in (comparison_path,prediction_path,features_path,raw_path,experiment_spec_path,transform_path)}
    bundle={
        'schema_version':'sign-recognition-experiment-bundle-v1',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'purpose':'원시 검출·전처리·모델 입력·예측을 함께 확인하는 로컬 실험 기록. 앱·서버의 확정 인터페이스가 아님.',
        'source':{'video':str(video),'video_sha256':comparison['video_sha256'],'capture_metadata':capture},
        'raw_hand_tracking':{'scope':'원본 전체 영상의 원시 손 검출. 상체 원시 XYZ는 포함하지 않음.',
                             'coordinate_space':'MediaPipe 이미지 기준 손 XYZ. xy는 영상 크기로 정규화된 값, z는 손별 깊이 기준. 공통 미터 단위 3D 좌표가 아님.',
                             'identity_note':'detection_index는 프레임별 검출 순서. 영구적인 왼손·오른손 ID가 아님.',
                             'fps':raw['fps'],'summary':raw['summary'],'frames':raw['frames']},
        'selection':{'frame_numbering':'원본 번호는 1부터 시작. requested_frame_interval의 끝 번호 포함.',
                     'requested_frame_interval_1based':comparison.get('requested_frame_interval_1based'),
                     'interval_seconds':prediction['interval_seconds'],'seconds_interval_rule':'시작 이상, 끝 미만',
                     'selected_source_frames_1based':selected,'selected_times_seconds':arrays['timestamps_seconds'],
                     'selected_input_row_indices':arrays['selected_input_row_indices'],'selected_word_row_indices':arrays['selected_word_row_indices']},
        'preprocessed':{'joint_order':'왼손21점, 오른손21점, MediaPipe Pose 0~16번. 좌우 배정은 실험 규칙에 의존.',
                        'shape':[30,59,2],'coordinates':'어깨 중심·어깨너비로 정규화한 XY. 미검출은 null.',
                        'normalized_xy':xy,'joint_mask':mask,'normalizable_frame':arrays['normalizable_frame'],
                        'mask_note':'유한한 좌표의 사용 가능 여부. 해부학적 위치 정확도를 보장하지 않음.'},
        'model_inputs':{'original':{'shape':list(base.shape),'layout':'앞118개 정규화 XY, 뒤59개 검출 마스크. 미검출 XY는0.',
                                   'values':base},
                        'experimental':{'shape':list(transformed.shape),'feature_variant':spec['feature_variant'],
                                        'layout':spec['layout'],'values':transformed}},
        'predictions':{'actual_class_user_supplied':comparison['actual_class_user_supplied'],
                       'original':comparison['original'],'experimental':comparison['experimental'],
                       'vote_note':'neighbor_vote_fraction은 이웃 투표 비율이며 정답 확률이 아님.'},
        'quality':comparison['quality'],'provenance_sha256':provenance,
        'validation':{'source_hashes_checked':True,'both_model_predictions_replayed':True},
        'limitations':['원본 전체의 원시 손 좌표와 선택30프레임의 정규화 좌표는 서로 다른 범위이다.',
                       '상체 전체 원시 XYZ와 전체 프레임의 고정 좌우 배정 이력은 현재 예측 도구에 저장되지 않아 이 파일에서도 복원하지 않음.',
                       'z는 원시 손 좌표에만 포함. 현재 두 모델은 XY 기반이며 z를 사용하지 않음.',
                       '기타 동작 거부·자동 구간 검출·일반화 성능 보장은 없음.'],
        'training':False,'external_upload':False}
    return json_safe(bundle),base,transformed,xy


def main():
    import numpy as np
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison',type=Path,help='두 모델 비교 결과 JSON. 생략 시 최신 파일')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/prediction_bundles')
    args=parser.parse_args()
    if args.comparison:path=args.comparison
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/new_video_predictions').glob('*/feature_comparison_*.json'))
        if not files:raise FileNotFoundError('먼저 두 모델 비교를 실행하세요.')
        path=max(files,key=lambda p:p.stat().st_mtime)
    bundle,base,transformed,xy=build_bundle(path)
    args.output.mkdir(parents=True,exist_ok=True)
    name=Path(bundle['source']['video']).stem
    output=args.output/f'{name}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}_bundle.json'
    with output.open('x',encoding='utf-8') as stream:json.dump(bundle,stream,ensure_ascii=False,indent=2,allow_nan=False)
    reread=json.loads(output.read_text(encoding='utf-8'))
    for key,expected in [('original',base),('experimental',transformed)]:
        if not np.array_equal(np.asarray(reread['model_inputs'][key]['values'],dtype=np.float32),expected):raise ValueError('모델 입력 재읽기 불일치')
    if not np.array_equal(np.asarray(reread['preprocessed']['normalized_xy'],dtype=np.float32),xy,equal_nan=True):raise ValueError('미검출 null 변환 재읽기 불일치')
    if reread!=bundle:raise ValueError('통합 JSON 재읽기 불일치')
    print('\n=== 통합 실험 JSON 저장 완료 ===')
    print('원시 손 검출 프레임:',len(bundle['raw_hand_tracking']['frames']))
    print('정규화 좌표 크기:',bundle['preprocessed']['shape'])
    print('기존 모델 입력:',bundle['model_inputs']['original']['shape'])
    print('분리 모델 입력:',bundle['model_inputs']['experimental']['shape'])
    print('미검출 null 변환·두 모델 예측 재현·재읽기 검사: 통과')
    print('저장:',output.resolve())
    print('원본 파일 변경·재학습·외부 업로드 없음.')


if __name__=='__main__':main()
