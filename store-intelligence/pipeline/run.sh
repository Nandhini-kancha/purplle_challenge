#!/bin/bash
# One command to process all clips -> events

VIDEO_DIR=$1
LAYOUT_FILE=$2

if [ -z "$VIDEO_DIR" ] || [ -z "$LAYOUT_FILE" ]; then
    echo "Usage: $0 <video_directory> <layout_file>"
    exit 1
fi

JSON_LAYOUT="dataset/store_layout.json"
echo "Converting layout $LAYOUT_FILE to $JSON_LAYOUT..."
python pipeline/convert_layout.py "$LAYOUT_FILE" "$JSON_LAYOUT"
LAYOUT_FILE="$JSON_LAYOUT"

# Example assumption: videos are named like STORE_BLR_002_CAM_ENTRY_01.mp4
for video in "$VIDEO_DIR"/*.mp4; do
    filename=$(basename -- "$video")
    store_id=$(echo $filename | grep -o 'STORE_[A-Z]*_[0-9]*')
    if [ -z "$store_id" ]; then
        store_id="ST1008"
    fi
    camera_id=$(basename -- "$filename" .mp4)
    
    echo "Processing Store: $store_id, Camera: $camera_id"
    python -m pipeline.detect --video "$video" --layout "$LAYOUT_FILE" --store_id "$store_id" --camera_id "$camera_id"
done
