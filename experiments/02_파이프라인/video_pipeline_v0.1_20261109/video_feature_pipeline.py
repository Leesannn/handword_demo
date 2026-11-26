"""영상 파일을 기존 v2 특징 요청으로 변환하는 동기 처리 모듈. 업로드 API 연결 전."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
from predict_mediapipe_video import digest, make_features
from predict_feature_json import SignFeaturePredictor, BASE_VERSION, REQUEST_VERSION

class VideoFeaturePipeline:
    def __init__(self, model_dir, assets_dir):
        start=time.perf_counter()
        self.engine=SignFeaturePredictor(model_dir)
        self.assets=Path(assets_dir)
        self.spec=self.engine.spec
        assignment=Path(__file__).with_name('track_hands_v2_experiment.py')
        if self.spec.get('assignment_script_sha256')!=digest(assignment):
            raise ValueError('모델 생성 당시와 v2 손 배정 코드가 다릅니다.')
        self.asset_hashes={p.name:digest(p) for p in
            (self.assets/'hand_landmarker.task',self.assets/'pose_landmarker_lite.task')}
        self.model_load_ms=(time.perf_counter()-start)*1000

    def process(self, video, output, first_frame=1, last_frame=None):
        """한 영상에 대한 산출물을 새 output 폴더에 저장하고 report를 반환합니다."""
        import cv2
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        from review_raw_hands import extract
        from track_hands_v2_experiment import assign_v2
        from build_mediapipe177_pilot import assemble_hands
        from hand_local_features import transform
        started=time.perf_counter()
        video=Path(video).resolve();output=Path(output)
        if not video.is_file():raise FileNotFoundError('영상 파일을 찾을 수 없습니다: '+str(video))
        if video.stat().st_size>50*1024*1024:raise ValueError('이번 로컬 실험은 50MiB 이하 파일만 처리합니다.')
        output.mkdir(parents=True,exist_ok=False)
        video_hash=digest(video)
        cap=cv2.VideoCapture(str(video))
        try:
            if not cap.isOpened():raise RuntimeError('영상 열기 실패')
            fps=float(cap.get(cv2.CAP_PROP_FPS));total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            codec=int(cap.get(cv2.CAP_PROP_FOURCC))
            codec=''.join(chr((codec>>(8*i))&255) for i in range(4))
        finally:cap.release()
        if not np.isfinite(fps) or not 0<fps<=240 or not 0<total<=1000 or min(width,height)<=0:
            raise ValueError('FPS·영상 크기·프레임 수를 확인하세요.')
        if total/fps>10 or max(width,height)>1920:
            raise ValueError('이번 로컬 실험은 10초 이하·긴 변 1920px 이하 영상만 처리합니다.')
        last=total if last_frame is None else last_frame
        if not isinstance(first_frame,int) or not isinstance(last,int) or not 1<=first_frame<=last<=total:
            raise ValueError('동작 구간은 1부터 시작하며 시작·끝 프레임을 모두 포함합니다.')
        stage=time.perf_counter()
        raw=extract(video,self.assets/'hand_landmarker.task',output/'raw_hands.json')
        if len(raw['frames'])!=total or abs(raw['fps']-fps)>1e-5:
            raise ValueError('영상 메타데이터와 손 추출 프레임이 다릅니다.')
        hand_ms=(time.perf_counter()-stage)*1000
        stage=time.perf_counter()
        rows=assign_v2(raw['frames'],height/width)
        hands,detection_ids=assemble_hands(raw,{'frames':rows})
        assignment_ms=(time.perf_counter()-stage)*1000
        n=len(raw['frames'])
        pose=np.full((n,17,3),np.nan,dtype=np.float32)
        visibility=np.full((n,17),np.nan,dtype=np.float32)
        stage=time.perf_counter()
        options=vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=(self.assets/'pose_landmarker_lite.task').read_bytes()),
            running_mode=vision.RunningMode.VIDEO,num_poses=1)
        cap=cv2.VideoCapture(str(video));count=0
        try:
            if not cap.isOpened():raise RuntimeError('상체 추출용 영상 열기 실패')
            with vision.PoseLandmarker.create_from_options(options) as detector:
                while True:
                    ok,bgr=cap.read()
                    if not ok:break
                    if count>=n:raise ValueError('손·Pose 프레임 수 불일치')
                    timestamp=round(count*1000/fps)
                    if timestamp!=raw['frames'][count]['timestamp_ms']:
                        raise ValueError('손·Pose 시각 불일치')
                    image=mp.Image(image_format=mp.ImageFormat.SRGB,
                        data=np.ascontiguousarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)))
                    result=detector.detect_for_video(image,timestamp)
                    if result.pose_landmarks:
                        points=result.pose_landmarks[0][:17]
                        if len(points)!=17:raise ValueError('Pose 관절 수 부족')
                        pose[count]=[[p.x,p.y,p.z] for p in points]
                        visibility[count]=[p.visibility if p.visibility is not None else np.nan for p in points]
                    count+=1
                    if count%30==0:print(f'Pose 처리: {count}/{n}프레임',flush=True)
            if count!=n:raise ValueError('손·Pose 프레임 수 불일치')
        finally:cap.release()
        pose_ms=(time.perf_counter()-stage)*1000
        stage=time.perf_counter()
        pose[~np.isfinite(pose).all(axis=2)]=np.nan
        coordinates=np.concatenate([hands,pose],axis=1)
        base,selected,quality=make_features(coordinates,visibility,width,height,fps,(first_frame-1)/fps,last/fps)
        if (selected['source_frame_indices'][0]!=first_frame-1 or selected['source_frame_indices'][-1]!=last-1):
            raise ValueError('선택 구간과 실제 선택 프레임의 경계가 다릅니다.')
        transformed=transform(base,'local_hands_keep_pose_add_wrists')
        feature_ms=(time.perf_counter()-stage)*1000
        request={'schema_version':REQUEST_VERSION,'request_id':str(uuid.uuid4()),
                 'preprocessing_version':BASE_VERSION,'input_kind':'normalized_xy118_mask59','features':base.tolist()}
        response=self.engine.predict(request)
        if digest(video)!=video_hash:raise ValueError('처리 중 원본 영상이 변경됐습니다.')
        np.savez_compressed(output/'raw_coordinates.npz',coordinates=coordinates,
                            pose_visibility=visibility,detection_ids=detection_ids)
        np.savez_compressed(output/'input_features.npz',X=base,transformed=transformed,**selected)
        for filename,value in [('request.json',request),('response.json',response)]:
            path=output/filename;path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('JSON 재읽기 불일치')
        with np.load(output/'input_features.npz',allow_pickle=False) as saved:
            if not np.array_equal(saved['X'],base) or not np.array_equal(saved['joint_mask'],selected['joint_mask']):
                raise ValueError('특징 저장 후 재읽기 불일치')
        report={'schema_version':'server-video-pipeline-experiment-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'video':str(video),'video_sha256':video_hash,'video_bytes':video.stat().st_size,
            'video_info':{'width':width,'height':height,'fps':fps,'frames':n,'duration_seconds':n/fps,'codec_fourcc':codec},
            'frame_interval_1based_inclusive':[first_frame,last],
            'timestamp_basis':'원본 프레임 번호 / 메타데이터 FPS. 일정 프레임레이트 영상 전제.',
            'selected_source_frames_1based':(selected['source_frame_indices']+1).tolist(),
            'base_shape':list(base.shape),'model_shape':list(transformed.shape),'quality':quality,
            'candidate':response['candidate'],'model_sha256':self.engine.model_hash,
            'asset_sha256':self.asset_hashes,'assignment_version':'v2','preprocessing_version':BASE_VERSION,
            'versions':{'opencv':cv2.__version__,'mediapipe':mp.__version__,'numpy':np.__version__},
            'timing_ms':{'model_load':self.model_load_ms,'hands':hand_ms,'assignment':assignment_ms,
                         'pose':pose_ms,'features':feature_ms,'knn':response['feature_inference_ms'],
                         'processing_with_output':(time.perf_counter()-started)*1000},
            'output_sha256':{p.name:digest(p) for p in output.iterdir() if p.is_file()},
            'limits':['로컬 파일 처리 재현 검사. 업로드 API·Kafka 워커 연결 전.',
                      '영상 디코딩은 손·Pose 추출 때 각각 수행. 대규모 최적화 전.',
                      '원본 영상·수어 구간을 재사용한 검사이며 새로운 정확도 평가가 아님.',
                      '일정 FPS인 기존 촬영 영상 기준. VFR·모바일 회전·코덱 호환성은 별도 검증 필요.'],
            'training':False}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        return report
