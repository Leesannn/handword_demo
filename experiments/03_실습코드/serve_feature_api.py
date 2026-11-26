"""노트북 내부에서만 실행하는 전처리 특징 추론 HTTP API 시제품."""
import argparse
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path


def find_model(data_root):
    paths=[p for p in (data_root/'assignment_v2_feature_experiments').glob('*/comparison.json') if (p.parent/'local_hands_keep_pose_add_wrists/knn_model.npz').is_file()]
    if not paths:raise FileNotFoundError('새 배정 규칙의 분리 모델을 찾을 수 없습니다.')
    return max(paths,key=lambda p:p.stat().st_mtime).parent/'local_hands_keep_pose_add_wrists'


def create_app(model_dir):
    import fastapi
    from fastapi import Body,FastAPI,HTTPException
    from predict_feature_json import SignFeaturePredictor,BASE_VERSION,REQUEST_VERSION

    @asynccontextmanager
    async def lifespan(app):
        app.state.predictor=SignFeaturePredictor(model_dir)
        try:yield
        finally:app.state.predictor=None

    app=FastAPI(title='수어 특징 추론 실험 API',version='0.1.0',lifespan=lifespan,
                description='전처리된 XY118개와 마스크59개를 입력하는 내부 시제품. 원시 영상·XYZ 업로드 API가 아닙니다.')

    @app.get('/health')
    def health():
        engine=app.state.predictor
        if engine is None:raise HTTPException(503,detail={'code':'MODEL_NOT_READY','message':'모델이 준비되지 않았습니다.'})
        return {'status':'ready','model_sha256':engine.model_hash,'k':engine.k,'class_count':len(engine.classes),
                'preprocessing_version':BASE_VERSION,'request_schema_version':REQUEST_VERSION,
                'interface_status':'experimental_internal','fastapi_version':fastapi.__version__,
                'unknown_rejection_supported':False,'sleep_label_policy':'pending'}

    @app.post('/v1/experimental/predict')
    def infer(payload:dict=Body(...)):
        """request.json과 같은 형식의 (30,177) 전처리 특징을 전송합니다."""
        engine=app.state.predictor
        if engine is None:raise HTTPException(503,detail={'code':'MODEL_NOT_READY','message':'모델이 준비되지 않았습니다.'})
        try:return engine.predict(payload)
        except (ValueError,TypeError,OverflowError) as error:
            raise HTTPException(422,detail={'code':'INVALID_FEATURE_INPUT','message':str(error)}) from error
        except Exception as error:
            logging.exception('특징 추론 중 내부 오류')
            raise HTTPException(500,detail={'code':'INFERENCE_FAILED','message':'모델 추론 중 내부 오류가 발생했습니다.'}) from error
    return app


def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir',type=Path)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not 1<=args.port<=65535:raise ValueError('포트 번호는1~65535 범위여야 합니다.')
    model_dir=args.model_dir or find_model(root.parent / '04_데이터'/'ksl_data')
    try:import uvicorn
    except ImportError as error:raise RuntimeError('가상환경에 fastapi와 uvicorn을 먼저 설치하세요.') from error
    app=create_app(model_dir)
    print('사용 모델:',model_dir.resolve())
    print(f'상태 확인: http://127.0.0.1:{args.port}/health')
    print(f'실험 API 문서: http://127.0.0.1:{args.port}/docs')
    print('이 터미널은 서버용으로 유지하세요. 종료: Ctrl+C',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
