"""Full pipeline against a live broker: trade → outbox → relay → Kafka →
consumers → read models. Skips when Kafka isn't running (e.g. CI), which
is safe: every DB-side behavior is covered by test_relay/test_consumers;
this test only proves the Kafka plumbing (producer, consumer groups,
offsets) wires those pieces together.

Uses throwaway topics recreated per run so residue from dev-world events
never reaches the test database's foreign keys."""

import socket
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from aiokafka import AIOKafkaProducer
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory, engine
from consumers import analytics, candles, volume
from consumers.common import pump_once
from relay import main as relay_main

REPO_ROOT = Path(__file__).resolve().parents[3]
FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

TEST_TRADES = "exchange.test-trade-events"
TEST_MARKETS = "exchange.test-market-events"


def _kafka_up() -> bool:
    try:
        with socket.create_connection(("localhost", 9092), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _kafka_up(), reason="Kafka not running — `docker compose up -d kafka`")


def _kadmin(*args: str) -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"),
         "exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", *args],
        check=True, capture_output=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _fresh_topics():
    for topic in (TEST_TRADES, TEST_MARKETS):
        subprocess.run(  # may not exist yet — fine
            ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"),
             "exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh",
             "--delete", "--topic", topic, "--bootstrap-server", "localhost:9092"],
            capture_output=True,
        )
        _kadmin("--create", "--topic", topic, "--partitions", "1",
                "--bootstrap-server", "localhost:9092")
    yield


async def test_outbox_through_kafka_into_read_models(client, alice, monkeypatch):
    r = await client.post("/api/markets", json={
        "question": "Will the live Kafka pipeline test pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    assert r.status_code == 200, r.text
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 1_500,
    })
    assert r.status_code == 200, r.text

    # relay → throwaway topics (no dev-world traffic on them)
    monkeypatch.setattr(relay_main, "TOPIC_TRADES", TEST_TRADES)
    monkeypatch.setattr(relay_main, "TOPIC_MARKETS", TEST_MARKETS)
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        async with SessionFactory() as session:
            assert await relay_main.relay_once(producer, session) == 2
    finally:
        await producer.stop()

    # fresh groups read the topics from the beginning
    suffix = uuid.uuid4().hex[:8]
    processed = 0
    for module in (candles, volume, analytics):
        processed += await pump_once(
            f"{module.GROUP}-it-{suffix}", [TEST_TRADES, TEST_MARKETS], module.handle
        )
    assert processed >= 3 * 2  # each group saw both events

    async with engine.connect() as conn:
        market_id = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": slug}
        )).scalar_one()
        candle = (await conn.execute(
            text("SELECT volume_cents, trades FROM candles_1m WHERE market_id = :m"),
            {"m": market_id},
        )).first()
        stats = (await conn.execute(
            text("SELECT status, trade_count, volume_cents FROM market_stats WHERE market_id = :m"),
            {"m": market_id},
        )).first()
        facts = (await conn.execute(
            text("SELECT COUNT(*) FROM trade_facts WHERE market_id = :m"), {"m": market_id}
        )).scalar_one()

    assert candle is not None and candle.trades == 1 and candle.volume_cents == 1_500
    assert stats is not None and stats.trade_count == 1 and stats.volume_cents == 1_500
    assert stats.status == "open"
    assert facts == 1
