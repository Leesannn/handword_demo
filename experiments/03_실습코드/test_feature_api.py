"""로컬 API의 상태·정상 추론·잘못된 입력 거부를 확인하고 기록."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlparse
from urllib.request import Request,urlopen


def exchange(base,route,payload=None):
    body=None if payload is None else json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
    request=Request(base.rstrip('/')+route,data=body,headers={'Content-Type':'application/json; charset=utf-8'})
    try:
        with urlopen(request,timeout=15) as response:
            return response.status,json.loads(response.read().decode('utf-8'))
    except HTTPError as error:
        return error.code,json.loads(error.read().decode('utf-8'))
    except URLError as error:
        raise RuntimeError('API에 연결하지 못했습니다. 다른 터미널에서 서버를 먼저 실행하고 켜두세요.') from error


def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--request',type=Path)
    args=parser.parse_args()
    url=urlparse(args.base_url)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost'):
        raise ValueError('이 검사는 노트북 내부127.0.0.1 또는 localhost 주소에만 사용하세요.')
    if args.request:path=args.request.resolve()
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/feature_inference_runs').glob('*/request.json'))
        if not files:raise FileNotFoundError('먼저 특징 JSON 추론 예제를 실행하세요.')
        path=max(files,key=lambda p:p.stat().st_mtime).resolve()
    request=json.loads(path.read_text(encoding='utf-8'))
    checks=[]
    status,health=exchange(args.base_url,'/health')
    if status!=200 or health.get('status')!='ready':raise RuntimeError('서버의 모델 준비 상태 검사 실패')
    checks.append({'check':'모델 준비 상태','http_status':status,'passed':True})
    status,result=exchange(args.base_url,'/v1/experimental/predict',request)
    if status!=200 or result.get('request_id')!=request['request_id'] or result.get('model',{}).get('sha256')!=health['model_sha256']:
        raise RuntimeError('정상 요청의 응답·요청 ID·모델 해시 검사 실패')
    reference=path.with_name('response.json')
    if reference.is_file():
        expected=json.loads(reference.read_text(encoding='utf-8'))
        if expected['model']['sha256']!=result['model']['sha256']:raise RuntimeError('예제 생성 시점과 API 모델이 다릅니다. 모델 경로를 확인하세요.')
        if expected['candidate']!=result['candidate']:raise RuntimeError('직접 호출과 HTTP 호출의 후보가 다릅니다.')
    checks.append({'check':'정상 특징 추론·직접 호출 결과 대응','http_status':status,'passed':True})
    invalid=copy.deepcopy(request);invalid['features']=invalid['features'][:29]
    error_status,error_result=exchange(args.base_url,'/v1/experimental/predict',invalid)
    if error_status!=422 or error_result.get('detail',{}).get('code')!='INVALID_FEATURE_INPUT':raise RuntimeError('잘못된29프레임 요청 거부 검사 실패')
    checks.append({'check':'잘못된 프레임 수 거부','http_status':error_status,'passed':True})
    output=root.parent / '04_데이터'/'ksl_data/http_api_checks'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True,exist_ok=False)
    report={'base_url':args.base_url,'request_file':str(path),'checks':checks,'health':health,
            'normal_response':result,'invalid_response':error_result,'scope':'노트북 내부 HTTP 호출 검증. 앱 연동·외부 배포·새 정확도 평가가 아님.'}
    out=output/'http_check.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if json.loads(out.read_text(encoding='utf-8'))!=report:raise RuntimeError('검사 기록 저장 후 재읽기 실패')
    print('\n=== 로컬 API 검사 완료 ===')
    for row in checks:print(row['check'],': 통과 / HTTP',row['http_status'])
    print('단어 후보:',result['candidate']['display_name'])
    print('저장:',out.resolve())


if __name__=='__main__':main()
