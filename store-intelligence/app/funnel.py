from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from datetime import datetime, timezone, timedelta
from app.database import get_db, Event
from app.pos_loader import get_pos_transactions
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/stores/{store_id}/funnel")
async def get_conversion_funnel(store_id: str, db: AsyncSession = Depends(get_db)):
    # Calculate for "today"
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Entry count (unique visitors entering)
    entries_query = select(distinct(Event.visitor_id)).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type == 'ENTRY',
        Event.is_staff == False
    )
    entries_result = await db.execute(entries_query)
    entered_visitors = {row[0] for row in entries_result}

    # 2. Zone Visit count (unique visitors who entered ANY named zone)
    zone_query = select(distinct(Event.visitor_id)).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type.in_(['ZONE_ENTER', 'ZONE_DWELL']),
        Event.is_staff == False
    )
    zone_result = await db.execute(zone_query)
    # Must have also entered to be in funnel step 2
    zone_visitors = {row[0] for row in zone_result}.intersection(entered_visitors)

    # 3. Billing Queue count (unique visitors joining billing queue)
    billing_query = select(distinct(Event.visitor_id)).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type == 'BILLING_QUEUE_JOIN',
        Event.is_staff == False
    )
    billing_result = await db.execute(billing_query)
    billing_visitors = {row[0] for row in billing_result}.intersection(zone_visitors)

    # 4. Purchase count (correlate POS with billing_visitors)
    transactions = get_pos_transactions(store_id)
    today_tx = [t for t in transactions if t['timestamp'] >= start_of_day]
    
    # Get all billing events (we need timestamps to correlate)
    b_events_query = select(Event.visitor_id, Event.timestamp).where(
        Event.store_id == store_id,
        Event.timestamp >= start_of_day,
        Event.event_type == 'BILLING_QUEUE_JOIN',
        Event.is_staff == False
    )
    b_events_result = await db.execute(b_events_query)
    b_events = b_events_result.all()
    
    purchased_visitors = set()
    for tx in today_tx:
        tx_time = tx['timestamp']
        window_start = tx_time - timedelta(minutes=5)
        for v_id, b_time in b_events:
            if v_id in billing_visitors and window_start <= b_time <= tx_time:
                purchased_visitors.add(v_id)

    step1 = len(entered_visitors)
    step2 = len(zone_visitors)
    step3 = len(billing_visitors)
    step4 = len(purchased_visitors)

    def calc_dropoff(current, previous):
        if previous == 0:
            return 0.0
        return round((1 - (current / previous)) * 100, 2)

    return {
        "funnel": [
            {"stage": "Entry", "count": step1, "drop_off_pct": 0.0},
            {"stage": "Zone Visit", "count": step2, "drop_off_pct": calc_dropoff(step2, step1)},
            {"stage": "Billing Queue", "count": step3, "drop_off_pct": calc_dropoff(step3, step2)},
            {"stage": "Purchase", "count": step4, "drop_off_pct": calc_dropoff(step4, step3)},
        ]
    }
