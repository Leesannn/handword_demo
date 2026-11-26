"""기존 네 영상의 고정 구간을 동일한 서버 처리 모듈로 재현·비교합니다."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',required=True,choices=['coffee','milk','thanks','cold'])
    p.add_argument('--pipeline-dir',type=Path,default=root.parent/'video_pipeline_v0.1_20261109')
    p.add_argument('--video',type=Path)
    args=p.parse_args()
    pipeline_dir=args.pipeline_dir.resolve()
    if not (pipeline_dir/'video_feature_pipeline.py').is_file():
        raise FileNotFoundError('영상 처리 패키지 위치가 다릅니다. --pipeline-dir로 안쪽 폴더를 지정하세요.')
    sys.path.insert(0,str(pipeline_dir))
    import numpy as np
    from video_feature_pipeline import VideoFeaturePipeline
    from predict_mediapipe_video import digest
    baseline=json.loads((root/'reference'/f'{args.case}.json').read_text(encoding='utf-8'))
    video=args.video or root.parents[1] / '04_데이터'/'recordings'/baseline['video_filename']
    features=root/'reference'/f'{args.case}.npz'
    if digest(features)!=baseline['feature_sha256']:raise ValueError('비교 기준 특징 파일이 변경됐습니다.')
    if digest(video)!=baseline['video_sha256']:raise ValueError('기준 영상의 해시가 다릅니다.')
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')/args.case
    try:
        engine=VideoFeaturePipeline(pipeline_dir/'model',pipeline_dir/'models')
        first,last=baseline['frame_interval_1based']
        report=engine.process(video,output,first,last)
        with np.load(features,allow_pickle=False) as z:previous={k:z[k].copy() for k in z.files}
        with np.load(output/'input_features.npz',allow_pickle=False) as z:current={k:z[k].copy() for k in z.files}
        checks={
            '기준 영상 해시 일치':report['video_sha256']==baseline['video_sha256'],
            '기존 모델 해시 일치':report['model_sha256']==baseline['model_sha256'],
            '추출 모델 파일 해시 일치':report['asset_sha256']==baseline['asset_sha256'],
            '고정 구간·선택 프레임 일치':report['frame_interval_1based_inclusive']==[first,last] and
                report['selected_source_frames_1based']==baseline['selected_source_frames_1based'],
            '기본·모델 특징 크기 확인':report['base_shape']==[30,177] and report['model_shape']==[30,183],
            '검출 마스크 일치':bool(np.array_equal(previous['joint_mask'],current['joint_mask'])),
            '정규화 XY 허용 오차 내 일치':bool(np.allclose(previous['X'][:,:118],current['X'][:,:118],rtol=1e-5,atol=1e-5)),
            '기존 단어 후보 재현':report['candidate']['class_id']==baseline['candidate']==args.case}
        record={'case':args.case,'checks':checks,'reference_frame_interval_1based':[first,last],
            'max_absolute_xy_difference':float(np.abs(previous['X'][:,:118]-current['X'][:,:118]).max()),
            'rtol':1e-5,'atol':1e-5,'reference_versions':baseline['versions'],'current_versions':report['versions'],
            'quality':report['quality'],'candidate':report['candidate'],
            'scope':'기존 영상·구간·모델 재사용 회귀 검사. 새 영상의 독립 정확도 평가 아님.'}
        (output/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('\n=== 영상 기준 비교 완료 ===')
        print('단어 후보:',report['candidate']['display_name'],'/ 고정 구간:',[first,last])
        for name,passed in checks.items():print('[PASS]' if passed else '[FAIL]',name)
        print('XY 최대 절대 차이:',record['max_absolute_xy_difference'])
        print('검사 기록:',output/'verification.json')
        if not all(checks.values()):raise RuntimeError('기준과 차이가 있습니다. 구간·모델을 바꾸지 말고 검사 기록부터 확인하세요.')
    except Exception as exc:
        output.mkdir(parents=True,exist_ok=True)
        (output/'error.json').write_text(json.dumps({'error_type':type(exc).__name__,'message':str(exc)},ensure_ascii=False,indent=2),encoding='utf-8')
        raise

if __name__=='__main__':main()
