# 데이터 흐름과 오류 시 동작

앱의 사용자 동작이 이벤트로 생성되고 Kafka·Spark·MongoDB를 거쳐 추적되는 흐름을 정리합니다.

## 사용자의 동작이 기록이 되는 과정

```mermaid
flowchart TD
    P[사용자가 수어 동작] --> C[카메라에서 프레임 획득]
    C --> L[MediaPipe 손·몸 좌표 추출]
    L --> F[프레임마다 177개 좌표값 구성]
    F --> S[동작 구간을 30프레임으로 재표본화·정규화]
    S --> M[r0006 모델을 기기에서 실행]
    M --> U[단어·후보·미인식 결과 표시]
    U --> E[학습 이벤트 생성]
    E --> O[폰의 Outbox에 event_id와 함께 보관]
```

화면을 열고 학습을 시작하는 행위도 이벤트를 만듭니다. 위 그림의 인식 결과 외에 학습 시작·시도·종료 이벤트가 별도로 존재합니다. 영상은 기기 내 좌표 추출에 사용하고, 서버에는 이벤트 JSON을 전송합니다.

## 실제 적재 경로

```mermaid
flowchart TD
    I[iOS 또는 Android Outbox] -->|HTTPS 이벤트 배치| H[Caddy]
    H --> A[FastAPI 인증·필드·배치 검증]
    A --> V{요청이 유효한가}
    V -->|아니오| X[오류 응답과 앱의 상태별 처리]
    V -->|예| K[Kafka에 이벤트별 발행]
    K --> ACK[발행 확인 후 HTTP 202]
    ACK --> D[앱이 수락된 기록을 큐에서 제거]
    K --> SP[Spark가 체크포인트 기준 소비]
    SP --> N[PrivateLink와 TLS를 통한 DB 연결]
    N --> R[MongoDB 이벤트 원장]
    N --> G[MongoDB 집계 스냅샷]
    R --> Q[event_id·토픽·오프셋 대조]
```

원장은 개별 기록을, 집계 스냅샷은 학습 통계를 저장하는 출력입니다. event_id와 원문을 기준으로 이벤트의 도착을 대조했습니다.

## 요청 수락과 DB 적재의 시점

```mermaid
sequenceDiagram
    participant Phone as 폰 Outbox
    participant API as FastAPI
    participant Kafka as Kafka
    participant Spark as Spark
    participant DB as AWS MongoDB
    Phone->>API: 같은 event_id를 유지한 이벤트 배치
    API->>API: 인증·이벤트 계약 검사
    API->>Kafka: user_id를 키로 발행
    Kafka-->>API: 발행 확인
    API-->>Phone: HTTP 202
    Phone->>Phone: 수락된 로컬 기록 제거
    Spark->>Kafka: 메시지 소비
    Spark->>DB: 원문·집계 저장
    DB-->>Spark: 쓰기 응답
    Note over Phone,DB: event_id와 Kafka 위치로 최종 도착 대조
```

202는 Kafka 발행 수락 시점입니다. DB에서 ID를 조회해 저장 완료를 확인합니다. 사용자가 보내는 실제 샘플 ID나 이벤트 ID는 공개 설명에서는 합성 값으로 대체합니다.

## 장애를 조사하는 순서

```mermaid
flowchart TD
    E[앱에서 보내고 DB에서 찾지 못함] --> A{HTTP 응답 확보}
    A -->|400 · 413 · 422| F[필드·종류·크기 확인]
    A -->|401 · 403| AUTH[키와 인증 설정 확인]
    A -->|202| K{Kafka에 같은 event_id가 있는가}
    K -->|있음| S[Spark 필터·소비 위치·출력 대상 확인]
    K -->|없음| P[API 발행 로그와 토픽 설정 확인]
    S --> D[MongoDB 연결·권한·저장 오류 확인]
    A -->|응답 없음 또는 5xx| R[Outbox 보관·재시도 상태 확인]
```

실제로 202와 Kafka 적재가 확인돼도 시험 세션 필터와 SQLite 출력 때문에 기존 MongoDB 원장에 기록이 없었던 사례가 있었습니다. 각 단계의 상태를 확인해 실제 앱 세션을 받는 MongoDB 상시 저장 경로로 연결했습니다.

## 재전송 시 시간 해석

```mermaid
sequenceDiagram
    participant Event as 앱 동작
    participant Queue as 로컬 Outbox
    participant API as 서버 수신
    participant DB as DB 조회
    Event->>Queue: event_time을 기록
    Note over Queue: 연결 실패·오프라인 대기 가능
    Queue->>API: sent_at을 붙여 배치 전송
    API->>API: received_at 기록
    API->>DB: Kafka·Spark를 통한 비동기 적재
```

event_time은 앱 동작 시각, sent_at은 배치 전송 시각, received_at은 서버 수신 시각입니다. 오프라인 기록의 재전송 여부를 해석할 때 이 시각을 함께 대조했습니다.

