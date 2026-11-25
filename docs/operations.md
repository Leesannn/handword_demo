# 적재 확인과 장애 조사 절차

팀에서 사용한 조사 순서를 정리합니다. 실사용 주소·인증정보는 배포 설정에서 관리합니다. 아래 예시는 권한이 있는 운영자가 기존 인증 경로로 접속한 뒤 사용하는 조회 코드입니다.

## 관측 지점

```mermaid
flowchart LR
    A[앱 event_id·HTTP 응답] --> K[Kafka 토픽·파티션·오프셋]
    K --> S[Spark 소비 위치·필터·출력]
    S --> D[MongoDB 원장·집계]
```

동일 ID의 재전송은 문서 수가 늘지 않을 수 있습니다. 총건수보다 조회 대상 ID·원문·처리 위치를 우선 대조합니다.

## 이벤트 단건 확인

```javascript
// 인증된 mongosh 세션에서 exampleEventId를 실제 조회할 ID로 바꿉니다.
const exampleEventId = "00000000-0000-4000-8000-000000000101";
const ledger = db.getSiblingDB("ksl_demo_video_stream_stats_aws_v1")
  .getCollection("learning_attempt_test_app_events");
const row = ledger.findOne(
  { _id: exampleEventId },
  { _id: 1, topic: 1, offset: 1, payload: 1 }
);
if (row === null) {
  printjson({ found: false });
} else {
  try {
    const event = JSON.parse(row.payload);
    printjson({
      found: true,
      event_id: row._id,
      topic: row.topic,
      offset: row.offset,
      event_type: event.event_type,
      event_time: event.event_time,
      received_at: event.received_at
    });
  } catch (error) {
    printjson({ found: true, event_id: row._id, payload_parse_error: true });
  }
}
```

현재 원장 구조를 전제로 한 문서용 조회 예시입니다. 이번 문서 개정에서 운영 DB에 추가 실행한 명령으로 기록하지 않습니다.

## 응답별 조사

| 증상 | 먼저 조사할 내용 | 다음 확인 |
|---|---|---|
| 400·422 | 이벤트별 허용 필드·타입, count·배열 일치 | 거절 배치 개별 전송·격리 |
| 413 | 요청 본문 크기 | 이벤트 배치 크기 확인 |
| 401·403 | 키·실행 환경 설정 | 앱 재시도와 서버 인증 로그 |
| 404 | BaseURL·경로·배포 버전 | 이벤트 API의 배포 경로 |
| 응답 없음·5xx | 네트워크·API·Kafka | 동일 ID 보존·Outbox 대기 |
| 202 후 원장 없음 | Kafka 발행·Spark 소비·필터·출력 | MongoDB 연결·권한·쓰기 오류 |
| 원장 있음·통계 다름 | 대상 이벤트·분모·시간 창 | 지연·중복·스냅샷 갱신 |

## 실제 문제 해결

### Kafka에는 있고 기존 원장에는 없는 이벤트

Kafka에서 같은 이벤트의 발행을 확인한 뒤 Spark를 조사했습니다. 특정 시험 세션 필터와 SQLite 출력이 사용 중이었습니다. API·Kafka 수락과 조회 대상 원장 적재 사이에 필터·출력 저장소 차이가 있었습니다. 이후 실제 앱 세션을 받는 MongoDB 상시 저장 경로로 연결했습니다.

### 앱 요청의 규격 밖 필드

학습 종료·완료에 attempt, 사용자 선택에 허용하지 않는 항목이 붙어 400이 발생한 사례가 있습니다. 이벤트별 필드 구성과 과거 큐 데이터의 호환 처리 코드를 확인했습니다. 거절 배치를 개별 요청으로 나누는 로직도 정상 항목의 재전송을 지원합니다.

### 관리 SSH 주소 변경

DB EC2 중지·시작 뒤 퍼블릭 IP가 달라져 노트북 조회가 실패했습니다. 현재 주소를 반영해 조회한 뒤 Elastic IP를 연결했습니다. 관리 SSH 실패와 서버 간 PrivateLink 실패는 각 접속 경로의 상태를 따로 조사합니다.

## 재시작·재처리 수행 기록

| 구간 | 팀이 수행한 내용 | 근거 |
|---|---|---|
| 실행 단위 | Caddy·API·Kafka·Spark 컨테이너 자동 재시작 정책 | 서버 담당 보고 |
| 소비 위치 | Spark 체크포인트 사용 | 서버 담당 보고 |
| 누락 복구 | 437~440의 4건을 별도 Spark 배치로 재처리, 총 28건 대조 | 서버 담당 보고 |
| 재기동 후 연결 | PrivateLink 인증 ping과 561~576의 16건 적재 확인 | 서버 담당 보고 |
| 원장 관리 | 실제 ID 대조·임시 컬렉션 반복 쓰기 시험 | DB 직접 수행 |
