"""Run a local Kafka and Spark integration check with synthetic learning attempts."""

from contextlib import closing
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic
from kafka.errors import TopicAlreadyExistsError


BROKER = "127.0.0.1:19092"
TOPIC = "ksl.demo.learning-attempt.synthetic.v1"


def main():
    run_id = uuid4().hex
    admin = KafkaAdminClient(bootstrap_servers=BROKER, request_timeout_ms=10000)
    try:
        admin.create_topics([NewTopic(TOPIC, 1, 1, topic_configs={"retention.ms": "86400000"})])
    except TopicAlreadyExistsError:
        pass
    finally:
        admin.close()

    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
    os.environ["SPARK_LOCAL_HOSTNAME"] = "localhost"
    from pyspark.sql import SparkSession, functions as F

    spark = (SparkSession.builder.master("local[2]")
             .appName("KSL synthetic learning attempts")
             .config("spark.ui.enabled", "false")
             .config("spark.sql.shuffle.partitions", "1")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.jars.ivy", str(Path(tempfile.gettempdir()) / "ksl-spark-ivy-4.0.3"))
             .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.3")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        with tempfile.TemporaryDirectory(prefix="ksl-learning-", ignore_cleanup_errors=True) as temp:
            events = (spark.readStream.format("kafka")
                      .option("kafka.bootstrap.servers", BROKER)
                      .option("subscribe", TOPIC)
                      .option("startingOffsets", "earliest")
                      .load()
                      .select(F.from_json(F.col("value").cast("string"),
                                          "schema_version INT, run_id STRING, event_id STRING, "
                                          "target_word STRING, predicted_word STRING, occurred_at TIMESTAMP").alias("event"))
                      .select("event.*")
                      .where((F.col("run_id") == run_id) & (F.col("schema_version") == 1)
                             & F.col("event_id").isNotNull() & F.col("target_word").isNotNull()
                             & F.col("occurred_at").isNotNull()))
            # One row per event ID and target word. Count deliveries separately
            # so a replay must be consumed before the duplicate check can pass.
            query = (events.groupBy("event_id", "target_word").count()
                     .writeStream.format("memory").queryName("learning_attempt_test")
                     .outputMode("complete").option("checkpointLocation", Path(temp).as_uri()).start())
            try:
                with closing(KafkaProducer(
                    bootstrap_servers=BROKER,
                    acks="all",
                    value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
                )) as producer:
                    event = {"schema_version": 1, "run_id": run_id, "event_id": f"{run_id}-1",
                             "target_word": "커피", "predicted_word": "커피", "occurred_at": "2026-11-20T01:00:00Z"}

                    def check(payload, deliveries, unique, label):
                        producer.send(TOPIC, key=payload["event_id"].encode(), value=payload).get(timeout=10)
                        deadline = time.monotonic() + 60
                        result = {}
                        while time.monotonic() < deadline:
                            if query.exception() is not None:
                                raise RuntimeError(str(query.exception()))
                            rows = (spark.table("learning_attempt_test").groupBy("target_word")
                                    .agg(F.count("*").alias("unique"), F.sum("count").alias("deliveries")).collect())
                            result = {row.target_word: (row.deliveries, row.unique) for row in rows}
                            if result == {"커피": (deliveries, unique)}:
                                print(f"[PASS] {label} / 수신 {deliveries}회 / 고유 시도 {unique}건", flush=True)
                                return
                            time.sleep(0.5)
                        raise TimeoutError(f"{label}: 예상 ({deliveries}, {unique}), 실제 {result}")

                    check(event, 1, 1, "첫 이벤트")
                    check(event, 2, 1, "같은 ID 재전송")
                    check(dict(event, event_id=f"{run_id}-2"), 3, 2, "새 ID 추가")
            finally:
                query.stop()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
