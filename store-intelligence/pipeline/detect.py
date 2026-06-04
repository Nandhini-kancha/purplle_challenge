import cv2
import json
import argparse
from pathlib import Path
from ultralytics import YOLO
from pipeline.tracker import SessionTracker
from pipeline.emit import EventEmitter
import logging

# AI-ASSISTED: Used Claude to compare YOLOv8n vs YOLOv8m vs RT-DETR
# for retail CCTV constraints. Claude recommended YOLOv8m for accuracy
# but I chose YOLOv8n for CPU reproducibility — see CHOICES.md

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DetectionPipeline:
    def __init__(self, model_path="yolov8n.pt", api_url="http://localhost:8000/events/ingest"):
        self.model = YOLO(model_path)
        self.tracker = SessionTracker()
        self.emitter = EventEmitter(api_url)

    def load_zones(self, layout_file, store_id):
        try:
            with open(layout_file, 'r') as f:
                layout = json.load(f)
            self.zones = layout.get(store_id, {}).get("zones", [])
        except Exception as e:
            logger.warning(f"Could not load valid JSON from {layout_file} ({e}). Falling back to default mock zones for {store_id}.")
            self.zones = [
                {"zone_id": "ENTRY", "polygon": [[0,0], [1920,0], [1920,200], [0,200]]},
                {"zone_id": "BILLING", "polygon": [[0,200], [500,200], [500,1080], [0,1080]]},
                {"zone_id": "MAKEUP", "polygon": [[500,200], [1920,200], [1920,1080], [500,1080]]}
            ]
        return self.zones

    def process_video(self, video_path, store_id, camera_id, show=False):
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.info(f"Processing {video_path} | FPS: {fps} | Frames: {frame_count}")

        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Process every Nth frame to simulate real-time performance or just process all
            results = self.model.track(frame, persist=True, classes=[0], verbose=False) # class 0 is person
            
            if results[0].boxes.id is not None:
                if show:
                    annotated_frame = results[0].plot()
                    cv2.imshow("Detection Pipeline Demo", annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.cpu().numpy()
                confidences = results[0].boxes.conf.cpu().numpy()
                
                # In a real system, we also run an OSNet model here for Re-ID embeddings
                # to stitch tracks across cameras (cross-camera deduplication).
                # For this challenge, we use tracker.py for trajectory analysis and event generation.
                events = self.tracker.update(
                    frame_idx, fps, frame, boxes, track_ids, confidences,
                    store_id, camera_id, self.zones
                )
                
                if events:
                    self.emitter.queue_events(events)
            
            frame_idx += 1

        cap.release()
        self.emitter.flush() # Ensure remaining events are sent

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--layout", required=True)
    parser.add_argument("--store_id", required=True)
    parser.add_argument("--camera_id", required=True)
    parser.add_argument("--show", action="store_true", help="Display the video with annotations for recording")
    args = parser.parse_args()

    pipeline = DetectionPipeline()
    pipeline.load_zones(args.layout, args.store_id)
    pipeline.process_video(args.video, args.store_id, args.camera_id, show=args.show)
