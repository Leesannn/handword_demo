"""로컬 업로드 시제품의 별도 프로세스 영상 검사."""
import argparse
import json
import math

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--path',required=True)
    p.add_argument('--max-seconds',type=float,default=10)
    p.add_argument('--max-side',type=int,default=1920)
    p.add_argument('--max-frames',type=int,default=1000)
    args=p.parse_args()
    import cv2
    cap=cv2.VideoCapture(args.path)
    try:
        if not cap.isOpened():raise ValueError('영상을 열 수 없습니다.')
        fps=float(cap.get(cv2.CAP_PROP_FPS));frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(fps) or not 0<fps<=240 or frames<=0 or min(width,height)<=0:
            raise ValueError('영상 FPS·크기·프레임 정보를 확인하세요.')
        if frames>args.max_frames or frames/fps>args.max_seconds or max(width,height)>args.max_side:
            print(json.dumps({'ok':False,'code':'VIDEO_LIMIT_EXCEEDED','message':'영상 길이·해상도·프레임 제한을 초과했습니다.'},ensure_ascii=False))
            return 2
        codec=int(cap.get(cv2.CAP_PROP_FOURCC))
        codec=''.join(chr((codec>>(8*i))&255) for i in range(4))
        count=0
        while True:
            ok,image=cap.read()
            if not ok:break
            count+=1
            if count>args.max_frames or image.shape[0]>args.max_side or image.shape[1]>args.max_side:
                raise ValueError('실제 디코딩 결과가 제한을 초과했습니다.')
        if count!=frames:raise ValueError('전체 프레임을 정상적으로 읽지 못했습니다.')
        print(json.dumps({'ok':True,'video_info':{'frames':count,'width':width,'height':height,
            'fps':fps,'duration_seconds':count/fps,'codec_fourcc':codec,
            'timestamp_basis':'프레임 번호 / 명목 FPS. VFR·회전 호환성 별도 검증 전.'}},ensure_ascii=False))
        return 0
    except ValueError as exc:
        print(json.dumps({'ok':False,'code':'INVALID_VIDEO','message':str(exc)},ensure_ascii=False));return 2
    finally:cap.release()

if __name__=='__main__':raise SystemExit(main())
