"""Verify the local Kafka → Spark → MongoDB path with synthetic attempts."""

import argparse
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from uuid import UUID, uuid4

from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from learning_attempt_contract import validate_attempt
from learning_attempt_test_api import normalize_team_attempt, submit_attempt
from test_learning_attempt_stream import BROKER


TOPIC = "ksl.demo.learning-attempt.mongodb-test.v1"
TEAM_CONTRACT_TOPIC = "ksl.demo.team-contract-test.v1"
DATABASE = "ksl_demo_learning_attempt_local_v1"
AWS_STATS_DATABASE = "ksl_demo_video_stream_stats_aws_v1"
WINDOW_MINUTES = (1, 5)
KAFKA_SPARK_PACKAGE = "org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.3"
KAFKA_SPARK_JARS = (
    "com.google.code.findbugs_jsr305-3.0.0.jar",
    "org.apache.commons_commons-pool2-2.12.0.jar",
    "org.apache.hadoop_hadoop-client-api-3.4.1.jar",
    "org.apache.hadoop_hadoop-client-runtime-3.4.1.jar",
    "org.apache.kafka_kafka-clients-3.9.1.jar",
    "org.apache.spark_spark-sql-kafka-0-10_2.13-4.0.3.jar",
    "org.apache.spark_spark-token-provider-kafka-0-10_2.13-4.0.3.jar",
    "org.lz4_lz4-java-1.8.0.jar",
    "org.scala-lang.modules_scala-parallel-collections_2.13-1.2.0.jar",
    "org.slf4j_slf4j-api-2.0.16.jar",
    "org.xerial.snappy_snappy-java-1.1.10.7.jar",
)


def prepare_topic(broker, topic=TOPIC):
    with closing(KafkaAdminClient(bootstrap_servers=broker, request_timeout_ms=10000)) as admin:
        try:
            admin.create_topics([NewTopic(topic, 1, 1, topic_configs={"retention.ms": "86400000"})])
        except TopicAlreadyExistsError:
            pass


def producer_client(broker):
    return closing(KafkaProducer(
        bootstrap_servers=broker, acks="all",
        value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
    ))


def check_broker(broker):
    with closing(KafkaAdminClient(bootstrap_servers=broker, request_timeout_ms=10000)) as admin:
        metadata = admin.describe_cluster()
        topic_exists = TOPIC in admin.list_topics()
    brokers = metadata["brokers"]
    if not brokers:
        raise RuntimeError("Kafka가 브로커 주소를 반환하지 않았습니다.")
    for advertised in brokers:
        host, port = advertised["host"], advertised["port"]
        with socket.create_connection((host, port), timeout=5):
            print(f"[PASS] Kafka가 알려 준 주소로 TCP 접속: {host}:{port}", flush=True)
    print(f"Kafka 클러스터 ID: {metadata.get('cluster_id') or '(미제공)'}", flush=True)
    print(f"시험 토픽 {TOPIC}: {'존재' if topic_exists else '미생성 또는 조회 권한 없음'}", flush=True)


