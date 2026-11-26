"""노트북 웹캠: SPACE → 준비 3초 → 녹화 5초 → 자동 저장."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time


def recording_fps(timestamps):
    if len(timestamps)<2:
        raise ValueError('저장할 프레임이 부족합니다.')
    if not all(math.isfinite(t) for t in timestamps) or any(b<=a for a,b in zip(timestamps,timestamps[1:])):
        raise ValueError('프레임 수집 시각이 정상적으로 증가하지 않습니다.')
    span=timestamps[-1]-timestamps[0]
    if span<=0:
        raise ValueError('촬영 프레임의 시각이 올바르지 않습니다.')
    return (len(timestamps)-1)/span


def save_clip(frames,timestamps,output,started_at,requested_seconds,device):
    import cv2
    fps=recording_fps(timestamps)
    height,width=frames[0].shape[:2]
    if any(f.shape!=frames[0].shape for f in frames):
        raise ValueError('녹화 도중 영상 크기가 달라졌습니다.')
    output.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().astimezone().strftime('%Y%m%d_%H%M%S_%f')
    path=output/f'webcam_{stamp}.mp4'
    temporary=output/f'webcam_{stamp}.part.mp4'
    writer=cv2.VideoWriter(str(temporary),cv2.VideoWriter_fourcc(*'mp4v'),fps,(width,height))
    try:
        if not writer.isOpened():
            raise RuntimeError('MP4 저장기를 열 수 없습니다. 저장 폴더 권한과 코덱을 확인하세요.')
        for frame in frames:writer.write(frame)
    finally:writer.release()
    # 생성 여부만으로 성공 처리하지 않고 실제로 모든 프레임을 다시 읽는다.
    capture=cv2.VideoCapture(str(temporary))
    decoded=0
    try:
        if not capture.isOpened():raise RuntimeError('저장 파일을 다시 열지 못했습니다.')
        while True:
            ok,frame=capture.read()
            if not ok:break
            if frame.shape[:2]!=(height,width):raise RuntimeError('저장 영상 크기 검사 실패')
            decoded+=1
    finally:capture.release()
    if decoded!=len(frames):
        raise RuntimeError(f'저장 후 프레임 검사 실패: 원본 {len(frames)} / 재읽기 {decoded}. 임시 파일: {temporary}')
    if path.exists():raise FileExistsError(path)
    temporary.rename(path)
    metadata={'schema_version':'webcam-short-clip-v1','video':str(path.resolve()),
              'recording_started_at':started_at,'camera_index':device,
              'requested_seconds':requested_seconds,'frames':len(frames),'width':width,'height':height,
              'encoded_fps':fps,'encoded_duration_seconds':len(frames)/fps,
              'observed_first_to_last_seconds':timestamps[-1]-timestamps[0],
              'frame_offsets_seconds':timestamps,
              'timing_note':'실측 프레임 간격의 평균 FPS로 저장. 실제 수집 시각은 별도 기록.',
              'mirrored':False,'overlays_in_saved_video':False,'audio_recorded':False,
              'decode_verified_frames':decoded,'opencv_version':cv2.__version__}
    path.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return path,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--camera',type=int,default=0,help='기본 노트북 카메라 번호')
    parser.add_argument('--countdown',type=float,default=3.,help='녹화 전 준비 시간. 바로 시작하려면 0')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'recordings',help='저장 폴더')
    args=parser.parse_args()
    if not math.isfinite(args.countdown) or args.countdown<0:raise ValueError('준비 시간은 유한한 0 이상의 숫자여야 합니다.')
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    if not font_path.is_file():raise FileNotFoundError('한글 화면 표시에 필요한 맑은 고딕 글꼴이 없습니다.')
    large_font=ImageFont.truetype(str(font_path),26)
    small_font=ImageFont.truetype(str(font_path),17)
    cap=cv2.VideoCapture(args.camera)
    try:
        if not cap.isOpened():raise RuntimeError('카메라를 열 수 없습니다. 다른 카메라 앱을 종료하고 Windows 카메라 권한을 확인하세요.')
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
        duration=5.
        state='ready';deadline=0.;record_start=0.;started_at=None
        frames=[];timestamps=[];saved_count=0;last_path=None;status_until=0.
        window='수어 촬영 - SPACE 녹화 / Q 종료'
        print('저장 폴더:',args.output.resolve())
        print(f'SPACE: 준비 {args.countdown:g}초 후 {duration:g}초 녹화 / Q 또는 ESC: 종료')
        print('상하좌우 반전 없이 저장합니다. 화면의 안내 글자는 영상에 저장하지 않습니다.')
        while True:
            ok,frame=cap.read()
            now=time.perf_counter()
            if not ok:raise RuntimeError('카메라 프레임을 읽을 수 없습니다. 다른 앱의 카메라 사용 여부를 확인하세요.')
            if state=='countdown' and now>=deadline:
                state='recording';record_start=now
                started_at=datetime.now(timezone.utc).astimezone().isoformat()
                frames=[];timestamps=[]
                print('녹화 시작',flush=True)
            if state=='recording':
                if now-record_start<duration:
                    frames.append(frame.copy());timestamps.append(now-record_start)
                else:
                    # 저장 검사 중에는 추가로 녹화하지 않는다.
                    print('녹화 종료. 파일 저장·재읽기 검사 중...',flush=True)
                    path,metadata=save_clip(frames,timestamps,args.output,started_at,duration,args.camera)
                    frames=[];timestamps=[];state='ready';saved_count+=1
                    last_path=path;status_until=time.perf_counter()+5
                    print('\n=== 녹화 저장 완료 ===')
                    print('영상:',path.resolve())
                    print('기록:',path.with_suffix('.json').resolve())
                    print(f'길이: 약 {metadata["encoded_duration_seconds"]:.2f}초 / 프레임: {metadata["frames"]} / FPS: {metadata["encoded_fps"]:.2f}')
                    print('저장 후 전체 프레임 재읽기: 통과')
                    print('SPACE로 다음 영상을 촬영할 수 있습니다.',flush=True)
            preview=frame.copy()
            scale=min(1100/preview.shape[1],700/preview.shape[0],1.)
            preview=cv2.resize(preview,(round(preview.shape[1]*scale),round(preview.shape[0]*scale)))
            if state=='countdown':
                text=f'촬영 준비: {max(1,int(deadline-now)+1)}초';color=(255,220,0)
            elif state=='recording':
                text=f'녹화 중: 남은 시간 {max(0,duration-(now-record_start)):.1f}초';color=(255,80,80)
            else:
                text=f'촬영 대기 / 저장 완료: {saved_count}개';color=(80,230,80)
            banner=Image.new('RGB',(preview.shape[1],110),(25,25,25))
            draw=ImageDraw.Draw(banner)
            draw.text((15,3),text,font=large_font,fill=color)
            draw.text((15,43),f'SPACE: 준비 후 {duration:g}초 녹화 / Q 또는 ESC: 종료',font=small_font,fill=(255,255,255))
            if last_path and time.perf_counter()<status_until:
                draw.text((15,76),'저장: '+last_path.name,font=small_font,fill=(80,230,80))
            banner_bgr=np.asarray(banner)[:,:,::-1]
            visible=min(110,preview.shape[0])
            preview[:visible]=banner_bgr[:visible]
            cv2.imshow(window,preview)
            key=cv2.waitKey(1)&255
            if key in (ord('q'),27) or cv2.getWindowProperty(window,cv2.WND_PROP_VISIBLE)<1:
                if state=='recording':print('종료 요청으로 진행 중인 녹화는 저장하지 않았습니다.')
                break
            if key==ord(' ') and state=='ready':
                state='countdown';deadline=time.perf_counter()+args.countdown
    finally:
        cap.release();cv2.destroyAllWindows()


if __name__=='__main__':main()
