import asyncio
import logging

from aiokafka.errors import KafkaError

from consumers import analytics, candles, volume
from consumers.common import pump
from app.telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


async def main() -> None:
    """All three consumers in one process, independent groups — if one
    wedges, the others keep flowing."""
    setup_telemetry(service_name="meridian-consumers")
    await asyncio.gather(
        pump(candles.GROUP, candles.TOPICS, candles.handle),
        pump(volume.GROUP, volume.TOPICS, volume.handle),
        pump(analytics.GROUP, analytics.TOPICS, analytics.handle),
    )


try:
    asyncio.run(main())
except KafkaError as err:  # pragma: no cover - startup guard for operators
    raise SystemExit(f"consumers: Kafka unreachable ({err}) — is `make db` up?")
