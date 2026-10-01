"""The market lifecycle workflow: close on a timer, settle on a signal.

Both steps run as activities backed by app.market_lifecycle, so the
durable path and the API's inline path produce identical state. The
workflow is deterministic — all I/O lives in the activities.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from worker import activities


def workflow_id(market_id: int) -> str:
    return f"market-lifecycle:{market_id}"


@dataclass
class MarketLifecycleInput:
    market_id: int
    slug: str
    closes_at_ts: float


@workflow.defn
class MarketLifecycleWorkflow:
    def __init__(self) -> None:
        self._resolution: str | None = None

    @workflow.run
    async def run(self, ml: MarketLifecycleInput) -> str:
        # 1. sleep until closes_at — or skip straight to settlement if the
        #    creator resolves early. +1s of slack so a market whose close
        #    already passed (workflow started late) transitions immediately.
        until_close = max(ml.closes_at_ts - workflow.now().timestamp(), 0.0) + 1.0
        try:
            await workflow.wait_condition(
                lambda: self._resolution is not None, timeout=until_close
            )
        except TimeoutError:
            await workflow.execute_activity(
                activities.close_market,
                args=[ml.market_id],
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            # 2. closed, awaiting resolution — a durable, indefinite wait
            #    that survives worker restarts and Temporal downtime
            await workflow.wait_condition(lambda: self._resolution is not None)

        outcome = self._resolution
        await workflow.execute_activity(
            activities.settle_market,
            args=[ml.market_id, outcome],
            schedule_to_close_timeout=timedelta(minutes=5),
            # settle_market returns success on same-outcome replay, so
            # retries are safe; only a genuine outcome conflict (or a bug)
            # raises LifecycleError, and burning 20 attempts on that helps
            # nobody — fail the workflow fast instead
            retry_policy=RetryPolicy(
                maximum_attempts=20,
                non_retryable_error_types=["LifecycleError"],
            ),
        )
        return outcome or "yes"

    @workflow.signal
    async def resolve(self, outcome: str) -> None:
        if outcome in ("yes", "no"):
            self._resolution = outcome
