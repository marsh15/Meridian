import asyncio
import logging
from typing import Any

from aiokafka.errors import KafkaError

from app.telemetry import setup_telemetry
from consumers import analytics, candles, volume
from consumers.common import pump

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("meridian.consumers")


async def _supervise(group: str, run: Any) -> None:
    """Restart one group's pump with backoff when it dies. gather() without
    this would tear down all three groups on any single pump-level failure
    (commit errors, coordinator hiccups) — the groups are supposed to be
    independent."""
    backoff = 1.0
    while True:
        try:
            await run()
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] pump crashed; restarting in %.0fs", group, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def main() -> None:
    """All three consumers in one process, independent groups — each pump is
    supervised separately, so if one wedges the others keep flowing."""
    setup_telemetry(service_name="meridian-consumers")
    await asyncio.gather(
        _supervise(candles.GROUP, pump(candles.GROUP, candles.TOPICS, candles.handle)),
        _supervise(volume.GROUP, pump(volume.GROUP, volume.TOPICS, volume.handle)),
        _supervise(analytics.GROUP, pump(analytics.GROUP, analytics.TOPICS, analytics.handle)),
    )


try:
    asyncio.run(main())
except KafkaError as err:  # pragma: no cover - startup guard for operators
    raise SystemExit(
        f"consumers: Kafka unreachable ({err}) — is `make db` up?"
    ) from err
