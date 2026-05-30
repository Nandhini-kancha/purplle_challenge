#!/bin/bash
# One command to process all clips -> events

VIDEO_DIR=$1
LAYOUT_FILE=$2

if [ -z "$VIDEO_DIR" ] || [ -z "$LAYOUT_FILE" ]; then
    echo "Usage: $0 <video_directory> <layout_file>"
    exit 1
fi

# Example assumption: videos are named like STORE_BLR_002_CAM_ENTRY_01.mp4
for video in "$VIDEO_DIR"/*.mp4; do
    filename=$(basename -- "$video")
    # Very naive split for demo: STORE_BLR_002_CAM_ENTRY_01.mp4
    # Store ID: STORE_BLR_002
    # Camera ID: CAM_ENTRY_01
    store_id=$(echo $filename | grep -o 'STORE_[A-Z]*_[0-9]*')
    camera_id=$(echo $filename | sed -e "s/^${store_id}_//" -e "s/.mp4$//")
    
    echo "Processing Store: $store_id, Camera: $camera_id"
    python -m pipeline.detect --video "$video" --layout "$LAYOUT_FILE" --store_id "$store_id" --camera_id "$camera_id"
done
