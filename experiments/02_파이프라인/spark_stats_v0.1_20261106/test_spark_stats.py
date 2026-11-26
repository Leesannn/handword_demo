"""새 인식 요청 하나와 같은 완료 이벤트 재전달로 Spark 통계를 검사합니다."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
import urllib.request
import uuid
from pymongo import MongoClient
from kafka import KafkaProducer

def http(path,payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request('http://127.0.0.1:8768'+path,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as response:return response.status,json.load(response)

def until(fn,seconds=120):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(.5)
    raise RuntimeError('집계 확인 시간 초과. Spark·API·워커·Kafka·MongoDB 로그를 확인하세요.')

def main():
    root=Path(__file__).resolve().parent
    source=json.loads((root/'examples/request.json').read_text(encoding='utf-8'))
    status,job=http('/jobs',{'client_request_id':'spark-check-'+uuid.uuid4().hex,'input':source})
    assert status==202
    def completed():
        _,value=http('/jobs/'+job['sequence_id'])
        if value['status']=='failed':raise RuntimeError('인식 작업 실패: '+str(value['error']))
        return value if value['status']=='completed' else None
    result=until(completed)
    print('[PASS] 새 인식 작업 완료: '+result['result']['candidate']['display_name'],flush=True)
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
        db=client['ksl_demo_stream_stats_v1']
        row=until(lambda:db.event_ledger.find_one({'sequence_id':job['sequence_id']}))
        candidate=result['result']['candidate']
        assert row['event']['candidate']==candidate
        print('[PASS] Kafka 완료 이벤트의 Spark 원장 반영',flush=True)
        start=row['event_time'].replace(second=0,microsecond=0)
        def stats_match():
            total=db.word_totals.find_one({'_id':candidate['class_id']})
            window=db.word_windows_1m.find_one({'class_id':candidate['class_id'],'window_start':start})
            expected=db.event_ledger.count_documents({'status':'completed','class_id':candidate['class_id']})
            expected_window=db.event_ledger.count_documents({'status':'completed','class_id':candidate['class_id'],
                'event_time':{'$gte':start,'$lt':start+timedelta(minutes=1)}})
            if total and window and total['count']==expected and window['count']==expected_window:
                return {'total':total['count'],'window':window['count']}
        before=until(stats_match)
        print('[PASS] 단어별 누적·1분 집계와 고유 원장 건수 일치',flush=True)
        producer=KafkaProducer(bootstrap_servers='127.0.0.1:19092',acks='all',
            value_serializer=lambda v:json.dumps(v,ensure_ascii=False).encode())
        try:
            meta=None
            for _ in range(3):
                meta=producer.send('ksl.recognition.completed.v1',key=job['sequence_id'].encode(),value=row['event']).get(timeout=15)
        finally:producer.close(timeout=5)
        key='ksl.recognition.completed.v1:'+str(meta.partition)
        until(lambda:(d if (d:=db.source_offsets.find_one({'_id':key})) and d['offset']>=meta.offset else None))
        after=stats_match()
        assert after==before,'검사 중 다른 요청이 들어왔는지 또는 중복 집계 여부를 확인하세요.'
        assert db.event_ledger.count_documents({'_id':row['_id']})==1
        print('[PASS] 동일 완료 이벤트 3회 재전달 후 통계 유지',flush=True)
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    evidence={'sequence_id':job['sequence_id'],'candidate':candidate,'stats_before':before,'stats_after':after,
        'duplicate_events_sent':3,'passed':4,'scope':'고정 특징 입력의 통계 반영·중복 방지 검사. 모델 정확도나 지연 목표 평가가 아님.'}
    (output/'spark_stats_check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('검사 기록:',output/'spark_stats_check.json')

if __name__=='__main__':main()
