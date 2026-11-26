"""실패·대기열·재시작 복구를 통제된 추론 함수로 검사합니다."""
import json
from pathlib import Path
import tempfile
import threading
import time
from serve_job_api import JobService, APIError, now

class ControlledPredictor:
    def __init__(self):
        self.entered=threading.Event(); self.release=threading.Event()
    def predict(self, value):
        self.entered.set()
        if not self.release.wait(5): raise RuntimeError('검사 대기 시간 초과')
        if value.get('fail'): raise RuntimeError('검사용 실패')
        return {'candidate':'test'}

def expect(code, fn):
    try: fn()
    except APIError as exc: assert exc.status==code
    else: raise AssertionError('예상한 오류가 발생하지 않았습니다.')

def wait_terminal(service, key):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        row=service.get(key)
        if row['status'] in ('completed','failed'): return row
        time.sleep(.01)
    raise AssertionError('작업 종료 시간 초과')

def main():
    checks=[]
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'jobs.sqlite3'; engine=ControlledPredictor()
        service=JobService(db,engine,validator=lambda x:None,capacity=1)
        try:
            accepted,_=service.submit({'client_request_id':'one','input':{'value':1}})
            assert engine.entered.wait(2)
            assert service.get(accepted['sequence_id'])['status']=='processing'
            checks.append('추론이 막혀 있어도 접수 반환·상태 조회 가능')
            expect(503,lambda:service.submit({'client_request_id':'two','input':{}}))
            checks.append('대기열 포화 503')
            replay,reused=service.submit({'client_request_id':'one','input':{'value':1}})
            assert reused and replay['sequence_id']==accepted['sequence_id']
            checks.append('처리 중 동일 요청 중복 방지')
            engine.release.set()
            assert wait_terminal(service,accepted['sequence_id'])['status']=='completed'
            failed,_=service.submit({'client_request_id':'fail','input':{'fail':True}})
            assert wait_terminal(service,failed['sequence_id'])['error']['code']=='INFERENCE_FAILED'
            checks.append('추론 예외를 failed 상태로 저장')
        finally:
            engine.release.set(); service.close()
        # 강제 종료 시 디스크에 남는 대기 상태를 재현합니다.
        with service.connect() as con:
            con.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',('interrupted','interrupted','hash','processing',now(),now(),None,None))
        restored=JobService(db,engine,validator=lambda x:None)
        try:
            assert restored.get(accepted['sequence_id'])['status']=='completed'
            assert restored.get('interrupted')['error']['code']=='SERVER_RESTARTED'
            same,reused=restored.submit({'client_request_id':'one','input':{'value':1}})
            assert reused and same['sequence_id']==accepted['sequence_id']
            checks.append('재시작 후 완료 결과·중복 방지 유지')
            checks.append('중단 작업은 SERVER_RESTARTED 실패로 전환')
        finally: restored.close()
    output=Path(__file__).resolve().parent/'results/service_checks.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'passed':checks,'count':len(checks)},ensure_ascii=False,indent=2),encoding='utf-8')
    for item in checks:print('[PASS]',item)

if __name__=='__main__':main()
