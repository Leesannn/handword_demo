"""촬영 영상에서 버튼으로 실제 동작 시작·끝을 지정하고 저장."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def selection_record(video,video_hash,first,last,total,fps):
    import math
    if not math.isfinite(fps) or fps<=0 or not 0<=first<=last<total:raise ValueError('선택 구간과 영상 정보를 확인하세요.')
    return {'schema_version':'gesture-selection-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'video':str(video.resolve()),'video_sha256':video_hash,'video_frames':total,'fps':fps,
            'frame_interval_1based':[first+1,last+1],'frame_rule':'1부터 시작하며 끝 프레임 포함',
            'interval_seconds':[first/fps,(last+1)/fps],'seconds_rule':'시작 이상, 끝 미만',
            'selected_frame_count':last-first+1,'selection_method':'user_visual_buttons',
            'automatic_detection':False,'original_video_modified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--video',type=Path,help='생략하면 가장 최근 웹캠 녹화 영상')
    args=parser.parse_args()
    if args.video:video=args.video.resolve()
    else:
        files=[p for p in (root.parent / '04_데이터'/'recordings').glob('webcam_*.mp4') if not p.name.endswith('.part.mp4')]
        if not files:raise FileNotFoundError('먼저 웹캠으로 영상을 촬영하세요.')
        video=max(files,key=lambda p:p.stat().st_mtime).resolve()
    if not video.is_file():raise FileNotFoundError(video)
    video_hash=digest(video)
    import cv2
    import tkinter as tk
    from tkinter import ttk,messagebox
    from PIL import Image,ImageTk
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():raise RuntimeError('영상을 열 수 없습니다.')
    fps=float(cap.get(cv2.CAP_PROP_FPS));total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total<1 or not 0<fps<1000:cap.release();raise ValueError('영상 FPS와 프레임 수를 확인하세요.')
    app=tk.Tk();app.title('수어 동작 구간 선택');app.geometry('1100x830')
    app.option_add('*Font',('맑은 고딕',11))
    state={'index':0,'first':0,'last':total-1,'cached':-1,'playing':False,'selection_only':False,'next_at':0.,'updating':False,'closed':False}
    ttk.Label(app,text='1. 시작 장면에서 [시작 지정] → 2. 끝 장면에서 [끝 지정] → 3. [선택 구간 재생] → 4. [구간 저장]').pack(pady=8)
    ttk.Label(app,text=video.name).pack()
    display=ttk.Label(app);display.pack(pady=5)
    info=tk.StringVar();ttk.Label(app,textvariable=info).pack()
    slider=ttk.Scale(app,from_=0,to=max(1,total-1),orient='horizontal');slider.pack(fill='x',padx=25,pady=10)
    buttons=ttk.Frame(app);buttons.pack(pady=8)
    status=tk.StringVar(value='준비·마무리를 제외하고 실제 동작 경계로 선택하세요.');ttk.Label(app,textvariable=status,wraplength=1040).pack(pady=8)

    def show(index):
        index=max(0,min(total-1,int(index)))
        if index!=state['cached']:
            if index!=state['cached']+1 or state['cached']<0:cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,frame=cap.read()
            if not ok:raise RuntimeError(f'{index+1}번 프레임을 읽지 못했습니다.')
            image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));image.thumbnail((1000,540))
            photo=ImageTk.PhotoImage(image);display.configure(image=photo);display.image=photo
            state['cached']=index
        state['index']=index
        state['updating']=True;slider.set(index);state['updating']=False
        info.set(f'현재 {index+1}/{total}번 ({index/fps:.2f}초)  |  선택: {state["first"]+1}~{state["last"]+1}번, {state["last"]-state["first"]+1}프레임')

    def seek(value):
        if state['updating']:return
        state['playing']=False;show(round(float(value)))
    slider.configure(command=seek)

    def step(delta):state['playing']=False;show(state['index']+delta)

    def toggle():
        state['playing']=not state['playing'];state['selection_only']=False;state['next_at']=time.perf_counter()+1/fps

    def set_boundary(which):
        state['playing']=False;index=state['index']
        if which=='first' and index>state['last'] or which=='last' and index<state['first']:
            messagebox.showerror('구간 확인','시작은 끝보다 뒤에 올 수 없습니다. 반대쪽 경계를 먼저 변경하세요.');return
        state[which]=index;show(index)

    def play_selection():
        show(state['first']);state['selection_only']=True;state['playing']=True;state['next_at']=time.perf_counter()+1/fps

    def save():
        state['playing']=False
        try:
            if digest(video)!=video_hash:raise ValueError('선택 중 원본 영상이 변경됐습니다.')
            record=selection_record(video,video_hash,state['first'],state['last'],total,fps)
            target=root.parent / '04_데이터'/'ksl_data/gesture_selections';target.mkdir(parents=True,exist_ok=True)
            path=target/f'{video.stem}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.selection.json'
            with path.open('x',encoding='utf-8') as stream:json.dump(record,stream,ensure_ascii=False,indent=2,allow_nan=False)
            if json.loads(path.read_text(encoding='utf-8'))!=record:raise ValueError('선택 기록 재읽기 불일치')
            status.set(f'저장 완료: {record["frame_interval_1based"][0]}~{record["frame_interval_1based"][1]}번. 창을 닫고 터미널에서 비교 명령을 실행하세요.')
            print('\n=== 동작 구간 저장 완료 ===')
            print('영상:',video)
            print('선택 구간:',record['frame_interval_1based'],'/ 프레임 수:',record['selected_frame_count'])
            print('저장:',path.resolve())
            print('다음: compare_new_video_models.py --latest-selection --truth 실제클래스',flush=True)
        except Exception as error:messagebox.showerror('저장 오류',str(error))

    def close():
        state['closed']=True;state['playing']=False;cap.release();app.destroy()
    for label,command in [('이전 프레임',lambda:step(-1)),('다음 프레임',lambda:step(1)),('재생 / 정지',toggle),
                          ('시작 지정',lambda:set_boundary('first')),('끝 지정',lambda:set_boundary('last')),
                          ('선택 구간 재생',play_selection),('구간 저장',save),('종료',close)]:
        ttk.Button(buttons,text=label,command=command).pack(side='left',padx=3)

    def tick():
        if state['closed']:return
        if state['playing'] and time.perf_counter()>=state['next_at']:
            last=state['last'] if state['selection_only'] else total-1
            if state['index']>=last:state['playing']=False
            else:
                show(state['index']+1);state['next_at']=time.perf_counter()+1/fps
        app.after(10,tick)
    app.protocol('WM_DELETE_WINDOW',close)
    try:show(0);tick();app.mainloop()
    finally:cap.release()


if __name__=='__main__':main()
