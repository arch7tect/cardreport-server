"""Bounded aggregate metrics, without report identifiers or data values."""

from prometheus_client import CollectorRegistry, Gauge, generate_latest

from .db import Database


def queue_metrics(db: Database) -> bytes:
    registry = CollectorRegistry()
    count = Gauge(
        "cardreport_jobs",
        "Global job counts; aggregate replica scrapes with max, not sum",
        ["state"],
        registry=registry,
    )
    age = Gauge(
        "cardreport_queue_oldest_seconds",
        "Age of the oldest queued report",
        registry=registry,
    )
    with db.pool.connection() as conn:
        rows = conn.execute(
            "SELECT state,count(*) AS n FROM reports GROUP BY state"
        ).fetchall()
        oldest = conn.execute(
            "SELECT COALESCE(EXTRACT(EPOCH FROM clock_timestamp()-min(created_at)),0) AS age FROM reports WHERE state='queued'"
        ).fetchone()
    values = {row["state"]: row["n"] for row in rows}
    for state in ("queued", "running", "succeeded", "failed", "expired"):
        count.labels(state).set(values.get(state, 0))
    assert oldest is not None
    age.set(float(oldest["age"]))
    return generate_latest(registry)
