"""Kafka 결과 이벤트를 읽어 MongoDB 원장과 Spark 통계를 갱신하는 소규모 시제품."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from pymongo import MongoClient, ReplaceOne
from pymongo.errors import DuplicateKeyError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker',default='127.0.0.1:19092')
    parser.add_argument('--prefix',default='ksl.recognition')
    parser.add_argument('--database',default='ksl_demo_stream_stats_v1')
    parser.add_argument('--checkpoint',type=Path,default=Path(__file__).resolve().parent/'runtime/stats_checkpoint')
    parser.add_argument('--once',action='store_true',help='현재 쌓인 이벤트를 처리하고 종료')
    args=parser.parse_args()
    os.environ['PYSPARK_PYTHON']=sys.executable
    os.environ['PYSPARK_DRIVER_PYTHON']=sys.executable
    os.environ['SPARK_LOCAL_IP']='127.0.0.1'
    os.environ['SPARK_LOCAL_HOSTNAME']='localhost'
    from pyspark.sql import SparkSession, functions as F
    builder=(SparkSession.builder.master('local[1]').appName('ksl-recognition-statistics')
             .config('spark.driver.host','127.0.0.1').config('spark.driver.bindAddress','127.0.0.1')
             .config('spark.ui.enabled','false').config('spark.driver.memory','768m')
             .config('spark.sql.shuffle.partitions','1').config('spark.sql.session.timeZone','UTC')
             .config('spark.jars.ivy',str(Path(tempfile.gettempdir())/'ksl-spark-ivy-4.0.3'))
             .config('spark.jars.packages','org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.3'))
    spark=builder.getOrCreate();spark.sparkContext.setLogLevel('WARN')
    if spark.version!='4.0.3':raise RuntimeError('Spark 4.0.3을 사용하세요.')
    client=MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000)
    db=client[args.database]
    ledger=db['event_ledger'];ledger.create_index('sequence_id',unique=True)
    # 체크포인트와 목적지를 임의로 섞지 않도록 설정을 고정합니다.
    args.checkpoint.mkdir(parents=True,exist_ok=True)
    settings={'broker':args.broker,'prefix':args.prefix,'database':args.database,'definition':'publish-time-1m-rebuild-v1'}
    binding=args.checkpoint/'ksl_binding.json'
    if binding.exists():
        if json.loads(binding.read_text(encoding='utf-8'))!=settings:
            raise ValueError('체크포인트 설정이 다릅니다. 이전 체크포인트를 삭제하지 말고 새 경로를 지정하세요.')
    else:binding.write_text(json.dumps(settings,indent=2),encoding='utf-8')

    def process(batch,batch_id):
        rows=batch.selectExpr('topic','partition','offset','CAST(timestamp AS DOUBLE) AS event_epoch','CAST(value AS STRING) AS value').collect()
        for row in rows:
            try:
                event=json.loads(row.value)
                expected='completed' if row.topic.endswith('.completed.v1') else 'failed'
                if (not isinstance(event,dict) or event.get('schema_version')!='sign-recognition-event-v1'
                    or event.get('event_type')!=expected or event.get('status')!=expected):
                    raise ValueError('이벤트 종류·상태·버전 불일치')
                for key in ('event_id','sequence_id'):
                    if not isinstance(event.get(key),str) or not event[key]:raise ValueError('이벤트·작업 ID 누락')
                candidate=event.get('candidate')
                if expected=='completed' and (not isinstance(candidate,dict) or not isinstance(candidate.get('class_id'),str)
                    or not isinstance(candidate.get('display_name'),str)):raise ValueError('단어 후보 누락')
            except (ValueError,TypeError) as exc:
                db['rejected_events'].update_one({'_id':f'{row.topic}:{row.partition}:{row.offset}'},
                    {'$setOnInsert':{'reason':str(exc),'batch_id':batch_id}},upsert=True)
                continue
            digest=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            doc={'_id':event['event_id'],'sequence_id':event['sequence_id'],'fingerprint':digest,'event':event,
                 'status':expected,'class_id':candidate['class_id'] if candidate else '',
                 'display_name':candidate['display_name'] if candidate else '',
                 'event_time':datetime.fromtimestamp(row.event_epoch,timezone.utc),
                 'source':{'topic':row.topic,'partition':row.partition,'offset':row.offset}}
            try:ledger.update_one({'_id':doc['_id']},{'$setOnInsert':doc},upsert=True)
            except DuplicateKeyError:raise RuntimeError('같은 작업에 다른 최종 이벤트가 있습니다. 원장을 확인하세요.')
            old=ledger.find_one({'_id':doc['_id']})
            if old['fingerprint']!=digest:raise RuntimeError('같은 이벤트 ID의 내용이 변경됐습니다.')
        # 재실행 시 부분 통계 갱신도 복구하도록 원장을 기준으로 절대값을 재계산합니다.
        # 첫 시연은 최대 10,000건만 지원합니다. 운영용 증분 집계로 확장해야 합니다.
        documents=list(ledger.find({}, {'class_id':1,'display_name':1,'status':1,'event_time':1}).limit(10001))
        if len(documents)>10000:raise RuntimeError('소규모 시제품 원장 10,000건 한도입니다. 데이터 삭제 대신 집계 설계를 확장하세요.')
        if documents:
            values=[(d['class_id'],d['display_name'],d['status'],d['event_time'].replace(tzinfo=timezone.utc)) for d in documents]
            frame=spark.createDataFrame(values,'class_id string, display_name string, status string, event_time timestamp').cache()
            try:
                done=frame.filter(F.col('status')=='completed')
                total=done.groupBy('class_id','display_name').count().collect()
                windows=(done.groupBy(F.window('event_time','1 minute'),'class_id','display_name').count()
                    .select('class_id','display_name','count',F.col('window.start').cast('double').alias('start_epoch'),
                            F.col('window.end').cast('double').alias('end_epoch')).collect())
                states=frame.groupBy('status').count().collect()
                plans={'word_totals':[], 'word_windows_1m':[], 'status_totals':[]}
                for r in total:plans['word_totals'].append({'_id':r.class_id,'class_id':r.class_id,'display_name':r.display_name,'count':r['count']})
                for r in windows:
                    start=datetime.fromtimestamp(r.start_epoch,timezone.utc);end=datetime.fromtimestamp(r.end_epoch,timezone.utc)
                    plans['word_windows_1m'].append({'_id':start.isoformat()+'|'+r.class_id,'class_id':r.class_id,
                        'display_name':r.display_name,'window_start':start,'window_end':end,'count':r['count']})
                for r in states:plans['status_totals'].append({'_id':r.status,'count':r['count']})
                for name,items in plans.items():
                    if items:db[name].bulk_write([ReplaceOne({'_id':d['_id']},{**d,'batch_id':batch_id,'time_basis':'kafka_publish_time'},upsert=True) for d in items])
            finally:frame.unpersist()
        offsets={}
        for row in rows:
            key=f'{row.topic}:{row.partition}';offsets[key]=max(row.offset,offsets.get(key,-1))
        for key,offset in offsets.items():
            db['source_offsets'].update_one({'_id':key},{'$max':{'offset':offset}},upsert=True)
        db['stream_progress'].update_one({'_id':'stats-v1'},
            {'$set':{'batch_id':batch_id,'ledger_count':len(documents),'last_batch_offsets':offsets}},upsert=True)
        print(f'집계 완료: batch={batch_id}, 입력={len(rows)}, 고유 결과={len(documents)}',flush=True)

    try:
        source=(spark.readStream.format('kafka').option('kafka.bootstrap.servers',args.broker)
            .option('subscribe',args.prefix+'.completed.v1,'+args.prefix+'.failed.v1')
            .option('startingOffsets','earliest').option('failOnDataLoss','true')
            .option('maxOffsetsPerTrigger','100').load())
        writer=source.writeStream.foreachBatch(process).option('checkpointLocation',str(args.checkpoint))
        writer=writer.trigger(availableNow=True) if args.once else writer.trigger(processingTime='5 seconds')
        query=writer.start()
        print('Spark 집계 시작: '+args.database+' / 종료 Ctrl+C',flush=True)
        query.awaitTermination()
    except KeyboardInterrupt:pass
    finally:
        for query in spark.streams.active:query.stop()
        client.close();spark.stop()

if __name__=='__main__':main()
