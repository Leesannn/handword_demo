"""커피 영상 업로드·해시·저장본 추론과 실패 응답을 실제 HTTP로 검사합니다."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid

def request(base,path,data=None,content_type=None):
    headers={} if content_type is None else {'Content-Type':content_type}
    req=urllib.request.Request(base+path,data=data,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=40) as res:status,raw=res.status,res.read()
    except urllib.error.HTTPError as exc:status,raw=exc.code,exc.read()
    try:value=json.loads(raw)
    except (ValueError,UnicodeDecodeError):value={'text':raw.decode('utf-8',errors='replace')}
    return status,value

def upload(base,data,filename='coffee.mp4'):
    boundary='ksl-upload-'+uuid.uuid4().hex
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="{filename}"\r\n'
          'Content-Type: video/mp4\r\n\r\n').encode()+data+f'\r\n--{boundary}--\r\n'.encode()
    return request(base,'/v1/videos',body,'multipart/form-data; boundary='+boundary)

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8769)
    p.add_argument('--video',type=Path,default=root.parents[1] / '04_데이터'/'recordings/webcam_20261105_151643_813679.mp4')
    p.add_argument('--pipeline-dir',type=Path,default=root.parent/'video_pipeline_v0.1_20261109')
    args=p.parse_args()
    base=f'http://127.0.0.1:{args.port}'
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    checks=[]
    def passed(name):checks.append(name);print('[PASS]',name,flush=True)
    status,health=request(base,'/health')
    assert status==200 and health['stage']=='upload-only'
    passed('업로드 서버 준비 상태')
    original=args.video.read_bytes();digest=hashlib.sha256(original).hexdigest()
    status,record=upload(base,original)
    assert status==201 and record['status']=='stored'
    passed('커피 영상 업로드 HTTP 201·파일 ID 반환')
    assert record['sha256']==digest and record['bytes']==len(original)
    passed('원본과 저장 파일의 SHA-256·용량 일치')
    status,metadata=request(base,'/v1/videos/'+record['file_id'])
    assert status==200 and metadata==record
    passed('파일 ID로 저장 정보 조회')
    downloaded=output/'downloaded_coffee.mp4'
    with urllib.request.urlopen(base+'/v1/videos/'+record['file_id']+'/content',timeout=40) as res:
        downloaded.write_bytes(res.read())
    assert hashlib.sha256(downloaded.read_bytes()).hexdigest()==digest
    passed('저장본 다운로드·원본 바이트 해시 일치')
    pipeline=args.pipeline_dir.resolve()
    if not (pipeline/'video_feature_pipeline.py').is_file():raise FileNotFoundError('영상 처리 모듈 위치를 --pipeline-dir로 지정하세요.')
    sys.path.insert(0,str(pipeline))
    import numpy as np
    from video_feature_pipeline import VideoFeaturePipeline
    engine=VideoFeaturePipeline(pipeline/'model',pipeline/'models')
    report=engine.process(downloaded,output/'processing')
    reference=json.loads((pipeline/'reference/coffee_reference.json').read_text(encoding='utf-8'))
    with np.load(pipeline/'reference/coffee_input_features.npz',allow_pickle=False) as z:old_x=z['X'].copy();old_mask=z['joint_mask'].copy()
    with np.load(output/'processing/input_features.npz',allow_pickle=False) as z:new_x=z['X'].copy();new_mask=z['joint_mask'].copy()
    assert report['video_sha256']==reference['video_sha256']
    assert report['model_sha256']==reference['model_sha256'] and report['asset_sha256']==reference['asset_sha256']
    assert report['selected_source_frames_1based']==reference['selected_source_frames_1based']
    assert report['candidate']['class_id']=='coffee'
    assert np.array_equal(old_mask,new_mask) and np.allclose(old_x,new_x,rtol=1e-5,atol=1e-5)
    passed('저장본의 커피 후보·기존 특징 재현')
    status,error=upload(base,b'not a video')
    assert status==422 and error['detail']['code']=='INVALID_VIDEO'
    passed('가짜 MP4 파일 거부 HTTP 422')
    status,error=upload(base,original[:64])
    assert status==422 and error['detail']['code']=='INVALID_VIDEO'
    passed('잘린 MP4 파일 거부 HTTP 422')
    status,error=upload(base,b'')
    assert status==422 and error['detail']['code']=='EMPTY_VIDEO'
    passed('빈 파일 거부 HTTP 422')
    status,error=upload(base,original,filename='coffee.txt')
    assert status==415
    passed('허용하지 않은 확장자 거부 HTTP 415')
    status,error=request(base,'/v1/videos/'+str(uuid.uuid4()))
    assert status==404
    passed('없는 파일 ID 조회 HTTP 404')
    connection=http.client.HTTPConnection('127.0.0.1',args.port,timeout=15)
    try:
        # 큰 데이터를 실제로 만들지 않고, 상한을 초과한 선언 길이 거부를 확인합니다.
        connection.putrequest('POST','/v1/videos')
        connection.putheader('Content-Type','multipart/form-data; boundary=probe')
        connection.putheader('Content-Length',str(health['limits']['max_request_bytes']+1))
        connection.endheaders()
        response=connection.getresponse();assert response.status==413;response.read()
    finally:connection.close()
    passed('요청 본문 선언 용량 제한 HTTP 413')
    evidence={'checks':checks,'passed':len(checks),'upload_response':record,
        'source_video':str(args.video.resolve()),'source_sha256':digest,'downloaded_sha256':digest,
        'max_feature_difference':float(np.abs(old_x-new_x).max()),
        'processing_report':'processing/report.json',
        'scope':'업로드·파일 저장·기존 처리 재현 검사. 작업 접수·Kafka·모바일·정확도 평가는 아님.'}
    (output/'upload_check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n검사 완료:',len(checks),'개 PASS')
    print('파일 ID:',record['file_id'])
    print('검사 기록:',output/'upload_check.json')

if __name__=='__main__':main()
