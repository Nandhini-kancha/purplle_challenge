# Store Intelligence API

A production-grade computer vision pipeline and analytics API built for the Purplle Tech Challenge. This repository processes raw CCTV footage, identifies shoppers, and emits events to a real-time analytics engine.

## Setup Instructions

As required, you can bring up the entire environment and run tests in 5 commands.

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd store-intelligence
   ```

2. **Start the API and Database:**
   ```bash
   docker-compose up -d --build
   ```

3. **Install dependencies for the detection pipeline (local):**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the detection pipeline against the video clips:**
   *Note: Ensure your dataset is extracted and accessible.*
   ```bash
   python pipeline/run.sh /path/to/cctv_clips_folder /path/to/store_layout.json
   ```

5. **Run the API tests:**
   ```bash
   pytest tests/
   ```

## Architecture

* **Detection Layer (`pipeline/`)**: Uses YOLOv8 for object detection, ByteTrack for tracking, and spatial logic for zone interactions. The events are formatted according to the spec and sent to the API.
* **Intelligence API (`app/`)**: A FastAPI service connected to an asynchronous PostgreSQL database. It features idempotent ingestion, robust metric aggregation, and anomaly detection.
