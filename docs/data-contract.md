# 이벤트 계약과 MongoDB 데이터 구조

## POST /v1/events

| 항목 | 계약 |
|---|---|
| 전송 | HTTPS, JSON |
| 인증 | `X-API-Key`, 실제 값은 배포 설정에서 주입 |
| 배치 | 최대 100건, `count`와 `events` 길이 일치 |
| 본문 크기 | 서버 담당 보고 기준 최대 1MB |
| 수락 | 모든 이벤트 Kafka 발행 확인 후 HTTP 202 |
| 원장 확인 | 비동기 소비 후 동일 event_id로 MongoDB 대조 |

아래 값은 설명용 합성 예시입니다.

```json
{
  "sent_at": "2026-11-25T00:14:07.000Z",
  "count": 1,
  "events": [
    {
      "event_id": "00000000-0000-4000-8000-000000000101",
      "schema_version": 1,
      "event_type": "lesson_started",
      "event_time": "2026-11-25T00:14:06.000Z",
      "seq": 1,
      "user_id": "00000000-0000-4000-8000-000000000201",
      "session_id": "00000000-0000-4000-8000-000000000301",
      "app_version": "1.0",
      "model_version": "r0006",
      "device": "example-device",
      "source": "practice",
      "lesson_id": "00000000-0000-4000-8000-000000000401",
      "word": "커피"
    }
  ]
}
```

## 식별자와 시각

| 필드 | 의미 |
|---|---|
| event_id | 재전송에서 유지하는 이벤트 식별자 |
| user_id | 앱이 만든 익명 사용자 식별자, 물리 기기의 영구 ID로 보장되지 않음 |
| session_id | 앱 실행 세션 |
| lesson_id | 따라 하기 시작부터 종료까지의 학습 단위 |
| reading_id | 한 번의 인식 결과, 사용자 선택과 샘플 연결 |
| sample_id | 별도 좌표 샘플 ID |
| seq | 앱이 관리하는 사용자별 기록 순번 |
| event_time | 폰에서 동작이 발생한 시각 |
| sent_at | 앱이 배치를 전송한 시각 |
| received_at | API가 수신한 시각 |

시간은 UTC ISO 8601을 사용합니다. `received_at`은 DB 저장 완료 시각이 아닙니다. `received_at - event_time`에는 오프라인 대기와 전송 대기가 함께 포함될 수 있으므로 순수 네트워크 지연으로 해석하지 않습니다.

## 이벤트별 데이터

| event_type | 공통 필드 외 주요 값 |
|---|---|
| lesson_started | source, lesson_id, word |
| practice_attempt | source, lesson_id, word, attempt |
| recognition_result | source, outcome, 모드에 따른 목표·인식 결과 |
| retry | source, lesson_id, word, attempt, previous_outcome |
| lesson_completed | source, lesson_id, word, total_attempts, success_count |
| lesson_ended | source, lesson_id, word, total_attempts, success_count |
| answer_selected | source, reading_id, predicted_word, selected_word, was_corrected, confidence, probabilities, 선택적 sample_id |

`recognition_result`에는 판정 상황에 따라 `is_correct`, `predicted_word`, `confidence`, `target_probability`, `probabilities`, `duration_ms`, `hand_missing_ratio`, `reading_id`, `sample_id`가 포함됩니다. 각 필드는 판정 상황에 따른 선택 필드로 정의돼 있습니다.

규격서의 허용 필드와 실제 API 모델이 함께 관리돼야 합니다. 제공 문서에서 사용하지 않는 필드를 붙여 HTTP 400이 발생했던 사례가 보고됐습니다.

## 통계의 분모

서버 담당 보고의 통계는 1분 단어별 연습 횟수, 최근 5분 미인식 비율, 사용자 확인 일치율입니다. 다음 표는 앱 규격에 정의된 각 지표의 원천과 분모를 설명합니다.

| 지표 | 기준 |
|---|---|
| 단어별 연습 횟수 | practice_attempt 이벤트, word와 event_time 기준 |
| 학습 정답 비율 | practice의 recognition_result 중 is_correct=true 비율 |
| 미인식 비율 | recognition_result 중 unsure·unknown·hands_unseen·no_hands·too_short 비율 |
| 사용자 확인 일치율 | answer_selected 중 was_corrected=false 비율 |

`wrong_word`는 목표와 다른 단어로 판정한 결과입니다. 앱 규격상 미인식 분자에는 포함하지 않습니다. `read`는 번역 모드의 읽기 성공 결과입니다. 사용자 확인 일치율은 모델의 독립 평가 정확도와 구분해 해석합니다. 위 표의 정의는 제공 앱 규격서에 근거합니다.

번역 인식 결과와 사용자 선택은 reading_id로 연결합니다. [Kafka·Spark 처리 내용](streaming-semantics.md)

## 실제 원장 저장

컬렉션은 `ksl_demo_video_stream_stats_aws_v1.learning_attempt_test_app_events`입니다. 11월 24일 최근 100건을 검사해 다음 최상위 구조를 확인했습니다.

```json
{
  "_id": "00000000-0000-4000-8000-000000000101",
  "topic": "<configured-topic>",
  "offset": 123,
  "payload": "{\"event_id\":\"00000000-0000-4000-8000-000000000101\",\"event_type\":\"lesson_started\",\"device\":\"example-device\"}"
}
```

위 예시는 필드를 줄인 합성 문서입니다. 실제 payload에는 배치 전송·서버 수신 시각도 포함됩니다.

| payload 내부 자료형 | 확인한 필드 |
|---|---|
| 문자열 | event_id, event_type, event_time, user_id, session_id, app_version, model_version, device, source, lesson_id, word, sent_at, received_at, outcome, predicted_word, reading_id, sample_id, previous_outcome |
| 정수 | schema_version, seq, attempt, total_attempts, success_count, duration_ms |
| 불리언 | is_correct |
| 실수 | confidence, target_probability, hand_missing_ratio |
| 객체 | probabilities |

내부 항목은 payload를 JSON으로 해석했을 때의 자료형입니다. 최상위 MongoDB 필드의 BSON 자료형은 payload 문자열입니다. `selected_word`, `was_corrected`는 앱 계약 필드이며 해당 100건에서 관측된 필드 목록과는 구분합니다.

| 인덱스 | 키 | 상태 |
|---|---|---|
| _id_ | _id | MongoDB 기본 고유 인덱스 |
| topic_offset_desc | topic 오름차순, offset 내림차순 | 팀 DB 최적화 작업에서 추가 |

## 기기 구분

직접 조회에서는 아이폰 `device=iPhone19,7`, `app_version=1.0`과 Android `device=android-16`, `app_version=1.0-expo`를 확인했습니다. Android 값만으로 제조사·갤럭시 모델까지 확정할 수 없습니다. 사용자 ID는 앱 인스턴스를 구분하는 식별자로 사용했습니다.
