import csv
from datetime import datetime
from typing import List, Dict
import os

POS_FILE = os.getenv("POS_FILE", "pos_transactions.csv")

def get_pos_transactions(store_id: str) -> List[Dict]:
    if not os.path.exists(POS_FILE):
        return []
    
    transactions = []
    with open(POS_FILE, mode='r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Expected schema: store_id, transaction_id, timestamp, basket_value_inr
            if row['store_id'] == store_id:
                try:
                    # Clean the timestamp. Example: 2026-03-03T14:38:12Z
                    ts_str = row['timestamp'].strip()
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    transactions.append({
                        "transaction_id": row['transaction_id'],
                        "timestamp": ts,
                        "basket_value_inr": float(row['basket_value_inr'])
                    })
                except Exception:
                    continue
    return transactions
