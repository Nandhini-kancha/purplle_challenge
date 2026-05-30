import uuid
from datetime import datetime, timezone, timedelta

class SessionTracker:
    def __init__(self):
        self.active_sessions = {}
        # Simple Re-ID mock map: global track id to session visitor id
        self.track_to_visitor = {}
        self.billing_queue = set()

    def update(self, frame_idx, fps, boxes, track_ids, confidences, store_id, camera_id, zones):
        """
        Takes raw detections and tracking outputs to generate business events.
        Handles group entry (each has unique track_id), staff movement (mocked staff check),
        and occlusion handling (ByteTrack holds IDs over missing frames).
        """
        events = []
        current_time = datetime.now(timezone.utc) + timedelta(seconds=frame_idx/fps)

        for box, t_id, conf in zip(boxes, track_ids, confidences):
            v_id = self.track_to_visitor.get(t_id)
            if not v_id:
                v_id = f"VIS_{uuid.uuid4().hex[:8]}"
                self.track_to_visitor[t_id] = v_id
                self.active_sessions[v_id] = {"seq": 0, "last_zone": None, "entered_billing": False}

                # Emit ENTRY
                self.active_sessions[v_id]["seq"] += 1
                events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": camera_id,
                    "visitor_id": v_id,
                    "event_type": "ENTRY",
                    "timestamp": current_time.isoformat(),
                    "zone_id": None,
                    "dwell_ms": 0,
                    "is_staff": False,  # Mocked VLM/Classifier staff detection
                    "confidence": float(conf),
                    "metadata": {
                        "queue_depth": None,
                        "sku_zone": None,
                        "session_seq": self.active_sessions[v_id]["seq"]
                    }
                })

            # Mock spatial zone logic based on box center
            cx, cy = (box[0] + box[2])/2, (box[1] + box[3])/2
            current_zone = self._get_zone_for_point(cx, cy, zones)
            
            session = self.active_sessions[v_id]
            if current_zone != session["last_zone"]:
                if session["last_zone"]:
                    # ZONE_EXIT
                    session["seq"] += 1
                    events.append(self._make_event(store_id, camera_id, v_id, "ZONE_EXIT", current_time, session["last_zone"], conf, session["seq"]))
                    
                    if session["last_zone"] == "BILLING":
                        # BILLING_QUEUE_ABANDON
                        if v_id in self.billing_queue:
                            self.billing_queue.remove(v_id)
                        session["seq"] += 1
                        events.append(self._make_event(store_id, camera_id, v_id, "BILLING_QUEUE_ABANDON", current_time, None, conf, session["seq"]))

                if current_zone:
                    # ZONE_ENTER
                    session["seq"] += 1
                    events.append(self._make_event(store_id, camera_id, v_id, "ZONE_ENTER", current_time, current_zone, conf, session["seq"]))
                    
                    if current_zone == "BILLING":
                        self.billing_queue.add(v_id)
                        session["seq"] += 1
                        evt = self._make_event(store_id, camera_id, v_id, "BILLING_QUEUE_JOIN", current_time, None, conf, session["seq"])
                        evt["metadata"]["queue_depth"] = len(self.billing_queue)
                        events.append(evt)

                session["last_zone"] = current_zone

        # In a real pipeline, we'd check for missing tracks to emit EXIT and clean up
        return events

    def _get_zone_for_point(self, cx, cy, zones):
        # Mock logic
        if cx < 500:
            return "SKINCARE"
        elif cx > 1000:
            return "BILLING"
        return "MAIN_FLOOR"

    def _make_event(self, store_id, camera_id, visitor_id, evt_type, ts, zone_id, conf, seq):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": evt_type,
            "timestamp": ts.isoformat(),
            "zone_id": zone_id,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": float(conf),
            "metadata": {
                "queue_depth": None,
                "sku_zone": zone_id if zone_id else None,
                "session_seq": seq
            }
        }
