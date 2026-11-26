"""커피 영상의 실제 완료 이벤트와 중복 재전달로 Spark 통계를 검사합니다."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import time
import uuid
from pymongo import MongoClient
from kafka import KafkaProducer

def until(check,seconds=180):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.5)
    raise RuntimeError('확인 시간 초과. API·영상 워커·Spark·Kafka·MongoDB 로그를 확인하세요.')

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8770)
    p.add_argument('--broker',default='127.0.0.1:19092')
    p.add_argument('--prefix',default='ksl.video.recognition')
    p.add_argument('--stats-database',default='ksl_demo_video_stream_stats_v1')
    p.add_argument('--jobs-dir',type=Path,default=root.parent/'video_jobs_v0.1_20261109')
    p.add_argument('--video',type=Path,default=root.parents[1] / '04_데이터'/'recordings/webcam_20261105_151643_813679.mp4')
    args=p.parse_args()
    sys.path.insert(0,str(args.jobs_dir.resolve()))
    from test_video_upload import request, upload
    base=f'http://127.0.0.1:{args.port}'
    checks=[]
    def passed(text):checks.append(text);print('[PASS]',text,flush=True)
    status,health=request(base,'/job-health');assert status==200 and health['topics']['completed']==args.prefix+'.completed.v1'
    status,file=upload(base,args.video.read_bytes());assert status==201
    payload={'client_request_id':'video-spark-'+uuid.uuid4().hex,'file_id':file['file_id']}
    status,job=request(base,'/v1/video-jobs',json.dumps(payload).encode(),'application/json');assert status==202
    def completed():
        status,value=request(base,'/v1/video-jobs/'+job['sequence_id']);assert status==200
        if value['status']=='failed':raise RuntimeError('영상 처리 실패: '+str(value['error']))
        return value if value['status']=='completed' else None
    result=until(completed)
    candidate=result['result']['candidate'];assert candidate['class_id']=='coffee'
    passed('새 커피 영상 업로드·워커 처리 완료')
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
        db=client[args.stats_database]
        row=until(lambda:db.event_ledger.find_one({'sequence_id':job['sequence_id']}))
        assert row['event']['candidate']==candidate and row['source']['topic']==args.prefix+'.completed.v1'
        passed('영상 완료 이벤트의 Spark 원장 반영')
        start=row['event_time'].replace(second=0,microsecond=0)
        def stats_match():
            total=db.word_totals.find_one({'_id':'coffee'})
            window=db.word_windows_1m.find_one({'class_id':'coffee','window_start':start})
            status_total=db.status_totals.find_one({'_id':'completed'})
            expected=db.event_ledger.count_documents({'status':'completed','class_id':'coffee'})
            expected_window=db.event_ledger.count_documents({'status':'completed','class_id':'coffee',
                'event_time':{'$gte':start,'$lt':start+timedelta(minutes=1)}})
            expected_completed=db.event_ledger.count_documents({'status':'completed'})
            if (total and window and status_total and total['count']==expected
                and window['count']==expected_window and status_total['count']==expected_completed):
                return {'coffee_total':total['count'],'coffee_window':window['count'],'completed_total':status_total['count']}
        before=until(stats_match)
        passed('단어별 누적·1분·완료 건수와 고유 원장 일치')
        producer=KafkaProducer(bootstrap_servers=args.broker,acks='all',value_serializer=lambda v:json.dumps(v,ensure_ascii=False).encode())
        try:
            for _ in range(3):
                meta=producer.send(args.prefix+'.completed.v1',key=job['sequence_id'].encode(),value=row['event']).get(timeout=15)
        finally:producer.close(timeout=5)
        key=args.prefix+'.completed.v1:'+str(meta.partition)
        until(lambda:(d if (d:=db.source_offsets.find_one({'_id':key})) and d['offset']>=meta.offset else None))
        after=stats_match()
        assert after==before,'검사 중 다른 요청이 들어왔는지 또는 중복 집계 여부를 확인하세요.'
        assert db.event_ledger.count_documents({'sequence_id':job['sequence_id']})==1
        assert db.event_ledger.find_one({'_id':row['_id']})['event_time']==row['event_time']
        passed('동일 완료 이벤트 3회 재전달 후 건수·원장 시각 유지')
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    report={'passed':len(checks),'checks':checks,'sequence_id':job['sequence_id'],'file_id':file['file_id'],
        'candidate':candidate,'stats_database':args.stats_database,'prefix':args.prefix,
        'stats_before':before,'stats_after':after,'duplicate_events_sent':3,
        'last_duplicate_offset':{'topic':args.prefix+'.completed.v1','partition':meta.partition,'offset':meta.offset},
        'scope':'기존 커피 영상 재사용의 통계 경로·중복 방지 검사. 새로운 정확도·지연 목표 평가는 아님.'}
    (output/'video_spark_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n검사 완료:',len(checks),'개 PASS')
    print('검사 기록:',output/'video_spark_check.json')

if __name__=='__main__':main()
