"""실행 중인 로컬 작업 API를 검사하고 결과를 저장합니다."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import uuid

def call(base, path, payload=None):
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    req = urllib.request.Request(base+path, data=body, headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--request', type=Path, default=root/'examples/request.json')
    p.add_argument('--model-dir', type=Path, default=root/'model')
    args=p.parse_args()
    base='http://127.0.0.1:'+str(args.port)
    source=json.loads(args.request.read_text(encoding='utf-8'))
    from predict_feature_json import SignFeaturePredictor
    engine=SignFeaturePredictor(args.model_dir)
    expected=engine.predict(source)
    checks=[]
    status,health=call(base,'/health')
    assert status==200 and health['model_sha256']==engine.model_hash
    checks.append({'name':'모델 버전 일치','pass':True})
    payload={'client_request_id':'check-'+uuid.uuid4().hex,'input':source}
    status,accepted=call(base,'/jobs',payload)
    assert status==202
    job_id=accepted['sequence_id']
    checks.append({'name':'접수 202 및 작업 ID','pass':True})
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        status,completed=call(base,'/jobs/'+job_id)
        assert status==200
        if completed['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert completed['status']=='completed', completed
    assert completed['result']['candidate']==expected['candidate']
    assert completed['result']['model']['sha256']==expected['model']['sha256']
    checks.append({'name':'기존 직접 추론과 결과 일치','pass':True})
    status,reused=call(base,'/jobs',payload)
    assert status==200 and reused['reused'] and reused['sequence_id']==job_id
    checks.append({'name':'동일 요청 재전송 시 같은 ID','pass':True})
    changed=json.loads(json.dumps(payload)); changed['input']['request_id']='different-input'
    status,error=call(base,'/jobs',changed)
    assert status==409
    checks.append({'name':'같은 키·다른 입력 409','pass':True})
    bad=json.loads(json.dumps(payload)); bad['client_request_id']='bad-'+uuid.uuid4().hex; bad['input']['features']=source['features'][:29]
    status,error=call(base,'/jobs',bad)
    assert status==422
    checks.append({'name':'잘못된 프레임 수 422','pass':True})
    status,error=call(base,'/jobs/'+str(uuid.uuid4()))
    assert status==404
    checks.append({'name':'없는 작업 404','pass':True})
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    record={'checks':checks,'accepted':accepted,'completed':completed,'model_sha256':engine.model_hash,
            'scope':'로컬 고정 특징 요청의 서버 연결 검사. 정확도 평가·모바일·AWS 검증이 아님.'}
    (output/'job_api_check.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('\n=== 비동기 작업 API 검사 완료 ===')
    for check in checks: print('[PASS]',check['name'])
    print('단어 후보:',completed['result']['candidate']['display_name'])
    print('작업 ID:',job_id)
    print('검사 기록:',output/'job_api_check.json')

if __name__=='__main__': main()
