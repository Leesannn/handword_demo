"""로컬 전용 비동기 특징 추론 시제품. SQLite 저장, 단일 추론 스레드."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

def now():
    return datetime.now(timezone.utc).isoformat()

class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)

def validate_input(value):
    import numpy as np
    from predict_feature_json import BASE_VERSION, REQUEST_VERSION
    from hand_local_features import transform
    if not isinstance(value, dict) or value.get('schema_version') != REQUEST_VERSION:
        raise ValueError('특징 요청 버전이 다릅니다.')
    if not isinstance(value.get('request_id'), str) or not value['request_id'].strip():
        raise ValueError('특징 입력의 request_id가 필요합니다.')
    if value.get('preprocessing_version') != BASE_VERSION or value.get('input_kind') != 'normalized_xy118_mask59':
        raise ValueError('전처리 버전·입력 의미를 확인하세요. 원시 XYZ 입력은 받지 않습니다.')
    x = np.asarray(value.get('features'))
    if x.shape != (30, 177) or x.dtype.kind not in 'fiu':
        raise ValueError('features는 숫자로 된 (30,177) 배열이어야 합니다.')
    with np.errstate(over='ignore', invalid='ignore'):
        x = x.astype(np.float32)
    transform(x, 'local_hands_keep_pose_add_wrists')
    if not x[:, 118:160].any():
        raise ValueError('사용 가능한 손 좌표가 없습니다.')

class JobService:
    def __init__(self, db, predictor, validator=validate_input, capacity=8):
        self.db = Path(db)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.predictor, self.validator = predictor, validator
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(capacity)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inference')
        self.closed = False
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS jobs (
                sequence_id TEXT PRIMARY KEY, client_request_id TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                result_json TEXT, error_code TEXT)''')
            # 이전 프로세스의 실행 중 입력은 메모리에만 있으므로 자동 재시도하지 않습니다.
            con.execute("UPDATE jobs SET status='failed', error_code='SERVER_RESTARTED', updated_at=? WHERE status IN ('queued','processing')", (now(),))

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def get(self, sequence_id):
        with self.connect() as con:
            row = con.execute('SELECT * FROM jobs WHERE sequence_id=?', (sequence_id,)).fetchone()
        if row is None:
            raise APIError(404, 'JOB_NOT_FOUND', '해당 작업이 없습니다.')
        return self.public(row)

    @staticmethod
    def public(row):
        return {'schema_version': 'sign-job-v1', 'sequence_id': row['sequence_id'],
                'client_request_id': row['client_request_id'], 'status': row['status'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'result': json.loads(row['result_json']) if row['result_json'] else None,
                'error': {'code': row['error_code']} if row['error_code'] else None}

    def submit(self, payload):
        if not isinstance(payload, dict):
            raise APIError(422, 'INVALID_REQUEST', 'JSON 객체가 필요합니다.')
        key, value = payload.get('client_request_id'), payload.get('input')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key):
            raise APIError(422, 'INVALID_REQUEST', 'client_request_id는 영문·숫자·밑줄·하이픈 1~80자입니다.')
        try:
            self.validator(value)
            fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        except (ValueError, TypeError, OverflowError) as exc:
            raise APIError(422, 'INVALID_FEATURE_INPUT', str(exc)) from exc
        with self.lock:
            with self.connect() as con:
                previous = con.execute('SELECT * FROM jobs WHERE client_request_id=?', (key,)).fetchone()
                if previous:
                    if previous['fingerprint'] != fingerprint:
                        raise APIError(409, 'IDEMPOTENCY_CONFLICT', '같은 요청 키에 다른 입력을 사용할 수 없습니다.')
                    return self.public(previous), True
                if self.closed or not self.slots.acquire(blocking=False):
                    raise APIError(503, 'QUEUE_FULL', '대기열이 가득 찼습니다. 잠시 후 같은 요청으로 재시도하세요.')
                job_id = str(uuid.uuid4())
                stamp = now()
                try:
                    con.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                                (job_id, key, fingerprint, 'queued', stamp, stamp, None, None))
                except Exception:
                    self.slots.release()
                    raise
            # 접수 응답은 추론 완료를 기다리지 않습니다.
            accepted = self.get(job_id)
            try:
                self.executor.submit(self.run, job_id, value)
            except Exception:
                self.update(job_id, 'failed', error='SCHEDULING_FAILED')
                self.slots.release()
                raise APIError(503, 'SCHEDULING_FAILED', '작업 실행 예약에 실패했습니다.')
            return accepted, False

    def update(self, job_id, status, result=None, error=None):
        data = json.dumps(result, ensure_ascii=False, allow_nan=False) if result is not None else None
        with self.connect() as con:
            con.execute('UPDATE jobs SET status=?, updated_at=?, result_json=?, error_code=? WHERE sequence_id=?',
                        (status, now(), data, error, job_id))

    def run(self, job_id, value):
        try:
            self.update(job_id, 'processing')
            result = self.predictor.predict(value)
            self.update(job_id, 'completed', result=result)
        except Exception:
            self.update(job_id, 'failed', error='INFERENCE_FAILED')
        finally:
            self.slots.release()

    def close(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=True)

def create_server(service, port=8766):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def handle_api(self, method):
            try:
                if method == 'GET' and self.path == '/health':
                    if hasattr(service, 'check_storage'):
                        service.check_storage()
                    return self.respond(200, {'status': 'ready', 'storage': getattr(service, 'storage_name', 'sqlite'),
                        'model_sha256': service.predictor.model_hash, 'local_only': True})
                if method == 'GET' and self.path.startswith('/jobs/'):
                    key = self.path[len('/jobs/'):]
                    if not re.fullmatch(r'[a-f0-9-]{36}', key):
                        raise APIError(404, 'JOB_NOT_FOUND', '해당 작업이 없습니다.')
                    return self.respond(200, service.get(key))
                if method == 'POST' and self.path == '/jobs':
                    if self.headers.get('Transfer-Encoding'):
                        raise APIError(400, 'UNSUPPORTED_ENCODING', 'Content-Length가 필요합니다.')
                    try:
                        length = int(self.headers.get('Content-Length', '0'))
                    except ValueError:
                        raise APIError(400, 'INVALID_LENGTH', '길이 헤더가 올바르지 않습니다.')
                    if not 0 < length <= 1_000_000:
                        raise APIError(413, 'BODY_SIZE', '요청은 1바이트~1MB 범위여야 합니다.')
                    raw = self.rfile.read(length)
                    try:
                        payload = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                    except (ValueError, UnicodeDecodeError):
                        raise APIError(422, 'INVALID_JSON', '표준 JSON 형식이 필요합니다.')
                    record, reused = service.submit(payload)
                    return self.respond(200 if reused else 202, {**record, 'reused': reused})
                raise APIError(404, 'NOT_FOUND', '없는 API 경로입니다.')
            except APIError as exc:
                self.respond(exc.status, {'error': {'code': exc.code, 'message': exc.message}})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.respond(500, {'error': {'code': 'INTERNAL_ERROR', 'message': '서버 내부 오류입니다.'}})

        def do_GET(self): self.handle_api('GET')
        def do_POST(self): self.handle_api('POST')
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)

def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--model-dir', type=Path, default=root/'model')
    parser.add_argument('--db', type=Path, default=root/'runtime/jobs.sqlite3')
    args = parser.parse_args()
    from predict_feature_json import SignFeaturePredictor
    service = JobService(args.db, SignFeaturePredictor(args.model_dir))
    try:
        server = create_server(service, args.port)
    except Exception:
        service.close()
        raise
    print('로컬 비동기 작업 API: http://127.0.0.1:'+str(server.server_port), flush=True)
    print('작업 저장소:', service.db.resolve(), flush=True)
    print('이 창은 유지하세요. 종료: Ctrl+C / Kafka·MongoDB·AWS 연결 전 시제품', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()

if __name__ == '__main__': main()