def fixture(event_id):
    return {"schema_version": 1, "event_id": event_id, "target_word": "커피",
            "predicted_word": "커피", "occurred_at": "2026-11-20T01:00:10Z"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish-id", help="지정 ID의 규약 예시 한 건을 Kafka에 발행")
    mode.add_argument("--receive-id", help="지정 ID의 외부 발행 예시 한 건이 MongoDB에 반영되는지 검사")
    mode.add_argument("--external-probe", action="store_true",
                      help="별도 프로세스로 테스트 이벤트 한 건을 발행하고 수신·집계를 검사")
    mode.add_argument("--api-probe", type=Path, metavar="JSON",
                      help="JSON을 로컬 모의 API에 POST하고 Kafka·MongoDB까지 검사")
    mode.add_argument("--team-api-probe", type=Path, metavar="JSON",
                      help="팀 형식의 JSON으로 로컬 모의 /v1/events부터 MongoDB까지 검사")
    mode.add_argument("--team-receive-id", metavar="UUID",
                      help="기존 팀 Kafka 토픽에서 지정한 이벤트를 읽어 MongoDB 저장을 검증")
    mode.add_argument("--check-broker", action="store_true", help="Kafka 접속과 클라이언트에 알려 준 주소 조회")
    parser.add_argument("--broker", default=BROKER, help="테스트 Kafka 접속 주소")
    parser.add_argument("--team-topic", help="팀 수신 검사에 사용할 기존 Kafka 테스트 토픽")
    parser.add_argument("--team-partition", type=int, help="지정 오프셋을 읽을 Kafka 파티션")
    parser.add_argument("--team-offsets", type=int, nargs="+", metavar="OFFSET",
                        help="유한 범위에서 정확히 확인할 Kafka 오프셋")
    parser.add_argument("--lookback-minutes", type=int, default=30,
                        help="팀 수신 검사가 되돌아볼 Kafka 메시지 시간 범위(기본 30분)")
    parser.add_argument("--verify-team-retry", action="store_true",
                        help="팀 API 검사에서 재전송과 같은 사용자의 새 이벤트도 확인")
    parser.add_argument("--verify-team-restart", action="store_true",
                        help="팀 API 재전송 검사를 같은 Spark 체크포인트의 재시작까지 포함해 실행")
    parser.add_argument("--verify-team-rejections", action="store_true",
                        help="팀 API 검사에서 잘못된 요청 세 가지의 HTTP 422와 발행 차단을 확인")
    parser.add_argument("--aws-tunnel", action="store_true",
                        help="기존 SSH 터널(127.0.0.1:27018)과 AWS 통계 DB의 전용 검사 컬렉션 사용")
    parser.add_argument("--mongo-host", help="AWS MongoDB의 PrivateLink DNS 주소")
    parser.add_argument("--mongo-ca-file", type=Path, help="PrivateLink MongoDB 서버를 신뢰할 공개 CA 파일")
    args = parser.parse_args()
    team_batch = args.team_api_probe is not None
    live_team = args.team_receive_id is not None
    team_wire = team_batch or live_team
    exact_offsets = args.team_offsets is not None
    if exact_offsets != (args.team_partition is not None):
        parser.error("--team-partition과 --team-offsets를 함께 입력하세요.")
    if exact_offsets and (not live_team or args.team_partition < 0 or min(args.team_offsets) < 0):
        parser.error("팀 수신 검사에서 0 이상의 파티션과 오프셋을 입력하세요.")
    if exact_offsets and len(set(args.team_offsets)) != len(args.team_offsets):
        parser.error("같은 Kafka 오프셋을 여러 번 지정할 수 없습니다.")
    direct_mongo = args.mongo_host is not None
    if direct_mongo != (args.mongo_ca_file is not None) or (direct_mongo and (args.aws_tunnel or not live_team)):
        parser.error("팀 수신 검사에서 --mongo-host와 --mongo-ca-file을 함께 사용하세요.")
    if direct_mongo and not args.mongo_ca_file.is_file():
        parser.error("--mongo-ca-file의 공개 CA 파일을 찾을 수 없습니다.")
    aws_mongo = args.aws_tunnel or direct_mongo
    team_event_id = None
    if live_team:
        try:
            team_event_id = UUID(args.team_receive_id)
        except ValueError:
            parser.error("--team-receive-id에 요청에 사용한 event_id UUID를 입력하세요.")
        if not args.team_topic or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.team_topic):
            parser.error("--team-topic에 확인한 Kafka 테스트 토픽 하나를 입력하세요.")
        if args.lookback_minutes < 1:
            parser.error("--lookback-minutes는 1 이상이어야 합니다.")
        args.receive_id = str(team_event_id)
    elif args.team_topic is not None:
        parser.error("--team-topic은 --team-receive-id 검사에 사용하세요.")
    verify_team_retry = args.verify_team_retry or args.verify_team_restart
    if (verify_team_retry or args.verify_team_rejections) and not team_batch:
        parser.error("팀 추가 검사에는 --team-api-probe가 필요합니다.")
    if team_batch and (args.aws_tunnel or args.broker != BROKER):
        parser.error("--team-api-probe는 로컬 Kafka와 MongoDB에서 실행하세요.")
    topic = TEAM_CONTRACT_TOPIC if team_batch else TOPIC
    if live_team:
        topic = args.team_topic
    if args.check_broker:
        check_broker(args.broker)
        return
    if args.publish_id:
        event = validate_attempt(fixture(args.publish_id))
        prepare_topic(args.broker)
        with producer_client(args.broker) as producer:
            sent = producer.send(TOPIC, key=event["event_id"].encode(), value=event).get(timeout=10)
        print(f"발행 확인: {sent.topic} / 파티션 {sent.partition} / 오프셋 {sent.offset}", flush=True)
        return
    if args.external_probe:
        args.receive_id = f"backend-probe-{uuid4().hex}"
    expected_external = validate_attempt(fixture(args.receive_id)) if args.receive_id and not live_team else None
    try:
        request_path = args.team_api_probe or args.api_probe
        request_body = request_path.read_bytes() if request_path else None
        if team_batch:
            batch = json.loads(request_body)
            batch["events"][0]["event_id"] = str(uuid4())
            request_body = json.dumps(batch, ensure_ascii=False).encode("utf-8")
            if verify_team_retry:
                first_event = batch["events"][0]
                additional_event = dict(first_event, event_id=str(uuid4()),
                                        seq=first_event["seq"] + 1, attempt=first_event["attempt"] + 1)
    except OSError as error:
        parser.exit(1, f"요청 JSON을 읽을 수 없습니다: {error}\n")
    except (ValueError, KeyError, IndexError, TypeError) as error:
        parser.exit(1, f"팀 이벤트 예시 JSON을 확인하세요: {error}\n")
    api_ack = None
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
    os.environ["SPARK_LOCAL_HOSTNAME"] = "localhost"
    from pyspark.sql import SparkSession, functions as F

    run_id = team_event_id.hex if live_team else uuid4().hex
    options = {"host": "127.0.0.1", "port": 27017, "serverSelectionTimeoutMS": 5000, "tz_aware": True}
    database_name = DATABASE
    collection_prefix = ""
    if aws_mongo:
        database_name = AWS_STATS_DATABASE
        collection_prefix = "learning_attempt_test_"
        options.update(directConnection=True, username="ksl_pipeline",
                       password=getpass("ksl_pipeline 비밀번호: "), authSource="admin")
        if direct_mongo:
            options.update(host=args.mongo_host, tls=True, tlsCAFile=str(args.mongo_ca_file.resolve()))
        else:
            options.update(port=27018)

    with MongoClient(**options) as client:
        options.pop("password", None)
        try:
            client.admin.command("ping")
        except ServerSelectionTimeoutError:
            if direct_mongo:
                parser.exit(1, "PrivateLink MongoDB에 접속하지 못했습니다. 실행 서버의 DNS·포트·TLS 인증서를 확인하세요.\n")
            if not args.aws_tunnel:
                raise
            parser.exit(1, "AWS MongoDB에 접속하지 못했습니다. SSH 터널(127.0.0.1:27018)과 EC2의 MongoDB 실행 상태를 확인하세요.\n")
        except OperationFailure as error:
            if not aws_mongo or error.code != 18:
                raise
            parser.exit(1, "AWS MongoDB 인증 실패(코드 18). ksl_pipeline 계정 비밀번호를 확인하고 다시 실행하세요.\n")
        if aws_mongo:
            users = client.admin.command("connectionStatus")["authInfo"]["authenticatedUsers"]
            if {"user": "ksl_pipeline", "db": "admin"} not in users:
                raise RuntimeError("터널에서 파이프라인 전용 계정 인증을 확인하지 못했습니다.")
            print("AWS MongoDB 인증 확인", flush=True)
        if live_team:
            with closing(KafkaAdminClient(bootstrap_servers=args.broker, request_timeout_ms=10000)) as admin:
                if topic not in admin.list_topics():
                    parser.exit(1, f"지정 Kafka 테스트 토픽을 찾지 못했습니다: {topic}\n")
        else:
            prepare_topic(args.broker, topic)
        key_field = "user_id" if team_batch else "event_id"

        def submit_api_request(body, *, rejected_case=None):
            publication_attempted = False
            with producer_client(args.broker) as api_producer:
                def publish(event):
                    nonlocal publication_attempted
                    publication_attempted = True
                    return api_producer.send(topic, key=event[key_field].encode("ascii"), value=event).get(timeout=10)

                try:
                    ack = submit_attempt(body, publish, team_batch=team_batch)
                except HTTPError as error:
                    with error:
                        reason = json.load(error)["error"]
                    if rejected_case:
                        if error.code != 422 or publication_attempted:
                            raise AssertionError(f"{rejected_case}: HTTP {error.code}, 발행 호출={publication_attempted}") from error
                        print(f"[PASS] {rejected_case} / HTTP 422 / Kafka 발행 호출 0회", flush=True)
                        return None
                    parser.exit(1, f"모의 API HTTP {error.code}: {reason}\n")
                if rejected_case:
                    raise AssertionError(f"{rejected_case}: 거부해야 할 요청이 수락됐습니다.")
                return ack

        if request_body is not None:
            if args.verify_team_rejections:
                sample_event = batch["events"][0]
                missing_lesson = dict(sample_event)
                missing_lesson.pop("lesson_id", None)
                invalid_requests = (
                    ("이벤트 개수 불일치", dict(batch, count=2)),
                    ("잘못된 event_id UUID", dict(batch, events=[dict(sample_event, event_id="invalid-uuid")])),
                    ("학습 모드의 lesson_id 누락", dict(batch, events=[missing_lesson])),
                )
                for label, invalid_request in invalid_requests:
                    invalid_body = json.dumps(invalid_request, ensure_ascii=False).encode("utf-8")
                    submit_api_request(invalid_body, rejected_case=label)
            api_ack = submit_api_request(request_body)
            args.receive_id = api_ack["event_id"]
            if team_batch:
                expected_external = normalize_team_attempt(batch["events"][0])
                team_user_id = str(UUID(batch["events"][0]["user_id"]))
                print(f"[PASS] 모의 POST /v1/events HTTP 202 / event_id: {args.receive_id}", flush=True)
            else:
                expected_external = validate_attempt(dict(json.loads(request_body), schema_version=1,
                                                          event_id=args.receive_id))
                print(f"[PASS] 모의 API HTTP 201 / event_id: {args.receive_id}", flush=True)
            print(f"[PASS] Kafka 발행: {topic} / 파티션 {api_ack['partition']} / 오프셋 {api_ack['offset']}", flush=True)
        database = client[database_name]
        ledger = database[collection_prefix + "attempt_events"]
        ledger.create_index("run_id")
        totals = database[collection_prefix + "word_totals"]
        windows = database[collection_prefix + "word_windows"]
        windows.create_index([("run_id", 1), ("window_minutes", 1)])
        offsets = database[collection_prefix + "test_offsets"]
        print(f"검사 ID: {run_id} / MongoDB: {database_name}", flush=True)
        ivy_dir = Path(tempfile.gettempdir()) / "ksl-spark-ivy-4.0.3"
        kafka_jars = [ivy_dir / "jars" / name for name in KAFKA_SPARK_JARS]
        spark_builder = (SparkSession.builder.master("local[2]")
                         .appName("KSL learning attempt MongoDB check")
                         .config("spark.driver.host", "127.0.0.1")
                         .config("spark.driver.bindAddress", "127.0.0.1")
                         .config("spark.ui.enabled", "false")
                         .config("spark.sql.shuffle.partitions", "1")
                         .config("spark.sql.session.timeZone", "UTC")
                         .config("spark.jars.ivy", str(ivy_dir)))
        if all(path.is_file() for path in kafka_jars):
            # The driver and the local executor can read the same cached files.
            spark_builder.config("spark.jars", ",".join(path.as_uri().replace("file:", "local:", 1)
                                                        for path in kafka_jars))
        else:
            spark_builder.config("spark.jars.packages", KAFKA_SPARK_PACKAGE)
        spark = spark_builder.getOrCreate()
        spark.sparkContext.setLogLevel("ERROR")
        try:
            scope = F.col("event_id") == args.receive_id if args.receive_id else F.col("run_id") == run_id
            if verify_team_retry:
                scope = F.col("event_id").isin(args.receive_id, additional_event["event_id"])
            event_schema = ("schema_version INT, run_id STRING, event_id STRING, target_word STRING, "
                            "predicted_word STRING, occurred_at STRING")
            if team_wire:
                event_schema = ("schema_version INT, event_id STRING, event_type STRING, source STRING, "
                                "word STRING, predicted_word STRING, event_time STRING, "
                                "user_id STRING, sent_at STRING, received_at STRING")
            reader = ((spark.read if exact_offsets else spark.readStream).format("kafka")
                      .option("kafka.bootstrap.servers", args.broker))
            if exact_offsets:
                partition_key = str(args.team_partition)
                (reader.option("assign", json.dumps({topic: [args.team_partition]}))
                 .option("startingOffsets", json.dumps({topic: {partition_key: min(args.team_offsets)}}))
                 .option("endingOffsets", json.dumps({topic: {partition_key: max(args.team_offsets) + 1}}))
                 .option("kafka.allow.auto.create.topics", "false"))
            elif live_team:
                start_time = datetime.now(timezone.utc) - timedelta(minutes=args.lookback_minutes)
                (reader.option("subscribe", topic)
                 .option("startingTimestamp", str(int(start_time.timestamp() * 1000)))
                 .option("startingOffsetsByTimestampStrategy", "latest")
                 .option("kafka.allow.auto.create.topics", "false")
                 .option("maxOffsetsPerTrigger", "5000"))
            else:
                reader.option("subscribe", topic).option("startingOffsets", "earliest")
                scope = scope & (F.col("schema_version") == 1)
            kafka_records = reader.load()
            if exact_offsets:
                kafka_records = kafka_records.where(F.col("offset").isin(args.team_offsets))
            events = (kafka_records
                      .select("partition", "offset", F.col("key").cast("string").alias("message_key"),
                              F.from_json(F.col("value").cast("string"), event_schema).alias("event"))
                      .select("partition", "offset", "message_key", "event.*").where(scope))
            if team_batch:
                events = events.where((F.col("event_type") == "recognition_result") & (F.col("source") == "practice"))
            if team_wire:
                events = (events.withColumnRenamed("word", "target_word")
                          .withColumnRenamed("event_time", "occurred_at"))
            live_result = None

            def normalize_row(row):
                attempt = validate_attempt({field: row[field] for field in (
                    "schema_version", "event_id", "target_word", "predicted_word", "occurred_at"
                )})
                if live_team:
                    if (row.event_type, row.source) != ("recognition_result", "practice"):
                        raise ValueError("지정한 이벤트는 학습 모드 recognition_result가 아닙니다.")
                    if not row.user_id or row.message_key != row.user_id:
                        raise ValueError("Kafka 메시지 키가 본문의 user_id와 다릅니다.")
                    for field in ("sent_at", "received_at"):
                        validate_attempt(dict(attempt, occurred_at=row[field]))
                elif team_batch:
                    if row.message_key != row.user_id or row.user_id != team_user_id:
                        raise ValueError("Kafka 메시지 키가 요청의 user_id와 다릅니다.")
                    if row.sent_at != api_ack["sent_at"] or not row.received_at:
                        raise ValueError("Kafka 메시지의 sent_at 또는 received_at이 다릅니다.")
                    if not verify_team_retry and row.received_at != api_ack["received_at"]:
                        raise ValueError("Kafka 메시지의 received_at이 다릅니다.")
                elif row.message_key != attempt["event_id"]:
                    raise ValueError("Kafka 메시지 키가 event_id와 다릅니다.")
                return attempt

            def persist_rows(rows):
                nonlocal live_result
                if not rows:
                    return
                partition_offsets = {}
                for row in rows:
                    attempt = normalize_row(row)
                    if live_team:
                        processed_attempt = dict(attempt)
                        received_partition = row.partition
                    doc = {"_id": attempt.pop("event_id"), "run_id": run_id, **attempt}
                    ledger.update_one({"_id": row.event_id}, {"$setOnInsert": doc}, upsert=True)
                    if ledger.find_one({"_id": row.event_id}) != doc:
                        raise ValueError("같은 이벤트 ID로 다른 내용이 도착했습니다.")
                    partition_offsets[row.partition] = max(row.offset, partition_offsets.get(row.partition, -1))

                samples = [(doc["target_word"], doc["occurred_at"]) for doc in ledger.find(
                    {"run_id": run_id}, {"target_word": 1, "occurred_at": 1}
                )]
                attempts = spark.createDataFrame(samples, "target_word string, occurred_at string").withColumn(
                    "event_time", F.to_timestamp("occurred_at")
                )
                summaries = attempts.groupBy("target_word").count().select(
                    "target_word", "count", F.lit(0).alias("window_minutes"),
                    F.lit(None).cast("long").alias("start_epoch"), F.lit(None).cast("long").alias("end_epoch"),
                )
                for minutes in WINDOW_MINUTES:
                    grouped = attempts.groupBy("target_word", F.window("event_time", f"{minutes} minutes")).count()
                    summaries = summaries.unionByName(grouped.select(
                        "target_word", "count", F.lit(minutes).alias("window_minutes"),
                        F.col("window.start").cast("long").alias("start_epoch"),
                        F.col("window.end").cast("long").alias("end_epoch"),
                    ))
                for row in summaries.collect():
                    if row.window_minutes:
                        start = datetime.fromtimestamp(row.start_epoch, timezone.utc)
                        end = datetime.fromtimestamp(row.end_epoch, timezone.utc)
                        key = f"{run_id}:{row.target_word}:{row.window_minutes}:{row.start_epoch}"
                        windows.replace_one({"_id": key}, {
                            "_id": key, "run_id": run_id, "target_word": row.target_word,
                            "window_minutes": row.window_minutes, "window_start": start,
                            "window_end": end, "count": row["count"],
                        }, upsert=True)
                    else:
                        key = f"{run_id}:{row.target_word}"
                        totals.replace_one({"_id": key}, {
                            "_id": key, "run_id": run_id, "target_word": row.target_word, "count": row["count"],
                        }, upsert=True)
                # Record the consumed Kafka offset only after both writes finish.
                for partition, offset in partition_offsets.items():
                    offsets.update_one({"_id": f"{run_id}:{partition}"},
                                       {"$max": {"offset": offset}}, upsert=True)
                if live_team:
                    live_result = processed_attempt, received_partition, partition_offsets[received_partition]

            def persist_batch(batch, batch_id):
                persist_rows(batch.collect())

            with tempfile.TemporaryDirectory(prefix="ksl-learning-db-", ignore_cleanup_errors=True) as temp:
                checkpoint = Path(temp).as_uri()

                def start_query():
                    return (events.writeStream.foreachBatch(persist_batch)
                            .option("checkpointLocation", checkpoint).start())

                with (nullcontext() if args.receive_id else producer_client(args.broker)) as producer:
                    event = dict(fixture(f"{run_id}-1"), run_id=run_id)

                    def verify_total(expected, target_word):
                        total = totals.find_one({"_id": f"{run_id}:{target_word}"})
                        actual = (ledger.count_documents({"run_id": run_id}), total and total["count"])
                        if actual != (expected, expected):
                            raise AssertionError(f"예상 원장·집계 {expected}건, 실제 {actual}")

                    def verify_count(expected):
                        verify_total(expected, "커피")

                        # Compare the complete set, including bounds and counts.
                        def bounds(minutes, start, end):
                            return ("커피", minutes, start, end)

                        expected_windows = {
                            bounds(1, "01:00", "01:01"): 1,
                            bounds(5, "01:00", "01:05"): min(expected, 2),
                        }
                        if expected >= 2:
                            expected_windows[bounds(1, "01:01", "01:02")] = 1
                        if expected == 3:
                            expected_windows[bounds(1, "01:05", "01:06")] = 1
                            expected_windows[bounds(5, "01:05", "01:10")] = 1
                        actual_windows = {
                            (doc["target_word"], doc["window_minutes"], doc["window_start"].strftime("%H:%M"),
                             doc["window_end"].strftime("%H:%M")): doc["count"]
                            for doc in windows.find({"run_id": run_id})
                        }
                        if actual_windows != expected_windows:
                            raise AssertionError(f"시간 구간 집계 불일치: 예상 {expected_windows}, 실제 {actual_windows}")

                    def check(query, payload, count, label):
                        normalized = validate_attempt(payload)
                        sent = producer.send(TOPIC, key=normalized["event_id"].encode(), value=normalized).get(timeout=10)
                        deadline = time.monotonic() + 75
                        while time.monotonic() < deadline:
                            if query.exception() is not None:
                                raise RuntimeError(str(query.exception()))
                            seen = offsets.find_one({"_id": f"{run_id}:{sent.partition}"})
                            if seen and seen["offset"] >= sent.offset:
                                verify_count(count)
                                print(f"[PASS] {label} / 원장·누적 {count}건 / 1분·5분 구간 일치", flush=True)
                                return
                            time.sleep(0.5)
                        raise TimeoutError(f"{label}: Kafka 오프셋 {sent.offset}의 저장 완료를 확인하지 못했습니다.")

                    def wait_for_external_offset(query, ack):
                        expected_offset = ({"_id": f"{run_id}:{ack['partition']}", "offset": ack["offset"]}
                                           if ack else {"_id": {"$regex": f"^{run_id}:"}})
                        deadline = time.monotonic() + 120
                        while time.monotonic() < deadline:
                            if query.exception() is not None:
                                raise RuntimeError(str(query.exception()))
                            if offsets.find_one(expected_offset):
                                return
                            time.sleep(0.5)
                        raise TimeoutError("지정 이벤트의 오프셋이 MongoDB에 기록되지 않았습니다.")

                    def verify_external_attempts(*expected_attempts):
                        verify_total(len(expected_attempts), expected_attempts[0]["target_word"])
                        expected_windows = {}
                        for attempt in expected_attempts:
                            event_time = datetime.fromisoformat(attempt["occurred_at"])
                            for minutes in WINDOW_MINUTES:
                                start = event_time.replace(minute=event_time.minute // minutes * minutes,
                                                           second=0, microsecond=0)
                                key = (attempt["target_word"], minutes, start, start + timedelta(minutes=minutes))
                                expected_windows[key] = expected_windows.get(key, 0) + 1
                            expected = dict(attempt)
                            event_id = expected.pop("event_id")
                            if ledger.find_one({"_id": event_id}) != dict(expected, _id=event_id, run_id=run_id):
                                raise AssertionError("수신한 이벤트가 규약 예시와 다릅니다.")
                        actual_windows = {
                            (doc["target_word"], doc["window_minutes"], doc["window_start"], doc["window_end"]): doc["count"]
                            for doc in windows.find({"run_id": run_id})
                        }
                        if actual_windows != expected_windows:
                            raise AssertionError("수신한 이벤트의 1분·5분 집계가 요청 시각과 다릅니다.")

                    if exact_offsets:
                        selected = sorted(events.collect(), key=lambda record: record.offset)
                        expected_offsets = sorted(args.team_offsets)
                        if [record.offset for record in selected] != expected_offsets:
                            raise ValueError("지정한 오프셋에서 동일한 event_id를 모두 확인하지 못했습니다.")
                        attempts = [normalize_row(record) for record in selected]
                        if any(attempt != attempts[0] for attempt in attempts[1:]) or len({row.user_id for row in selected}) != 1:
                            raise ValueError("같은 event_id의 Kafka 레코드 내용 또는 user_id가 서로 다릅니다.")
                        persist_rows(selected)
                        verify_external_attempts(attempts[0])
                        if not offsets.find_one({"_id": f"{run_id}:{args.team_partition}", "offset": {"$gte": expected_offsets[-1]}}):
                            raise AssertionError("MongoDB에 저장된 처리 오프셋을 확인하지 못했습니다.")
                        print(f"[PASS] 팀 Kafka 수신: {topic} / 파티션 {args.team_partition} / 오프셋 {expected_offsets}", flush=True)
                        print(f"[PASS] MongoDB 원장·누적·1분·5분 집계 각각 1건 / event_id: {args.receive_id}", flush=True)
                        return

                    if live_team:
                        print(f"팀 이벤트 수신 대기: {topic} / event_id: {args.receive_id} / 최근 {args.lookback_minutes}분부터",
                              flush=True)
                        query = start_query()
                        try:
                            deadline = time.monotonic() + 120
                            while time.monotonic() < deadline:
                                if query.exception() is not None:
                                    raise RuntimeError(str(query.exception()))
                                if live_result is not None:
                                    attempt, partition, offset = live_result
                                    verify_external_attempts(attempt)
                                    saved_offset = {"_id": f"{run_id}:{partition}", "offset": {"$gte": offset}}
                                    if not offsets.find_one(saved_offset):
                                        raise AssertionError("MongoDB에 저장된 처리 오프셋을 확인하지 못했습니다.")
                                    print(f"[PASS] 팀 Kafka 수신: {topic} / 파티션 {partition} / 오프셋 {offset}", flush=True)
                                    print(f"[PASS] MongoDB 원장·누적·1분·5분 집계 각각 1건 / event_id: {args.receive_id}",
                                          flush=True)
                                    return
                                time.sleep(0.5)
                            raise TimeoutError("지정한 이벤트를 찾지 못했습니다. 팀에서 알려준 토픽, event_id와 발행 시각을 확인하세요.")
                        finally:
                            query.stop()

                    if expected_external is not None:
                        if ledger.find_one({"_id": args.receive_id}, {"_id": 1}):
                            raise ValueError("이전에 사용한 검사 ID입니다. 새 ID를 사용하세요.")
                        query = start_query()
                        try:
                            status = "수신 검사" if team_batch else "외부 발행 대기"
                            print(f"{status}: {topic} / event_id: {args.receive_id}", flush=True)
                            if args.external_probe:
                                subprocess.run([
                                    sys.executable, "-B", str(Path(__file__).resolve()),
                                    "--publish-id", args.receive_id, "--broker", args.broker,
                                ], check=True, timeout=35)
                            wait_for_external_offset(query, api_ack)
                            verify_external_attempts(expected_external)
                            if verify_team_retry:
                                print("[PASS] 첫 이벤트 / 원장·누적·1분·5분 각각 1건", flush=True)
                                if args.verify_team_restart:
                                    query.processAllAvailable()
                                    checkpoint_query_id, first_query_run_id = query.id, query.runId
                                    query.stop()
                                replay_ack = submit_api_request(request_body)
                                if replay_ack["event_id"] != args.receive_id or replay_ack["offset"] <= api_ack["offset"]:
                                    raise AssertionError("같은 이벤트가 새 Kafka 오프셋으로 재전송되지 않았습니다.")
                                if args.verify_team_restart:
                                    if not offsets.find_one({"_id": f"{run_id}:{api_ack['partition']}", "offset": api_ack["offset"]}):
                                        raise AssertionError("Spark 중지 중에 처리 오프셋이 변경됐습니다.")
                                    print(f"[PASS] Spark 중지 중 재전송 / Kafka 오프셋 {replay_ack['offset']} / 저장 오프셋 유지", flush=True)
                                    query = start_query()
                                    if query.id != checkpoint_query_id or query.runId == first_query_run_id:
                                        raise AssertionError("같은 Spark 체크포인트에서 새 실행을 복구하지 못했습니다.")
                                    print("[PASS] 같은 Spark 체크포인트에서 스트리밍 쿼리 재시작", flush=True)
                                wait_for_external_offset(query, replay_ack)
                                verify_external_attempts(expected_external)
                                print(f"[PASS] 같은 event_id 재전송 / 오프셋 {replay_ack['offset']} / 각각 1건 유지", flush=True)
                                next_body = json.dumps(dict(batch, events=[additional_event]), ensure_ascii=False).encode("utf-8")
                                next_ack = submit_api_request(next_body)
                                if next_ack["event_id"] != additional_event["event_id"] or next_ack["offset"] <= replay_ack["offset"]:
                                    raise AssertionError("새 이벤트가 다음 Kafka 오프셋에 발행되지 않았습니다.")
                                wait_for_external_offset(query, next_ack)
                                verify_external_attempts(expected_external, normalize_team_attempt(additional_event))
                                print(f"[PASS] 같은 user_id의 새 event_id / 오프셋 {next_ack['offset']} / 각각 2건", flush=True)
                            query.processAllAvailable()
                            label = "모의 API → Kafka → Spark" if api_ack else "외부 발행"
                            print(f"[PASS] {label} → MongoDB 원장·누적·1분·5분 집계", flush=True)
                            return
                        finally:
                            query.stop()

                    query = start_query()
                    try:
                        check(query, event, 1, "첫 기록 저장")
                        check(query, event, 1, "같은 ID 재전송")
                        check(query, dict(event, event_id=f"{run_id}-2", occurred_at="2026-11-20T01:01:00Z"),
                              2, "1분 경계에 새 ID 추가")
                        query.processAllAvailable()
                        query_id = query.id
                    finally:
                        query.stop()

                    verify_count(2)
                    query = start_query()
                    try:
                        if query.id != query_id:
                            raise AssertionError("같은 체크포인트에서 스트리밍 쿼리가 복구되지 않았습니다.")
                        print("[PASS] 같은 체크포인트 쿼리 재시작 / 기존 2건과 구간 유지", flush=True)
                        check(query, event, 2, "재시작 후 같은 ID 재전송")
                        check(query, dict(event, event_id=f"{run_id}-3", occurred_at="2026-11-20T01:05:00Z"),
                              3, "재시작 후 5분 경계에 새 ID 추가")
                        query.processAllAvailable()
                    finally:
                        query.stop()
        finally:
            spark.stop()
        verify_count(3)
        print(f"검사 완료: 6개 PASS / 조회용 run_id: {run_id}", flush=True)


if __name__ == "__main__":
    main()
