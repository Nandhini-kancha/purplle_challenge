import json
import os

INPUT_FILE = "events.jsonl"
OUTPUT_FILE = "hackerearth_events.jsonl"

def translate_event(our_event):
    evt_type = our_event.get("event_type", "").upper()
    ts = our_event.get("timestamp")
    store = our_event.get("store_id")
    cam = our_event.get("camera_id")
    vid = our_event.get("visitor_id")
    is_staff = our_event.get("is_staff", False)
    zone = our_event.get("zone_id")
    
    # Base translation
    out = {}
    
    if evt_type in ["ENTRY", "EXIT", "REENTRY"]:
        out["event_type"] = "entry" if evt_type in ["ENTRY", "REENTRY"] else "exit"
        out["id_token"] = vid
        out["store_code"] = store
        out["camera_id"] = cam
        out["event_timestamp"] = ts
        out["is_staff"] = is_staff
        
    elif evt_type in ["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"]:
        out["event_type"] = "zone_entered" if evt_type == "ZONE_ENTER" else "zone_exited"
        out["track_id"] = vid
        out["store_id"] = store
        out["camera_id"] = cam
        out["zone_id"] = zone
        out["event_time"] = ts
        
    elif evt_type in ["BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"]:
        out["queue_event_id"] = our_event.get("event_id")
        out["event_type"] = "queue_abandoned"
        out["track_id"] = vid
        out["store_id"] = store
        out["camera_id"] = cam
        out["zone_id"] = zone
        out["queue_join_ts"] = ts
        out["abandoned"] = (evt_type == "BILLING_QUEUE_ABANDON")
        
    else:
        out = our_event # Fallback
        
    # Fill in dummy fields expected by the HackerEarth schema
    if "gender_pred" not in out and evt_type in ["ENTRY", "EXIT", "REENTRY"]:
        out["gender_pred"] = "U"
        out["age_pred"] = 30
        
    return out

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found. Please run your pipeline first to generate it.")
        return
        
    count = 0
    with open(INPUT_FILE, 'r') as infile, open(OUTPUT_FILE, 'w') as outfile:
        for line in infile:
            line = line.strip()
            if not line: continue
            
            try:
                our_event = json.loads(line)
                translated = translate_event(our_event)
                outfile.write(json.dumps(translated) + "\n")
                count += 1
            except json.JSONDecodeError:
                pass
                
    print(f"Success! Translated {count} events into {OUTPUT_FILE}")
    print("You can now submit hackerearth_events.jsonl alongside your standard events.jsonl!")

if __name__ == "__main__":
    main()
