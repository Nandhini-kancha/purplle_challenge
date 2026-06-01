import csv
from datetime import datetime
from typing import List, Dict
import os
from datetime import timezone, timedelta

# Fallback to the real dataset if it exists in the workspace
DEFAULT_POS = r"C:\Users\Nandhini\OneDrive\Desktop\purple\dataset\Brigade_Bangalore_10_April_26 (1)bc6219c.csv"
POS_FILE = os.getenv("POS_FILE", DEFAULT_POS)

def get_pos_transactions(store_id: str) -> List[Dict]:
    if not os.path.exists(POS_FILE):
        return []
    
    transactions = []
    with open(POS_FILE, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Expected schema from real dataset: order_id, order_date, order_time, store_id, total_amount
            if row.get('store_id') == store_id:
                try:
                    # Clean the timestamp. Example: 10-04-2026, 16:55:36
                    # Assuming IST time, converting to UTC for metrics comparison
                    date_str = row['order_date'].strip()
                    time_str = row['order_time'].strip()
                    ts_str = f"{date_str} {time_str}"
                    # Format: DD-MM-YYYY HH:MM:SS
                    ts_local = datetime.strptime(ts_str, "%d-%m-%Y %H:%M:%S")
                    # Convert IST (+05:30) to UTC
                    ts_utc = ts_local.replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
                    
                    # Shift the date to "today" so that metrics.py can cross-reference it with real-time CCTV events
                    now_utc = datetime.now(timezone.utc)
                    ts_shifted = ts_utc.replace(year=now_utc.year, month=now_utc.month, day=now_utc.day)
                    
                    transactions.append({
                        "transaction_id": row['order_id'],
                        "timestamp": ts_shifted,
                        "basket_value_inr": float(row['total_amount'])
                    })
                except Exception as e:
                    continue
    return transactions
