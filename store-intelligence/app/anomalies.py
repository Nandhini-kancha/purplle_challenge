from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from datetime import datetime, timezone, timedelta
from app.database import get_db, Event
from app.pos_loader import get_pos_transactions
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/stores/{store_id}/anomalies")
async def get_active_anomalies(store_id: str, db: AsyncSession = Depends(get_db)):
    anomalies = []
    now = datetime.now(timezone.utc)
    
    # 1. Queue Spike
    # Let's say queue depth > 5 is a warning, > 10 is critical
    latest_q_query = select(Event).where(
        Event.store_id == store_id,
        Event.event_type == 'BILLING_QUEUE_JOIN'
    ).order_by(Event.timestamp.desc()).limit(1)
    
    latest_q_result = await db.execute(latest_q_query)
    latest_q_event = latest_q_result.scalar_one_or_none()
    
    if latest_q_event and latest_q_event.metadata_ and 'queue_depth' in latest_q_event.metadata_:
        qd = latest_q_event.metadata_['queue_depth']
        if qd and qd > 10:
            anomalies.append({
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL",
                "description": f"Queue depth is critically high ({qd})",
                "suggested_action": "Deploy additional billing staff immediately."
            })
        elif qd and qd > 5:
            anomalies.append({
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "description": f"Queue depth is elevated ({qd})",
                "suggested_action": "Monitor queue and prepare to open another counter."
            })

    # 2. Dead zone (no visits in 30 min)
    thirty_mins_ago = now - timedelta(minutes=30)
    
    # Get all distinct zones
    zones_query = select(distinct(Event.zone_id)).where(
        Event.store_id == store_id,
        Event.zone_id.isnot(None)
    )
    zones_result = await db.execute(zones_query)
    all_zones = [row[0] for row in zones_result if row[0]]
    
    for zone in all_zones:
        # Check if any event in this zone in last 30 mins
        recent_zone_query = select(Event).where(
            Event.store_id == store_id,
            Event.zone_id == zone,
            Event.timestamp >= thirty_mins_ago
        ).limit(1)
        recent_zone_result = await db.execute(recent_zone_query)
        if not recent_zone_result.scalar_one_or_none():
            anomalies.append({
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "description": f"No visits in zone '{zone}' for 30 minutes",
                "suggested_action": f"Check camera feed for {zone} to ensure no obstructions or lighting issues."
            })

    # 3. Conversion drop vs 7-day baseline (Statistical)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    transactions = get_pos_transactions(store_id)
    
    async def get_daily_conversion(target_date):
        next_day = target_date + timedelta(days=1)
        day_tx = [t for t in transactions if target_date <= t['timestamp'] < next_day]
        
        uv_query = select(func.count(distinct(Event.visitor_id))).where(
            Event.store_id == store_id,
            Event.timestamp >= target_date,
            Event.timestamp < next_day,
            Event.is_staff == False
        )
        uv = (await db.execute(uv_query)).scalar() or 0
        
        if uv == 0: return None
            
        billing_q = select(Event.visitor_id, Event.timestamp).where(
            Event.store_id == store_id,
            Event.timestamp >= target_date,
            Event.timestamp < next_day,
            Event.zone_id == 'BILLING',
            Event.is_staff == False
        )
        b_events = (await db.execute(billing_q)).all()
        converted = set()
        for tx in day_tx:
            tx_time = tx['timestamp']
            w_start = tx_time - timedelta(minutes=5)
            for v_id, b_time in b_events:
                if w_start <= b_time <= tx_time:
                    converted.add(v_id)
                    
        return len(converted) / uv
        
    today_conv_rate = await get_daily_conversion(start_of_today) or 0
    today_tx = [t for t in transactions if t['timestamp'] >= start_of_today]
    
    past_rates = []
    for i in range(1, 8):
        day_date = start_of_today - timedelta(days=i)
        rate = await get_daily_conversion(day_date)
        if rate is not None: past_rates.append(rate)
            
    if len(past_rates) >= 3:
        import statistics
        mean_rate = statistics.mean(past_rates)
        std_dev = statistics.stdev(past_rates) if len(past_rates) > 1 else 0
        
        # Fire if today's rate is significantly lower than average (2 standard deviations)
        if today_conv_rate < (mean_rate - 2 * std_dev) and today_conv_rate < 0.5 * mean_rate:
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "description": f"Conversion dropped to {today_conv_rate:.1%} (7-day baseline: {mean_rate:.1%} ± {std_dev:.1%})",
                "suggested_action": "Statistically significant drop. Check billing counter efficiency."
            })
    elif today_conv_rate == 0 and len(today_tx) == 0:
        today_uv_query = select(func.count(distinct(Event.visitor_id))).where(
            Event.store_id == store_id,
            Event.timestamp >= start_of_today,
            Event.is_staff == False
        )
        today_uv = (await db.execute(today_uv_query)).scalar() or 0
        if today_uv > 20:
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "description": "0% conversion rate despite high footfall today.",
                "suggested_action": "Check POS systems for downtime."
            })
    
    return {"anomalies": anomalies}
