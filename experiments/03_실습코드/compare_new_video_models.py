"""같은 영상의 좌표로 기존 모델과 손 모양·위치 분리 모델을 비교."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from project_paths import assignment_hash_matches
from project_paths import resolve_saved_path
import subprocess
import sys


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_interval_seconds(first,last,fps,total):
    if not math.isfinite(fps) or fps<=0 or not 1<=first<=last<=total:
        raise ValueError('시작·끝은 영상 안의 프레임 번호여야 합니다. 번호는 1부터 시작하고 끝 프레임도 포함합니다.')
    return (first-1)/fps,last/fps


def load_model(folder,features,classes):
    import numpy as np
    from train_aihub_knn import predict
    with np.load(folder/'knn_model.npz',allow_pickle=False) as model:
        tx=model['train_X'].astype(np.float64);ty=model['train_y'].copy()
        labels=model['class_names'].tolist();k=int(model['k'])
    query=np.asarray(features).reshape(1,-1).astype(np.float64)
    if labels!=classes or tx.ndim!=2 or tx.shape[1]!=query.shape[1] or not np.isfinite(tx).all():
        raise ValueError('모델의 클래스·특징 크기·수치가 다릅니다.')
    guess,vote=predict(tx,ty,query,k,len(classes))
    return {'candidate':classes[int(guess[0])],'k':k,'neighbor_vote_fraction':float(vote[0]),
            'features_per_frame':features.shape[-1],'model_folder':str(folder.resolve()),
            'model_sha256':digest(folder/'knn_model.npz')}


def main():
    import numpy as np
    from hand_local_features import transform
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--video',type=Path)
    group.add_argument('--latest-recording',action='store_true',help='recordings 폴더의 가장 최근 MP4 사용')
    group.add_argument('--report',type=Path,help='이미 추출한 prediction.json 재사용')
    group.add_argument('--selection',type=Path,help='화면에서 저장한 동작 구간 JSON')
    group.add_argument('--latest-selection',action='store_true',help='가장 최근 저장한 동작 구간 사용')
    parser.add_argument('--model-dir',type=Path,help='생략 시 최신 비교 실험의 손 위치 추가 모델')
    parser.add_argument('--truth',choices=('coffee','milk','cold','thanks','sleep_v1','sleep_v2','sleep_v3','sleep_v4'))
    parser.add_argument('--data-root',type=Path,default=root.parent / '04_데이터'/'ksl_data')
    parser.add_argument('--output',type=Path,help='비교 기록 저장 폴더. 생략하면 원래 예측 기록 옆에 저장')
    parser.add_argument('--start-frame',type=int,help='실제 동작 시작 프레임, 1부터 시작')
    parser.add_argument('--end-frame',type=int,help='실제 동작 끝 프레임, 해당 프레임 포함')
    parser.add_argument('--assignment-v2',action='store_true',help='학습·예측 모두 새 한 손 배정 규칙의 별도 모델 사용')
    args=parser.parse_args()
    if (args.start_frame is None)!=(args.end_frame is None):raise ValueError('시작과 끝 프레임을 함께 지정하세요.')
    if args.report and args.start_frame is not None:raise ValueError('새 구간을 적용하려면 --report 대신 --video 또는 --latest-recording을 사용하세요.')
    if (args.selection or args.latest_selection) and args.start_frame is not None:raise ValueError('저장 구간과 직접 프레임 지정을 동시에 사용할 수 없습니다.')
    data_root=args.data_root
    selection_path=None;selection=None
    if args.selection or args.latest_selection:
        if args.selection:selection_path=args.selection.resolve()
        else:
            selections=list((data_root/'gesture_selections').glob('*.selection.json'))
            if not selections:raise FileNotFoundError('먼저 화면에서 동작 구간을 저장하세요.')
            selection_path=max(selections,key=lambda p:p.stat().st_mtime).resolve()
        selection=json.loads(selection_path.read_text(encoding='utf-8'))
        if selection.get('schema_version')!='gesture-selection-v1':raise ValueError('지원하지 않는 동작 구간 형식입니다.')
        args.start_frame,args.end_frame=selection['frame_interval_1based']
    experiment_path=None
    base_version='mediapipe-xy59-mask59-nearest30-assignment-v2-v1' if args.assignment_v2 else 'mediapipe-xy59-mask59-nearest30-v1'
    if args.model_dir:folder=args.model_dir.resolve()
    else:
        experiment_root=data_root/('assignment_v2_feature_experiments' if args.assignment_v2 else 'feature_experiments')
        paths=[p for p in experiment_root.glob('*/comparison.json') if (p.parent/'local_hands_keep_pose_add_wrists/knn_model.npz').is_file()]
        if not paths:raise FileNotFoundError('먼저 특징 비교 실험을 완료하세요.')
        experiment_path=max(paths,key=lambda p:p.stat().st_mtime)
        folder=experiment_path.parent/'local_hands_keep_pose_add_wrists'
    spec=json.loads((folder/'preprocessing.json').read_text(encoding='utf-8'))
    variant=spec.get('feature_variant')
    if variant!='local_hands_keep_pose_add_wrists' or spec.get('base_preprocessing_version')!=base_version:
        raise ValueError('이 비교 도구는 손 모양과 손 위치를 보존한 183개 특징 실험 모델을 사용합니다.')
    if spec['transform_script_sha256']!=digest(root/'hand_local_features.py'):
        raise ValueError('실험 모델 생성 당시와 특징 변환 코드가 다릅니다.')
    original_folder=folder.parent/'original' if args.assignment_v2 else data_root/'mediapipe_knn_v1'
    if args.assignment_v2:
        assignment_hash=digest(root/'track_hands_v2_experiment.py')
        original_spec=json.loads((original_folder/'preprocessing.json').read_text(encoding='utf-8'))
        if original_spec.get('feature_variant')!='original' or original_spec.get('base_preprocessing_version')!=base_version:
            raise ValueError('새 배정 규칙의 기본 XY 모델을 찾을 수 없습니다.')
        if not assignment_hash_matches(spec['assignment_script_sha256'], assignment_hash) or not assignment_hash_matches(original_spec['assignment_script_sha256'], assignment_hash):
            raise ValueError('두 모델과 현재 손 배정 코드의 버전이 다릅니다.')
    if args.report:report_path=args.report.resolve()
    else:
        if data_root.resolve()!=(root.parent / '04_데이터'/'ksl_data').resolve():raise ValueError('영상 추출은 04_데이터/ksl_data를 사용해야 합니다.')
        if selection is not None:
            video=resolve_saved_path(selection['video']).resolve()
            if digest(video)!=selection['video_sha256']:raise ValueError('구간 선택 시점과 원본 영상이 다릅니다.')
        elif args.latest_recording:
            videos=[p for p in (root.parent / '04_데이터'/'recordings').glob('webcam_*.mp4') if not p.name.endswith('.part.mp4')]
            if not videos:raise FileNotFoundError('먼저 웹캠 촬영 프로그램으로 새 영상을 저장하세요.')
            video=max(videos,key=lambda p:p.stat().st_mtime).resolve()
        else:video=args.video.resolve()
        if not video.is_file():raise FileNotFoundError(video)
        print('비교할 영상:',video,flush=True)
        env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
        command=[sys.executable,'-X','utf8',str(root/'predict_mediapipe_video.py'),'--video',str(video)]
        if args.assignment_v2:command.extend(['--model-dir',str(original_folder)])
        if args.start_frame is not None:
            import cv2
            capture=cv2.VideoCapture(str(video))
            try:
                if not capture.isOpened():raise RuntimeError('영상 프레임 정보를 읽을 수 없습니다.')
                fps=float(capture.get(cv2.CAP_PROP_FPS))
                total=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            finally:capture.release()
            if selection is not None and (total!=selection['video_frames'] or abs(fps-selection['fps'])>1e-5):
                raise ValueError('선택 기록과 영상의 프레임 수·FPS가 다릅니다.')
            start,end=frame_interval_seconds(args.start_frame,args.end_frame,fps,total)
            command.extend(['--start-seconds',repr(start),'--end-seconds',repr(end)])
            print(f'사용자가 지정한 동작 구간: {args.start_frame}~{args.end_frame}번, 총 {args.end_frame-args.start_frame+1}프레임',flush=True)
        paths=[]
        with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',env=env) as process:
            for line in process.stdout:
                print(line,end='',flush=True)
                if line.startswith('결과:'):paths.append(line[len('결과:'):].strip())
            code=process.wait()
        if code or len(paths)!=1:raise RuntimeError('기존 좌표 추출·예측 단계가 실패했습니다. 위 오류를 확인하세요.')
        report_path=Path(paths[0]).resolve()
    prediction=json.loads(report_path.read_text(encoding='utf-8'))
    if prediction['preprocessing_version']!=spec['base_preprocessing_version']:raise ValueError('입력 기본 전처리 버전 불일치')
    input_path=report_path.parent/'input_features.npz'
    with np.load(input_path,allow_pickle=False) as data:
        base=data['X'].copy()
        selected_frames=(data['source_frame_indices']+1).tolist()
    if args.start_frame is not None and (selected_frames[0]!=args.start_frame or selected_frames[-1]!=args.end_frame):
        raise ValueError('선택된 시작·끝 프레임이 요청과 다릅니다. 구간 시각 대응을 확인하세요.')
    transformed=transform(base,variant)
    if transformed.shape!=(30,183):raise ValueError('분리 특징 크기가 올바르지 않습니다.')
    original=load_model(original_folder,base,spec['class_names'])
    if original['model_sha256']!=prediction['model_sha256'] or original['candidate']!=prediction['candidate']:
        raise ValueError('기존 모델 또는 예측 기록이 달라졌습니다.')
    experimental=load_model(folder,transformed,spec['class_names'])
    known_probe=None
    if experiment_path:
        experiment=json.loads(experiment_path.read_text(encoding='utf-8'))
        identity=experiment.get('probe_identity')
        if identity and resolve_saved_path(identity['report']).is_file():
            previous=json.loads(resolve_saved_path(identity['report']).read_text(encoding='utf-8'))
            known_probe=previous['video_sha256']==prediction['video_sha256']
    names={'coffee':'커피','milk':'우유','cold':'춥다','thanks':'감사','sleep_v1':'자다1','sleep_v2':'자다2','sleep_v3':'자다3','sleep_v4':'자다4(잠자다)'}
    result={'video':prediction['video'],'video_sha256':prediction['video_sha256'],'source_prediction':str(report_path),
            'source_prediction_sha256':digest(report_path),'source_features_sha256':digest(input_path),
            'actual_class_user_supplied':args.truth,'original':original,'experimental':experimental,
            'same_base_input':True,'known_feature_design_probe':known_probe,'quality':prediction['quality'],
            'hand_assignment_version':'v2' if args.assignment_v2 else 'v1','base_preprocessing_version':base_version,
            'interval_seconds':prediction['interval_seconds'],'selected_source_frames_1based':selected_frames,
            'requested_frame_interval_1based':None if args.start_frame is None else [args.start_frame,args.end_frame],
            'selection_record':None if selection_path is None else str(selection_path),
            'selection_sha256':None if selection_path is None else digest(selection_path),
            'limitations':['두 모델은 같은 입력 좌표를 사용하지만 특징 구성과 선택된 k가 다름.',
                           '일회 비교 결과는 실사용 정확도 측정이 아님. 기타 동작 거부 기능 없음.',
                           '기존에 분석한 커피 영상의 재사용 결과는 독립 검증이 아님.'],'training':False,'existing_models_changed':False}
    output_dir=args.output or report_path.parent
    output_dir.mkdir(parents=True,exist_ok=True)
    output=output_dir/f'feature_comparison_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== 같은 영상의 두 모델 비교 ===')
    print('손 배정 버전:','v2 (새 규칙의 두 모델)' if args.assignment_v2 else 'v1 (기존 규칙)')
    print('실제 단어:',names.get(args.truth,'미입력'))
    print(f'입력 구간: 원본 {selected_frames[0]}~{selected_frames[-1]}번 / 구간 내 원본 {prediction["quality"]["interval_frames"]}프레임 → 선택 30프레임')
    print('기본 XY 모델:' if args.assignment_v2 else '기존 모델:',names.get(original['candidate'],original['candidate']),f'(k={original["k"]})')
    print('손 모양·위치 분리 모델:',names.get(experimental['candidate'],experimental['candidate']),f'(k={experimental["k"]})')
    print('정규화 가능 프레임:',prediction['quality']['normalizable_selected_frames'],'/30')
    print('손 누락: 왼손',prediction['quality']['left_hand_unavailable'],'/ 오른손',prediction['quality']['right_hand_unavailable'])
    if known_probe:print('주의: 특징 설계에 이미 사용한 영상입니다. 독립 검증으로 세지 않습니다.')
    print('기타 동작 거부 기능 없음. 재학습과 기존 모델 변경 없음.')
    print('비교 기록:',output)


if __name__=='__main__':main()
