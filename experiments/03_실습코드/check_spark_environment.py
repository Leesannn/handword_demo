"""Spark JVM·Python 워커 실행 확인. Kafka나 기존 DB는 변경하지 않습니다."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

def child():
    # 이번 검사 프로세스에만 적용하며 시스템 환경변수는 변경하지 않습니다.
    os.environ['PYSPARK_PYTHON']=sys.executable
    os.environ['PYSPARK_DRIVER_PYTHON']=sys.executable
    os.environ['SPARK_LOCAL_IP']='127.0.0.1'
    from pyspark.sql import SparkSession
    import pyspark
    spark=None
    try:
        spark=(SparkSession.builder.appName('ksl-spark-environment-check').master('local[1]')
               .config('spark.driver.host','127.0.0.1')
               .config('spark.driver.bindAddress','127.0.0.1')
               .config('spark.ui.enabled','false')
               .config('spark.driver.memory','512m')
               .config('spark.sql.shuffle.partitions','1')
               .config('spark.pyspark.python',sys.executable).getOrCreate())
        spark.sparkContext.setLogLevel('ERROR')
        if pyspark.__version__!='4.0.3' or spark.version!='4.0.3':
            raise RuntimeError(f'버전 불일치: Python 패키지={pyspark.__version__}, JVM={spark.version}')
        print('[PASS] PySpark 패키지와 Spark JVM 버전 일치: 4.0.3',flush=True)
        count=spark.range(10).count()
        if count!=10:raise RuntimeError(f'JVM 계산 결과 불일치: {count}')
        print('[PASS] Spark JVM 계산: 10행',flush=True)
        values=spark.sparkContext.parallelize([1,2,3],1).map(lambda x:x*2).collect()
        if values!=[2,4,6]:raise RuntimeError(f'Python 워커 결과 불일치: {values}')
        print('[PASS] Python 워커 계산: [2, 4, 6]',flush=True)
        print('KSL_SPARK_SUCCESS',flush=True)
    finally:
        if spark is not None:spark.stop()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    if args.child:
        child();return
    root=Path(__file__).resolve().parent
    output=root.parent / '04_데이터'/'ksl_data/spark_environment_checks'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['PYTHONUNBUFFERED']='1'
    print('Spark 실행 검사 시작. 첫 실행은 시간이 걸릴 수 있습니다. 최대 120초 대기합니다.',flush=True)
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child'],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env)
    timed_out=False
    try:
        text,_=process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        timed_out=True
        # 이번에 생성한 검사 프로세스와 그 자식 JVM만 종료합니다.
        if os.name=='nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        else:process.kill()
        try:text,_=process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();text='검사 시간 초과. 자식 프로세스 종료도 지연되었습니다.'
    success=not timed_out and process.returncode==0 and 'KSL_SPARK_SUCCESS' in text
    (output/'spark_check.log').write_text(text,encoding='utf-8')
    record={'success':success,'timed_out':timed_out,'exit_code':process.returncode,
            'python_version':sys.version,'python_executable':sys.executable,
            'java_home':os.environ.get('JAVA_HOME'),'spark_home':os.environ.get('SPARK_HOME'),
            'checks':[line for line in text.splitlines() if line.startswith('[PASS]')],
            'scope':'로컬 Spark JVM·Python 워커 검사. Kafka 커넥터·스트리밍·MongoDB 집계는 미검증.'}
    (output/'spark_check.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    if success:
        print('\n=== Spark 실행 검사 통과 ===')
        for line in record['checks']:print(line)
    else:
        print('\n=== Spark 실행 검사 실패 ===')
        if timed_out:print('120초 대기 시간이 초과되었습니다.')
        print('\n'.join(text.splitlines()[-25:]))
    print('검사 기록:',output/'spark_check.json')
    print('상세 로그:',output/'spark_check.log')
    if not success:raise SystemExit(1)

if __name__=='__main__':main()
