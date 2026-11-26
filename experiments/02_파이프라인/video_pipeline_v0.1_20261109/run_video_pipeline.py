"""고정된 모델로 영상 파일을 처리합니다. 커피 기준 검사 또는 다른 영상 실행."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import traceback
import numpy as np
from video_feature_pipeline import VideoFeaturePipeline
from predict_mediapipe_video import digest

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--check-coffee',action='store_true')
    parser.add_argument('--start-frame',type=int,default=1)
    parser.add_argument('--end-frame',type=int)
    args=parser.parse_args()
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.parent.mkdir(exist_ok=True)
    if args.check_coffee:
        baseline=json.loads((root/'reference/coffee_reference.json').read_text(encoding='utf-8'))
        if digest(args.video)!=baseline['video_sha256']:raise ValueError('선택한 커피 기준 영상의 해시가 다릅니다.')
        if args.start_frame!=1 or args.end_frame not in (None,91):raise ValueError('커피 기준 검사는 전체 1~91프레임을 사용합니다.')
    try:
        pipeline=VideoFeaturePipeline(root/'model',root/'models')
        report=pipeline.process(args.video,output,args.start_frame,args.end_frame)
        print('\n=== 서버 영상 처리 완료 ===')
        print('단어 후보:',report['candidate']['display_name'])
        print('선택 구간:',report['frame_interval_1based_inclusive'])
        print('기본 특징:',report['base_shape'],'/ 모델 특징:',report['model_shape'])
        print('손 좌표 불완전 선택 프레임: 왼손',report['quality']['left_hand_unavailable'],
              '/ 오른손',report['quality']['right_hand_unavailable'])
        if args.check_coffee:
            with np.load(root/'reference/coffee_input_features.npz',allow_pickle=False) as saved:
                previous={k:saved[k].copy() for k in saved.files}
            with np.load(output/'input_features.npz',allow_pickle=False) as saved:
                current={k:saved[k].copy() for k in saved.files}
            delta=np.abs(previous['X'][:,:118]-current['X'][:,:118])
            checks={
                '기준 영상 해시 일치':report['video_sha256']==baseline['video_sha256'],
                '기존 모델 해시 일치':report['model_sha256']==baseline['model_sha256'],
                '추출 모델 파일 해시 일치':report['asset_sha256']==baseline['asset_sha256'],
                '전체 구간·선택 프레임 일치':report['frame_interval_1based_inclusive']==[1,91] and
                    report['selected_source_frames_1based']==baseline['selected_source_frames_1based'],
                '기본·모델 특징 크기 확인':report['base_shape']==[30,177] and report['model_shape']==[30,183],
                '검출 마스크 일치':bool(np.array_equal(previous['joint_mask'],current['joint_mask'])),
                '정규화 XY 허용 오차 내 일치':bool(np.allclose(previous['X'][:,:118],current['X'][:,:118],rtol=1e-5,atol=1e-5)),
                '기존 커피 후보 재현':report['candidate']['class_id']==baseline['candidate']=='coffee'}
            record={'checks':checks,'reference':'2026-11-05 커피 전체 구간 재사용',
                    'max_absolute_xy_difference':float(delta.max()),'rtol':1e-5,'atol':1e-5,
                    'reference_versions':baseline['versions'],'current_versions':report['versions'],
                    'independent_accuracy_evaluation':False}
            (output/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            for name,passed in checks.items():print('[PASS]' if passed else '[FAIL]',name)
            print('XY 최대 절대 차이:',record['max_absolute_xy_difference'])
            if not all(checks.values()):raise RuntimeError('기준 결과와 차이가 있습니다. 모델을 바꾸지 말고 verification.json을 확인하세요.')
        print('처리 기록:',output/'report.json')
        print('특징 요청:',output/'request.json')
        print('모델 응답:',output/'response.json')
        print('검증 폴더:',output)
        print('로컬 영상 처리 단계이며 업로드 API·Kafka 연결은 다음 단계입니다.')
    except Exception as exc:
        output.mkdir(parents=True,exist_ok=True)
        (output/'error.json').write_text(json.dumps({'error_type':type(exc).__name__,'message':str(exc),
            'scope':'영상 처리 재현 검사 실패. 원본 영상·기존 모델 변경 없음.'},ensure_ascii=False,indent=2),encoding='utf-8')
        print('실패 기록:',output/'error.json')
        raise

if __name__=='__main__':main()
