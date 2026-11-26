"""우유·감사·춥다의 고정 영상을 API부터 Spark 통계까지 검증합니다."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from pymongo import MongoClient
from kafka import KafkaProducer

NAMES={'milk':'우유','thanks':'감사','cold':'춥다'}

def until(check,seconds=180):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.5)
    raise RuntimeError('확인 시간 초과. API·워커·Spark 터미널의 마지막 로그를 확인하세요.')

def require(condition,message):
    if not condition:raise RuntimeError(message)

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['milk','thanks','cold','all'],default='all')
    parser.add_argument('--port',type=int,default=8770)
    parser.add_argument('--broker',default='127.0.0.1:19092')
    parser.add_argument('--prefix',default='ksl.video.recognition')
    parser.add_argument('--stats-database',default='ksl_demo_video_stream_stats_v1')
    parser.add_argument('--jobs-dir',type=Path,default=root.parent/'video_jobs_v0.1_20261109')
    parser.add_argument('--recordings',type=Path,default=root.parents[1] / '04_데이터'/'recordings')
    args=parser.parse_args()
    sys.path.insert(0,str(args.jobs_dir.resolve()))
    from test_video_upload import request, upload
    base=f'http://127.0.0.1:{args.port}'
    cases=list(NAMES) if args.case=='all' else [args.case]
    # 요청 전에 선택된 모든 기준 영상이 있는지 확인합니다.
    references={}
    for case in cases:
        ref=json.loads((root/'reference'/f'{case}.json').read_text(encoding='utf-8'))
        path=args.recordings/ref['video_filename']
        require(path.is_file(),'기준 영상이 없습니다: '+str(path))
        require(hashlib.sha256(path.read_bytes()).hexdigest()==ref['video_sha256'],'기준 영상의 내용이 다릅니다: '+str(path))
        references[case]=ref
    status,health=request(base,'/job-health')
    require(status==200 and health['topics']['completed']==args.prefix+'.completed.v1','영상 API·토픽 설정을 확인하세요.')
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    summary={'status':'running','cases':{},'passed':0,'stats_database':args.stats_database,'prefix':args.prefix,
        'scope':'기존 고정 영상·수어 구간을 재사용한 회귀 검사. 새 독립 정확도·모바일 호환성 평가가 아님.'}
    def save():
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
            db=client[args.stats_database]
            for case in cases:
                ref=references[case];checks=[]
                record={'status':'running','checks':checks,'reference_sha256':ref['video_sha256'],
                    'reference_frame_interval':ref['frame_interval_1based']}
                summary['cases'][case]=record
                def passed(text):
                    checks.append(text);summary['passed']+=1;save();print(f'[PASS] {NAMES[case]} / {text}',flush=True)
                print('\n검사 시작:',NAMES[case],'/ 구간:',ref['frame_interval_1based'],flush=True)
                path=args.recordings/ref['video_filename']
                status,file=upload(base,path.read_bytes())
                require(status==201 and file['sha256']==ref['video_sha256'],'업로드 상태·해시 불일치: '+str(file))
                record['file_id']=file['file_id'];passed('기준 영상 업로드·해시 일치')
                first,last=ref['frame_interval_1based']
                payload={'client_request_id':'case-'+case+'-'+uuid.uuid4().hex,'file_id':file['file_id'],
                    'frame_interval':{'start':first,'end':last}}
                status,job=request(base,'/v1/video-jobs',json.dumps(payload).encode(),'application/json')
                require(status==202,'작업 접수 실패: '+str(job))
                record['sequence_id']=job['sequence_id'];passed('고정 구간 작업 접수 HTTP 202')
                def completed():
                    status,value=request(base,'/v1/video-jobs/'+job['sequence_id'])
                    require(status==200,'작업 조회 실패: '+str(value))
                    if value['status']=='failed':raise RuntimeError('영상 작업 실패: '+str(value['error']))
                    return value if value['status']=='completed' else None
                result=until(completed)['result'];processing=result['video_processing']
                require(result['candidate']['class_id']==case,'후보 불일치. 기대='+case+', 실제='+str(result['candidate']))
                require(processing['video_sha256']==ref['video_sha256'] and processing['frame_interval']==payload['frame_interval'],
                    '처리 영상·구간 불일치')
                require(processing['selected_source_frames_1based']==ref['selected_source_frames_1based']
                    and processing['base_shape']==[30,177] and processing['model_shape']==[30,183],
                    '선택 프레임·특징 크기 불일치')
                require(processing['pipeline_sha256']==health['pipeline_sha256'],'API·워커 파이프라인 버전 불일치')
                record['candidate']=result['candidate'];record['processing']=processing
                passed('워커 후보·처리 구간·30프레임 특징 확인')
                row=until(lambda:db.event_ledger.find_one({'sequence_id':job['sequence_id']}))
                require(row['source']['topic']==args.prefix+'.completed.v1' and row['event']['candidate']==result['candidate']
                    and row['event']['model_sha256']==ref['model_sha256'],'Spark 원장·API 후보·모델 해시 불일치')
                passed('Kafka 완료 이벤트의 Spark 원장·API 결과 일치')
                start=row['event_time'].replace(second=0,microsecond=0)
                def stats_match():
                    total=db.word_totals.find_one({'_id':case})
                    window=db.word_windows_1m.find_one({'class_id':case,'window_start':start})
                    state=db.status_totals.find_one({'_id':'completed'})
                    expected=db.event_ledger.count_documents({'status':'completed','class_id':case})
                    expected_window=db.event_ledger.count_documents({'status':'completed','class_id':case,
                        'event_time':{'$gte':start,'$lt':start+timedelta(minutes=1)}})
                    expected_completed=db.event_ledger.count_documents({'status':'completed'})
                    if total and window and state and (total['count'],window['count'],state['count'])==(expected,expected_window,expected_completed):
                        return {'word_total':total['count'],'word_window_1m':window['count'],'completed_total':state['count']}
                before=until(stats_match);record['stats_before']=before;passed('단어별 누적·1분·완료 통계와 고유 원장 일치')
                producer=KafkaProducer(bootstrap_servers=args.broker,acks='all',
                    value_serializer=lambda value:json.dumps(value,ensure_ascii=False).encode())
                try:
                    for _ in range(3):
                        meta=producer.send(args.prefix+'.completed.v1',key=job['sequence_id'].encode(),value=row['event']).get(timeout=15)
                finally:producer.close(timeout=5)
                key=args.prefix+'.completed.v1:'+str(meta.partition)
                until(lambda:(doc if (doc:=db.source_offsets.find_one({'_id':key})) and doc['offset']>=meta.offset else None))
                after=stats_match()
                require(after==before,'재전달 전후 통계가 다릅니다. 다른 요청 동시 실행 여부를 확인하세요.')
                require(db.event_ledger.count_documents({'sequence_id':job['sequence_id']})==1
                    and db.event_ledger.find_one({'_id':row['_id']})['event_time']==row['event_time'],'원장 중복·시각 변경')
                record.update(status='passed',stats_after=after,duplicate_events_sent=3,
                    last_duplicate_offset={'topic':args.prefix+'.completed.v1','partition':meta.partition,'offset':meta.offset})
                passed('완료 이벤트 3회 재전달 후 건수·원장 시각 유지')
                (output/(case+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        summary['status']='passed';save()
    except Exception as exc:
        summary['status']='failed';summary['error']={'type':type(exc).__name__,'message':str(exc)};save()
        print('검사 중단. 기록:',output/'summary.json',flush=True)
        raise
    print('\n검사 완료:',summary['passed'],'개 PASS /',len(cases),'개 단어')
    print('검사 기록:',output/'summary.json')

if __name__=='__main__':main()
