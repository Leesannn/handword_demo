from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parents[1] / 'assets' / 'diagrams'
OUT.mkdir(parents=True, exist_ok=True)
NAVY = '#142c45'
MUTED = '#536b80'
TEAL = '#087f72'
BLUE = '#245fba'
PURPLE = '#7050b2'
ORANGE = '#b96c1d'


class Diagram:
    def __init__(self, height, tag, title, subtitle):
        self.h = height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="{height}" viewBox="0 0 1280 {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
                      '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#7a8da2"/></marker></defs>',
                      '<rect width="1280" height="100%" fill="#f4f7fb"/>',
                      '<g font-family="Malgun Gothic, Noto Sans KR, Arial, sans-serif">']
        self.text(48, 37, tag, 15, BLUE, 700, spacing='2')
        self.text(48, 85, title, 33, NAVY, 700)
        self.text(48, 118, subtitle, 18, MUTED)

    def rect(self, x, y, w, h, fill='white', stroke='#dce5ee', r=18):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')

    def text(self, x, y, s, size=20, color=NAVY, weight=400, anchor='start', spacing=None):
        extra = f' letter-spacing="{spacing}"' if spacing else ''
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}"{extra}>{escape(s)}</text>')

    def line(self, x1, y1, x2, y2, dashed=False, arrow=True):
        dash = ' stroke-dasharray="7 6"' if dashed else ''
        end = ' marker-end="url(#arrow)"' if arrow else ''
        self.parts.append(f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="#7a8da2" stroke-width="2.4"{dash}{end}/>')

    def path(self, d, dashed=False):
        dash = ' stroke-dasharray="7 6"' if dashed else ''
        self.parts.append(f'<path d="{d}" fill="none" stroke="#7a8da2" stroke-width="2.4"{dash} marker-end="url(#arrow)"/>')

    def pill(self, x, y, text, color, width):
        self.rect(x, y, width, 32, color, color, 16)
        self.text(x + width / 2, y + 22, text, 14, 'white', 700, 'middle')

    def card(self, x, y, w, h, title, lines, color=BLUE, badge=None):
        self.rect(x, y, w, h)
        self.parts.append(f'<rect x="{x}" y="{y + 20}" width="5" height="{h - 40}" rx="2" fill="{color}"/>')
        self.text(x + 22, y + 35, title, 22, color, 700)
        for i, s in enumerate(lines):
            self.text(x + 22, y + 69 + i * 27, s, 18, MUTED)
        if badge:
            self.text(x + w - 18, y + h - 14, badge, 14, color, 700, 'end')

    def save(self, filename, note):
        self.text(48, self.h - 25, note, 16, MUTED)
        self.parts.extend(['</g>', '</svg>'])
        (OUT / filename).write_text('\n'.join(self.parts), encoding='utf-8')



d = Diagram(1040, 'APP EXPERIENCE · LEARNING EVENTS', '화면 조작에서 학습 기록까지', '시작·시도·판정·재시도를 구분한 이벤트 흐름')
d.rect(40, 154, 1200, 266, '#eaf7f3', '#eaf7f3')
d.text(62, 190, '01  PRACTICE  ·  본보기에서 동작 판정까지', 21, TEAL, 700)
for x,title,lines in [(62,'본보기 · 따라 하기',['lesson_started','학습 단위 시작']), (471,'준비 · 시도 시작',['practice_attempt','3 · 2 · 1 후 동작 입력']), (880,'동작 판정',['recognition_result','성공·미인식 결과 기록'])]:
    d.card(x,220,338,150,title,lines,TEAL)
d.line(410,295,459,295)
d.line(819,295,868,295)
d.rect(40,458,1200,278,'#edf3fc','#edf3fc')
d.text(62,495,'02  NEXT ACTION  ·  결과 이후의 사용자 선택',21,BLUE,700)
d.card(62,525,338,170,'실패 후 다시 시작',['retry + practice_attempt','이전 실패와 새 시도 연결','동작 판정 단계로 재진입'],ORANGE)
d.card(471,525,338,170,'한 번 더',['practice_attempt','새 연습 시도 기록','준비 단계부터 반복'],BLUE)
d.card(880,525,338,170,'누적 세 번째 성공',['lesson_completed','학습 완료 기록','닫기·마치기: lesson_ended'],PURPLE)
d.line(1049,380,1049,443)
d.text(1025,412,'결과에 따른 분기',17,MUTED,anchor='end')
d.rect(40,778,1200,180,'#f2edfa','#f2edfa')
d.text(62,818,'03  USER FEEDBACK  ·  번역 후보의 확인과 수정',21,PURPLE,700)
d.text(64,861,'answer_selected',24,PURPLE,700)
d.text(64,899,'was_corrected = false  기존 후보 확인',19,MUTED)
d.text(650,899,'was_corrected = true  다른 낱말로 수정',19,MUTED)
d.text(62,937,'상세 열기·탭 이동 자체는 이벤트 미생성 · 학습 화면 닫기는 lesson_ended',17,MUTED)
d.save('app-learning-events.svg','retry와 practice_attempt는 서로 다른 이벤트 유형 · 두 기록을 연습 두 번으로 중복 집계하지 않음')

d = Diagram(1060,'APP TELEMETRY · ASYNCHRONOUS DELIVERY','단말 판정과 서버 접수의 경계','HTTP 202 접수와 MongoDB 저장 완료를 구분한 비동기 파이프라인')
d.rect(40,154,1200,245,'#eaf7f3','#eaf7f3')
d.text(62,191,'01  ON DEVICE  ·  영상 처리와 판정',21,TEAL,700)
for x,title,lines in [(62,'카메라 · MediaPipe',['59점 × XYZ 좌표','영상은 단말 내부 처리']), (471,'구간 선택 · 전처리',['동작 0.5~3초','모델 입력 30 × 177']), (880,'r0006 GRU · 결과 UI',['Core ML / JavaScript','판정 후 이벤트 생성'])]:
 d.card(x,220,338,145,title,lines,TEAL)
d.line(410,292,459,292);d.line(819,292,868,292)
d.rect(40,438,1200,245,'#edf3fc','#edf3fc')
d.text(62,475,'02  ACCEPTANCE  ·  이벤트 보관과 서버 접수',21,BLUE,700)
for x,title,lines in [(62,'SyncCenter · Outbox',['event_id 유지 · 파일 큐','1.5초 배치 · 최대 100건']), (471,'Caddy · FastAPI',['HTTPS POST /v1/events','인증 · 이벤트 입력 검증']), (880,'Kafka 발행 확인',['학습 이벤트 발행','확인 후 HTTP 202 응답'])]:
 d.card(x,504,338,145,title,lines,BLUE)
d.line(410,576,459,576);d.line(819,576,868,576)
d.path('M1049 660 V712 H231 V660',dashed=True)
d.text(640,739,'점선: 앱으로 돌아오는 접수 응답 · DB 저장 완료 응답과 구분',18,BLUE,anchor='middle')
d.rect(40,778,1200,210,'#f2edfa','#f2edfa')
d.text(62,815,'03  PERSISTENCE  ·  접수 이후 비동기 소비·저장',21,PURPLE,700)
for x,title,lines in [(62,'Spark Streaming',['체크포인트 · 시간 창 집계']), (471,'PrivateLink · TLS',['계정 간 사설 DB 연결']), (880,'MongoDB 원장·집계',['event_id 기반 이벤트 추적'])]:
 d.card(x,842,338,111,title,lines,PURPLE)
d.line(410,899,459,899);d.line(819,899,868,899)
d.path('M1225 579 H1233 V760 H50 V899 H53')
d.save('app-event-delivery.svg','생성 → HTTP 202: 1.53~1.59초 / 제공된 iPhone 이벤트 8건 · Kafka → DB 저장 지연은 별도 측정 필요')
print('Generated 2 app SVG diagrams.')
