from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from datetime import datetime, timezone
from app.database import get_db, Event
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def normalize(value: float, min_value: float, max_value: float) -> int:
    """
    Normalize to 0-100 scale.
    If all values are identical, return 100 for non-zero values else 0.
    """
    if max_value == min_value:
        return 100 if value > 0 else 0

    return round(
        ((value - min_value) / (max_value - min_value)) * 100
    )


@router.get("/stores/{store_id}/heatmap")
async def get_store_heatmap(
    store_id: str,
    db: AsyncSession = Depends(get_db)
):
    # Today UTC
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    # ------------------------------------------------------------
    # Session count (unique visitors) for confidence flag
    # ------------------------------------------------------------
    session_query = select(
        func.count(distinct(Event.visitor_id))
    ).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False
    )

    session_result = await db.execute(session_query)
    session_count = session_result.scalar() or 0

    data_confidence = session_count >= 20

    # ------------------------------------------------------------
    # Visit frequency per zone
    # Count ZONE_ENTER events
    # ------------------------------------------------------------
    frequency_query = select(
        Event.zone_id,
        func.count(distinct(Event.visitor_id))
    ).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False,
        Event.event_type == "ZONE_ENTER",
        Event.zone_id.isnot(None)
    ).group_by(Event.zone_id)

    frequency_result = await db.execute(frequency_query)

    zone_frequency = {
        zone_id: count
        for zone_id, count in frequency_result.all()
    }

    # ------------------------------------------------------------
    # Average dwell per zone
    # ------------------------------------------------------------
    dwell_query = select(
        Event.zone_id,
        func.avg(Event.dwell_ms)
    ).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.is_staff == False,
        Event.event_type == "ZONE_DWELL",
        Event.zone_id.isnot(None)
    ).group_by(Event.zone_id)

    dwell_result = await db.execute(dwell_query)

    zone_dwell = {
        zone_id: float(avg_dwell or 0)
        for zone_id, avg_dwell in dwell_result.all()
    }

    # ------------------------------------------------------------
    # Merge zones from both datasets
    # ------------------------------------------------------------
    all_zones = set(zone_frequency.keys()) | set(zone_dwell.keys())

    if not all_zones:
        return {"zones": []}

    # ------------------------------------------------------------
    # Normalization ranges
    # ------------------------------------------------------------
    frequency_values = [
        zone_frequency.get(zone, 0)
        for zone in all_zones
    ]

    dwell_values = [
        zone_dwell.get(zone, 0)
        for zone in all_zones
    ]

    min_frequency = min(frequency_values)
    max_frequency = max(frequency_values)

    min_dwell = min(dwell_values)
    max_dwell = max(dwell_values)

    # ------------------------------------------------------------
    # Build response
    # ------------------------------------------------------------
    zones = []

    for zone in sorted(all_zones):
        raw_frequency = zone_frequency.get(zone, 0)
        raw_dwell = zone_dwell.get(zone, 0)

        zones.append({
            "zone_id": zone,
            "visit_frequency": normalize(
                raw_frequency,
                min_frequency,
                max_frequency
            ),
            "avg_dwell_normalised": normalize(
                raw_dwell,
                min_dwell,
                max_dwell
            ),
            "data_confidence": data_confidence
        })

    return {
        "zones": zones
    }
