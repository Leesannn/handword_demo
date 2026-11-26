"""Validate the draft learning-attempt event and normalize its UTC timestamp."""

from datetime import datetime, timedelta
import re


TARGET_WORDS = frozenset({"커피", "춥다", "감사", "우유", "자다"})
PREDICTIONS = TARGET_WORDS | {"기타", None}
UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|\+00:00)")


def validate_attempt(event):
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("지원하는 schema_version은 정수 1입니다.")
    event_id = event["event_id"]
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
        raise ValueError("event_id는 1~128자의 영문·숫자·밑줄·하이픈이어야 합니다.")
    if event["target_word"] not in TARGET_WORDS or event["predicted_word"] not in PREDICTIONS:
        raise ValueError("지원하지 않는 단어입니다.")
    value = event["occurred_at"]
    if not isinstance(value, str) or not UTC_TIMESTAMP.fullmatch(value):
        raise ValueError("occurred_at은 UTC 표기가 있는 ISO 8601 시각이어야 합니다.")
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("occurred_at은 UTC 기준이어야 합니다.")
    return dict(event, occurred_at=timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
