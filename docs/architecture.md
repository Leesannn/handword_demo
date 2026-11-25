# 시스템 아키텍처와 설계 판단

기준일은 2026-11-25입니다. 앱 ZIP의 코드·문서, 메인 서버 담당자 제공 보고, DB 담당자의 실제 조회 결과를 통합했습니다.

## 앱 내부 처리

```mermaid
flowchart LR
    A[카메라 프레임] --> B[MediaPipe 손·몸 좌표]
    B --> C[59점 · 177값 조립]
    C --> D[0.5~3초 구간]
    D --> E[30프레임 재표본화]
    E --> F[어깨 중심·너비 정규화]
    F --> G[r0006 GRU]
    G --> H[6개 확률]
    H --> I[단어·미인식·학습 진도]
    I --> J[이벤트 Outbox]
```

- iOS의 `Core`·`Capture`는 SwiftUI 화면 프로젝트에서 공통 엔진으로 참조합니다.
- iOS는 Core ML, Android는 WebView의 JavaScript GRU 계산을 사용합니다. 모델 파일 형식과 실행 엔진이 다르므로 동일 입력 기준의 출력 대조가 필요합니다.
- Android README에 전처리 차이 `2.4e-7`, 확률 차이 `7.6e-8`, 아이폰 샘플 8건의 판정 일치가 보고돼 있습니다. 11월25일 제공 단일 fixture의 순수 엔진 계산을 재실행해 전처리·확률 허용 범위를 통과했습니다. 8건 실기기 샘플 일치는 제공 보고이며 [재검증 범위](app-engine.md)와 구분합니다.
- Android APK는 페이지·MediaPipe WASM·좌표 모델을 앱에 묶는 구성을 제공합니다. Expo Go와 웹 실행은 초기 좌표 모델 다운로드가 필요합니다.
- 영상의 기기 외부 전송을 생략하고 좌표로 추론합니다. 추론 결과와 학습 기록은 서버에 전송합니다.

## 앱에서 MongoDB까지

```mermaid
sequenceDiagram
    participant App as 모바일 Outbox
    participant API as Caddy / FastAPI
    participant K as Kafka
    participant S as Spark
    participant DB as MongoDB
    App->>App: 이벤트 ID를 유지해 로컬 보관
    App->>API: HTTPS 배치 / X-API-Key
    API->>API: 인증·이벤트별 필드·건수 검증
    API->>K: user_id 키로 개별 이벤트 발행
    K-->>API: 발행 확인
    API-->>App: HTTP 202
    App->>App: 수락된 기록을 큐에서 제거
    S->>K: 체크포인트에 따른 소비
    S->>DB: TLS / 원장 및 집계 스냅샷 저장
```

앱의 HTTP 재시도와 Spark 재실행은 같은 이벤트가 다시 처리될 수 있는 조건입니다. 원장에는 `event_id` 기준 중복 방지가 필요하고, 집계에는 재실행 후 같은 결과가 되는 별도 보장이 필요합니다. 원장 한 건 유지 시험과 집계의 장애 후 정확성은 다른 검증 항목입니다.

Kafka 키는 사용자별 순서 유지를 위한 `user_id`입니다. Kafka 오프셋은 파티션 내부 위치이므로 일반적인 처리 식별에는 토픽·파티션·오프셋을 함께 사용합니다. 현재 직접 조회한 원장은 `_id`, `topic`, `offset`, `payload` 네 필드이며 `partition` 필드는 없었습니다. 다중 파티션 확장 시 저장 규격을 보완해야 합니다.

## AWS 네트워크

| 영역 | 배포 구성 |
|---|---|
| 메인 EC2 | 서버 담당 보고 기준 Ubuntu 24.04, `t3.medium`, Docker·Compose |
| 메인 실행 단위 | Caddy, FastAPI, Kafka, Spark |
| DB EC2 | 별도 계정의 `t3.micro`, MongoDB 8.0.34 |
| 서버 간 경로 | 팀 Interface Endpoint → DB Endpoint Service → Internal NLB → MongoDB |
| DB 전송 보호 | TLS 필수, CA 검증, MongoDB 계정 인증 |
| 관리 접속 | SSH 키 인증, 현재 고정 관리 주소 사용 |
| 주소 안정화 | 메인·DB EC2 Elastic IP |

별도 계정의 두 VPC에서 동일한 `172.31.0.0/16` 대역을 사용한 구성이어서, 서비스 단위 PrivateLink로 연결했습니다. 실제 사설 주소의 동일 대역 여부는 계정별 구성의 근거를 기준으로 설명하며, 단순히 두 IP가 `172.31`로 시작한다는 이유만으로 같은 VPC라고 판단하지 않습니다.

DB는 `requireTLS`로 구성했고, 내부 로드밸런서의 대상 상태와 MongoDB 인증·`ping`을 단계별로 확인했습니다. 인증서 개인키와 DB 비밀번호는 서버 측에서 관리합니다.

퍼블릭 Elastic IP는 관리 접속과 앱 HTTPS 주소를 안정화합니다. 서버 간 MongoDB 연결은 PrivateLink DNS를 사용합니다. 계정·서버별 실제 주소는 배포 환경 설정에서 주입합니다.

## 설계 결정

| 결정 | 선택한 이유 | 현재 한계 |
|---|---|---|
| 기기 내 추론 | 서버 수신 없이 단어 판정 가능, 영상 업로드 감소 | 기기별 처리 속도와 모델 동등성 평가 필요 |
| Outbox | 오프라인·응답 유실 시 동일 이벤트 재전송 | 로컬 큐 용량 제한과 장기 실패 정책 존재 |
| Kafka | API 수신과 Spark 처리를 분리하고 재처리 위치 추적 | 보관 기간·소비 지연 운영 필요 |
| Spark | 이벤트 시간 창 집계와 체크포인트 기반 소비 | MongoDB 출력의 멱등성과 집계 정합성 검증 필요 |
| MongoDB 원문 저장 | 원본 필드 보존과 이벤트 ID 대조 | payload 문자열 내부를 직접 인덱싱하기 어려움 |
| 최근 조회 복합 인덱스 | topic 조건과 offset 정렬에 맞는 탐색 | 추가 인덱스의 쓰기·용량 비용 존재 |
| 좌표 파일 S3 분리 계획 | 큰 좌표 본문과 검색 메타데이터 역할 분담 | 실제 S3·샘플 API 통합 검증 필요 |

## 시간 창 통계

서버 담당자는 1분 단어별 연습 횟수, 최근 5분 미인식 비율, 사용자 확인 일치율 집계를 구현했다고 보고했습니다. 통계 해석은 [데이터 계약](data-contract.md)의 이벤트·분모 정의를 사용합니다. 정확한 창 유형, 늦은 이벤트 허용 범위, 워터마크, 원장과 스냅샷의 쓰기 순서는 제공 서버 소스가 없어 최종 설정 확인 항목입니다.

초기 설계의 Delta Lake는 현재 확인한 실제 적재 경로에서 사용 여부가 입증되지 않았습니다. 현재 아키텍처의 저장소는 MongoDB이며 S3 샘플 경로는 후속 단계로 표시합니다.
