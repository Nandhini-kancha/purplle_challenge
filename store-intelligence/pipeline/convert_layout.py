import sys
import json
import pandas as pd

def convert_layout(excel_file, out_json):
    print(f"Reading layout from {excel_file}...")
    try:
        df = pd.read_excel(excel_file)
        layout_dict = {}
        
        for _, row in df.iterrows():
            store_id = str(row.get("StoreID", "STORE_BLR_002")).strip()
            zone_id = str(row.get("ZoneID", "UNKNOWN")).strip()
            x = float(row.get("X", 0.0))
            y = float(row.get("Y", 0.0))
            
            if store_id not in layout_dict:
                layout_dict[store_id] = {"zones": []}
                
            zones_list = layout_dict[store_id]["zones"]
            zone_obj = next((z for z in zones_list if z["zone_id"] == zone_id), None)
            if not zone_obj:
                zone_obj = {"zone_id": zone_id, "polygon": []}
                zones_list.append(zone_obj)
                
            zone_obj["polygon"].append([x, y])
            
        with open(out_json, "w") as f:
            json.dump(layout_dict, f, indent=4)
        print(f"Successfully converted layout to {out_json}")
        
    except Exception as e:
        print(f"Failed to parse Excel cleanly ({e}). Generating fallback JSON layout...")
        fallback = {
            "STORE_BLR_002": {
                "zones": [
                    {"zone_id": "ENTRY", "polygon": [[0,0], [1920,0], [1920,200], [0,200]]},
                    {"zone_id": "BILLING", "polygon": [[0,200], [500,200], [500,1080], [0,1080]]},
                    {"zone_id": "SKINCARE", "polygon": [[500,200], [1920,200], [1920,1080], [500,1080]]}
                ]
            }
        }
        with open(out_json, "w") as f:
            json.dump(fallback, f, indent=4)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python convert_layout.py <input.xlsx> <output.json>")
        sys.exit(1)
    convert_layout(sys.argv[1], sys.argv[2])
