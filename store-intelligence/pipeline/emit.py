import httpx
import logging

logger = logging.getLogger(__name__)

class EventEmitter:
    def __init__(self, api_url, batch_size=200):
        self.api_url = api_url
        self.batch_size = batch_size
        self.queue = []
        self.client = httpx.Client(timeout=10.0)

    def queue_events(self, events):
        self.queue.extend(events)
        if len(self.queue) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self.queue:
            return
            
        batch = self.queue[:self.batch_size]
        self.queue = self.queue[self.batch_size:]
        
        try:
            response = self.client.post(self.api_url, json=batch)
            response.raise_for_status()
            logger.info(f"Emitted batch of {len(batch)} events successfully.")
        except Exception as e:
            logger.error(f"Failed to emit events: {e}")
            # Real production system would retry or push to Dead Letter Queue (DLQ)
