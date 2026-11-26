"""새 단일 동작 영상으로 저장된 MediaPipe XY kNN 모델의 단어 후보 확인."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def assignment_for_model(spec):
    old='mediapipe-xy59-mask59-nearest30-v1'
    new='mediapipe-xy59-mask59-nearest30-assignment-v2-v1'
    if spec.get('preprocessing_version')==old:return 'v1',old
    if spec.get('preprocessing_version')=='hand-local-experiment-original-v1' and spec.get('feature_variant')=='original' and spec.get('base_preprocessing_version')==new:
        return 'v2',new
    raise ValueError('단계별 좌표 추출에는 기본 XY 특징 모델이 필요합니다. 모델과 손 배정 버전을 확인하세요.')


def make_features(points,visibility,width,height,fps,start,end):
    import numpy as np
    from normalize_mediapipe177_pilot import normalize
    from resample_xy30_pilot import select_frames
    valid=np.isfinite(points).all(axis=2)
    data,error=normalize(points,valid,visibility,width,height)
    n=len(points);times=np.arange(n,dtype=np.float64)/fps
    data.update(source_frame_indices=np.arange(n,dtype=np.int64),timestamps_seconds=times,
                word_interval_mask=(times>=start)&(times<end))
    selected,word=select_frames(data)
    features=np.concatenate([selected['xy_zero_filled'].reshape(30,118),selected['joint_mask'].astype(np.float32)],axis=1)
    return features,selected,{'interval_frames':len(word),'normalizable_selected_frames':int(selected['normalizable_frame'].sum()),
                              'left_hand_unavailable':int((~selected['joint_mask'][:,:21].all(axis=1)).sum()),
                              'right_hand_unavailable':int((~selected['joint_mask'][:,21:42].all(axis=1)).sum()),
                              'inverse_error_pixels':error}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,default=root/'ksl_data/mediapipe_knn_v1')
    parser.add_argument('--start-seconds',type=float,default=0.)
    parser.add_argument('--end-seconds',type=float,help='생략하면 영상 끝까지 사용')
    args=parser.parse_args()
    video=args.video.resolve()
    if not video.is_file():raise FileNotFoundError(f'새 영상 경로를 확인하세요: {video}')
    import numpy as np
    spec=json.loads((args.model_dir/'preprocessing.json').read_text(encoding='utf-8'))
    assignment_version,base_preprocessing_version=assignment_for_model(spec)
    if assignment_version=='v2' and spec['assignment_script_sha256']!=digest(root/'track_hands_v2_experiment.py'):
        raise ValueError('학습 당시와 새 손 배정 코드가 다릅니다.')
    model_path=args.model_dir/'knn_model.npz'
    with np.load(model_path,allow_pickle=False) as model:
        train_x=model['train_X'].astype(np.float64);train_y=model['train_y'].copy();classes=model['class_names'].tolist();k=int(model['k'])
    if classes!=spec['class_names'] or train_x.ndim!=2 or train_x.shape[1]!=30*177 or not np.isfinite(train_x).all():raise ValueError('모델 배열·클래스 구성이 다릅니다.')
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    from review_raw_hands import extract
    from track_hands_pilot import assign
    if assignment_version=='v2':
        from track_hands_v2_experiment import assign_v2
        assign=assign_v2
    from build_mediapipe177_pilot import assemble_hands
    from train_aihub_knn import predict
    pose_model=root/'models/pose_landmarker_lite.task'
    hand_model=root/'models/hand_landmarker.task'
    video_hash=digest(video)
    folder=root/'ksl_data/new_video_predictions'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True,exist_ok=False)
    raw=extract(video,hand_model,folder/'raw_hands.json')
    cap=cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():raise RuntimeError('영상 열기 실패')
        fps=float(cap.get(cv2.CAP_PROP_FPS));width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not np.isfinite(fps) or not 0<fps<=240 or min(width,height)<=0 or abs(fps-raw['fps'])>1e-5:raise ValueError('영상 크기·FPS를 확인하세요.')
        n=len(raw['frames']);end=n/fps if args.end_seconds is None else args.end_seconds
        if not np.isfinite([args.start_seconds,end]).all() or not 0<=args.start_seconds<end<=n/fps+1e-6:raise ValueError('선택 구간은 영상 안에서 시작 < 끝이어야 합니다.')
        rows=assign(raw['frames'],height/width)
        hands,det_ids=assemble_hands(raw,{'frames':rows})
        pose=np.full((n,17,3),np.nan,dtype=np.float32);visibility=np.full((n,17),np.nan,dtype=np.float32)
        options=vision.PoseLandmarkerOptions(base_options=python.BaseOptions(model_asset_buffer=pose_model.read_bytes()),running_mode=vision.RunningMode.VIDEO,num_poses=1)
        count=0
        with vision.PoseLandmarker.create_from_options(options) as detector:
            while True:
                ok,bgr=cap.read()
                if not ok:break
                if count>=n:raise ValueError('손 좌표보다 영상 프레임이 많습니다.')
                timestamp=round(count*1000/fps)
                if raw['frames'][count]['timestamp_ms']!=timestamp:raise ValueError('손·상체 시각 불일치')
                image=mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)))
                result=detector.detect_for_video(image,timestamp)
                if result.pose_landmarks:
                    pts=result.pose_landmarks[0][:17]
                    if len(pts)!=17:raise ValueError('상체 관절 수 부족')
                    pose[count]=[[p.x,p.y,p.z] for p in pts]
                    visibility[count]=[p.visibility if p.visibility is not None else np.nan for p in pts]
                count+=1
                if count%30==0:print(f'상체 처리: {count}/{n}프레임',flush=True)
        if count!=n:raise ValueError('손·상체 프레임 수 불일치')
    finally:cap.release()
    pose[~np.isfinite(pose).all(axis=2)]=np.nan
    points=np.concatenate([hands,pose],axis=1)
    features,selected,quality=make_features(points,visibility,width,height,fps,args.start_seconds,end)
    guess,vote=predict(train_x,train_y,features.reshape(1,-1).astype(np.float64),k,len(classes))
    names={'coffee':'커피','milk':'우유','cold':'춥다','thanks':'감사','sleep_v1':'자다1','sleep_v2':'자다2','sleep_v3':'자다3','sleep_v4':'자다4(잠자다)'}
    candidate=classes[int(guess[0])]
    if digest(video)!=video_hash:raise ValueError('처리 중 영상이 변경됐습니다.')
    report={'video':str(video),'video_sha256':video_hash,'model_sha256':digest(model_path),
            'preprocessing_version':base_preprocessing_version,'model_preprocessing_version':spec['preprocessing_version'],
            'hand_assignment_version':assignment_version,'candidate':candidate,'candidate_display':names.get(candidate,candidate),
            'k':k,'neighbor_vote_fraction':float(vote[0]),'interval_seconds':[args.start_seconds,end],'quality':quality,
            'hand_assignment_settings':{'max_gap_frames':5,'max_distance_image_width_units':.25,'min_cost_margin_image_width_units':.04,'label_seed_score_min':.7},
            'model_sha256_assets':{p.name:digest(p) for p in (pose_model,hand_model)},
            'versions':{'opencv':cv2.__version__,'mediapipe':mp.__version__,'numpy':np.__version__},
            'limitations':['8개 중 한 후보를 고르는 실험이며 기타·모르는 동작을 거부하는 기능 없음.',
                           '이웃 투표 비율은 정답 확률이 아님. k=1이면 오답도 1.0.',
                           '한 번의 수어 동작 구간 입력이 필요함. 문장·연속 수어 번역 아님.',
                           '실제 정답과의 비교는 사용자 확인이 필요함.'],'training':False}
    np.savez_compressed(folder/'input_features.npz',X=features,**selected)
    report_path=folder/'prediction.json'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== 새 영상 예측 결과 ===')
    print('손 배정 버전:',assignment_version)
    print('단어 후보:',names.get(candidate,candidate))
    print('정규화 가능 선택 프레임:',quality['normalizable_selected_frames'],'/30')
    print('손 누락 선택 프레임: 왼손',quality['left_hand_unavailable'],'/ 오른손',quality['right_hand_unavailable'])
    print('기타 동작 거부 기능은 없습니다. 후보를 정답으로 보장하지 않습니다.')
    print('결과:',report_path)


if __name__=='__main__':main()
