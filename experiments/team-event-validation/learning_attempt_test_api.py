"""Local HTTP ingress for an end-to-end synthetic learning-attempt check."""

from datetime import datetime, timezone
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from learning_attempt_contract import validate_attempt


def normalize_team_attempt(event):
    return validate_attempt({
        "schema_version": event["schema_version"], "event_id": event["event_id"],
        "target_word": event["word"], "predicted_word": event.get("predicted_word"),
        "occurred_at": event["event_time"],
    })


def validate_team_sample(batch):
    if not isinstance(batch, dict) or set(batch) != {"sent_at", "count", "events"}:
        raise ValueError("expected sent_at, count, events")
    events = batch["events"]
    if type(batch["count"]) is not int or batch["count"] != 1 or not isinstance(events, list) or len(events) != 1:
        raise ValueError("expected a batch with one test event")
    event = events[0]
    if not isinstance(event, dict) or (event.get("event_type"), event.get("source"), event.get("outcome")) != (
        "recognition_result", "practice", "correct"
    ):
        raise ValueError("expected a correct practice recognition result")
    event = dict(event)
    for field in ("event_id", "user_id", "session_id"):
        event[field] = str(UUID(event[field]))
    for field in ("lesson_id", "app_version", "model_version", "device"):
        if not isinstance(event[field], str) or not event[field].strip() or len(event[field]) > 256:
            raise ValueError(f"invalid {field}")
    if type(event["seq"]) is not int or event["seq"] < 0 or type(event["attempt"]) is not int or event["attempt"] < 1:
        raise ValueError("invalid seq or attempt")
    normalized = normalize_team_attempt(event)
    validate_attempt(dict(normalized, occurred_at=batch["sent_at"]))
    return event


def submit_attempt(request_body, publish, *, team_batch=False):
    endpoint = "/v1/events" if team_batch else "/learning-attempts"
    expected_status = 202 if team_batch else 201
    receipt = None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal receipt
            if self.path != endpoint:
                self.respond(404, {"error": "unknown endpoint"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("JSON must be 1–4096 bytes")
                payload = json.loads(self.rfile.read(size))
                if team_batch:
                    event = validate_team_sample(payload)
                    event = {field: value for field, value in event.items() if value is not None}
                    received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    event.update(sent_at=payload["sent_at"], received_at=received_at)
                else:
                    if not isinstance(payload, dict) or set(payload) != {"target_word", "predicted_word", "occurred_at"}:
                        raise ValueError("expected target_word, predicted_word, occurred_at")
                    event = validate_attempt(dict(payload, schema_version=1, event_id=f"api-probe-{uuid4().hex}"))
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                self.respond(422 if team_batch else 400, {"error": str(error)})
                return
            try:
                ack = publish(event)
            except Exception as error:
                self.respond(503, {"error": f"Kafka publish failed: {type(error).__name__}"})
                return
            receipt = {"event_id": event["event_id"], "partition": ack.partition, "offset": ack.offset}
            if team_batch:
                receipt.update(sent_at=event["sent_at"], received_at=event["received_at"])
            self.respond(expected_status, {"accepted": True, "count": 1} if team_batch else receipt)

        def respond(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}{endpoint}",
                              data=request_body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=20) as response:
                if response.status != expected_status:
                    raise RuntimeError(f"expected HTTP {expected_status}, got {response.status}")
                payload = json.load(response)
                expected = {"accepted": True, "count": 1} if team_batch else receipt
                if receipt is None or payload != expected:
                    raise RuntimeError("unexpected HTTP response or missing Kafka acknowledgement")
                return receipt
        finally:
            server.shutdown()
            worker.join()
