# 수어 학습 앱 AWS 서버 구축 및 데이터 파이프라인 연동

## 담당 범위

AWS EC2 실행 환경을 구축하고, 아이폰 앱이 보낸 학습 이벤트를 HTTPS로 받아 Kafka와 Spark를 거쳐 팀 MongoDB에 저장하는 경로를 구현·배포했다. 서버 재시작, 연결 장애 확인, 누락 데이터 재처리, 팀원 인수인계 절차도 마련했다.

```text
아이폰 앱 → HTTPS / Caddy → FastAPI POST /v1/events
          → Kafka → Spark Structured Streaming
          → AWS PrivateLink → DB 담당자 서버의 MongoDB
```

## 구현 및 배포

| 영역 | 수행한 작업 |
| --- | --- |
| AWS EC2·Docker | 서울 리전의 Ubuntu 24.04 EC2(`t3.medium`)에 Docker와 Docker Compose 실행 환경을 구성했다. 외부 HTTPS와 관리자 SSH를 보안 그룹으로 제어하고, Kafka와 Spark는 Docker 내부 네트워크에서 연결했다. |
| 고정 공인 IP·HTTPS | EC2 중지·시작 시 앱 주소가 바뀌는 문제를 해결하기 위해 Elastic IP를 연결했다. Caddy를 고정 IP에 맞춰 갱신하고 Let’s Encrypt 인증서 발급을 확인했다. FastAPI, Caddy, Kafka, Spark에 Docker 자동 재시작 정책을 적용했다. |
| FastAPI | `POST /v1/events`에 `X-API-Key` 인증과 JSON 배치 검증을 적용했다. 요청당 최대 100건, 본문 최대 1MB를 허용하며, Kafka에서 모든 이벤트 발행을 확인한 뒤 HTTP `202`를 반환한다. |
| Kafka | 학습 시작·연습 시도·인식 결과·재시도·학습 완료·학습 종료·정답 선택 이벤트를 개별 JSON 메시지로 발행했다. 메시지 키는 `user_id`이며 `event_id`, 앱 이벤트 시각, 서버 수신 시각을 보존한다. |
| Spark Structured Streaming | 1분 단어별 연습 횟수, 최근 5분 인식 실패율, 사용자 확인 일치율을 집계했다. 체크포인트에 Kafka 처리 위치를 보존하고, 실제 앱 세션을 받는 상시 작업을 배포했다. |
| MongoDB | Spark에서 PrivateLink를 통해 DB 담당자 서버의 MongoDB에 연결했다. 이벤트 원문과 집계 스냅샷을 별도 컬렉션에 저장한다. 원장의 `event_id`를 문서 키로 사용해 같은 ID가 재전송돼도 중복 문서가 생기지 않도록 했다. 기존 SQLite 테스트 작업은 종료했다. |
| 운영·인수인계 | Kafka 오프셋, Spark 체크포인트, MongoDB 원장을 대조해 각 구간의 상태를 확인하는 절차를 정리했다. DB 담당자 환경에서도 동일한 `event_id`와 오프셋을 확인할 수 있도록 조회 방법을 문서화했다. |

## 검증 결과

| 검증 항목 | 결과 |
| --- | --- |
| 실제 아이폰 자동 저장 | SQLite 테스트 작업이 꺼진 상태에서 Kafka 오프셋 `504~560`의 아이폰 이벤트 57건이 Spark를 거쳐 MongoDB에 자동 저장됐다. `event_id`, 오프셋, JSON 원문이 모두 일치했다. |
| 누락 이벤트 재처리 | Kafka 오프셋 `437~440`의 누락 이벤트 4건을 별도 Spark 배치로 처리했다. 기존 MongoDB 문서 24건에 변경이나 중복 없이 총 28건이 대조 결과와 일치했다. 상시 Spark 작업과 체크포인트는 유지했다. |
| EC2 중지·시작 후 연결 | PrivateLink를 통한 MongoDB `ping` 결과 `{ ok: 1 }`을 확인했다. Kafka 오프셋 `561~576`의 이벤트 16건이 모두 MongoDB에 저장됐다. |
| Elastic IP HTTPS 전환 | EC2 재시작 없이 Caddy 설정을 적용하고 고정 IP의 인증서 발급을 확인했다. 외부에서 인증서 검증을 거친 `POST /v1/events` 요청이 FastAPI에 도달했다. 키 없이 보낸 확인 요청에는 예상대로 HTTP `401`이 반환됐다. |
