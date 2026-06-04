import uuid
from datetime import datetime, timezone, timedelta
import cv2
import numpy as np

class SessionTracker:
    def __init__(self):
        self.active_sessions = {}
        # Simple Re-ID mock map: global track id to session visitor id
        self.track_to_visitor = {}
        self.billing_queue = set()
        self.exited_visitors = {}

    def update(self, frame_idx, fps, frame, boxes, track_ids, confidences, store_id, camera_id, zones):
        """
        Takes raw detections and tracking outputs to generate business events.
        Handles group entry (each has unique track_id), staff movement (mocked staff check),
        and occlusion handling (ByteTrack holds IDs over missing frames).
        """
        events = []
        current_time = datetime.now(timezone.utc) + timedelta(seconds=frame_idx/fps)
        seen_v_ids = set()

        for box, t_id, conf in zip(boxes, track_ids, confidences):
            v_id = self.track_to_visitor.get(t_id)
            is_staff_val = self._is_staff_color(frame, box)

            if not v_id:
                # Check for recent exit (Re-Entry heuristic)
                recycled_v_id = None
                for ev_id, exit_time in list(self.exited_visitors.items()):
                    if (current_time - exit_time).total_seconds() < 300:
                        recycled_v_id = ev_id
                        del self.exited_visitors[ev_id]
                        break

                if recycled_v_id:
                    v_id = recycled_v_id
                    self.track_to_visitor[t_id] = v_id

                    # Restore session if cleaned up
                    if v_id not in self.active_sessions:
                        self.active_sessions[v_id] = {
                            "seq": 0,
                            "last_zone": None,
                            "status": "ACTIVE",
                            "last_seen_frame": frame_idx,
                            "zone_enter_time": current_time,
                            "last_dwell_emit": current_time,
                            "is_staff": is_staff_val
                        }

                    # Emit REENTRY immediately here
                    self.active_sessions[v_id]["status"] = "ACTIVE"
                    self.active_sessions[v_id]["zone_enter_time"] = current_time
                    self.active_sessions[v_id]["last_dwell_emit"] = current_time
                    self.active_sessions[v_id]["seq"] += 1
                    events.append(self._make_event(
                        store_id, camera_id, v_id, "REENTRY",
                        current_time, None, conf,
                        self.active_sessions[v_id]["seq"], is_staff_val
                    ))
                else:
                    v_id = f"VIS_{uuid.uuid4().hex[:8]}"
                    self.track_to_visitor[t_id] = v_id
                    self.active_sessions[v_id] = {
                        "seq": 0, 
                        "last_zone": None, 
                        "status": "ACTIVE",
                        "last_seen_frame": frame_idx,
                        "zone_enter_time": current_time,
                        "last_dwell_emit": current_time,
                        "is_staff": is_staff_val
                    }
    
                    # Emit ENTRY
                    self.active_sessions[v_id]["seq"] += 1
                    events.append(self._make_event(store_id, camera_id, v_id, "ENTRY", current_time, None, conf, self.active_sessions[v_id]["seq"], is_staff_val))
            
            session = self.active_sessions[v_id]
            seen_v_ids.add(v_id)
            session["last_seen_frame"] = frame_idx
            


            # Spatial zone logic based on box center
            cx, cy = (box[0] + box[2])/2, (box[1] + box[3])/2
            current_zone = self._get_zone_for_point(cx, cy, zones)
            
            if current_zone != session["last_zone"]:
                if session["last_zone"]:
                    # ZONE_EXIT
                    session["seq"] += 1
                    total_dwell = (current_time - session.get("zone_enter_time", current_time)).total_seconds() * 1000
                    evt = self._make_event(store_id, camera_id, v_id, "ZONE_EXIT", current_time, session["last_zone"], conf, session["seq"], session["is_staff"])
                    evt["dwell_ms"] = int(total_dwell)
                    events.append(evt)
                    
                    if session["last_zone"] == "BILLING":
                        # BILLING_QUEUE_ABANDON
                        if v_id in self.billing_queue:
                            self.billing_queue.remove(v_id)
                        session["seq"] += 1
                        events.append(self._make_event(store_id, camera_id, v_id, "BILLING_QUEUE_ABANDON", current_time, None, conf, session["seq"], session["is_staff"]))

                if current_zone:
                    # ZONE_ENTER
                    session["seq"] += 1
                    session["zone_enter_time"] = current_time
                    session["last_dwell_emit"] = current_time
                    events.append(self._make_event(store_id, camera_id, v_id, "ZONE_ENTER", current_time, current_zone, conf, session["seq"], session["is_staff"]))
                    
                    if current_zone == "BILLING":
                        self.billing_queue.add(v_id)
                        session["seq"] += 1
                        evt = self._make_event(store_id, camera_id, v_id, "BILLING_QUEUE_JOIN", current_time, None, conf, session["seq"], session["is_staff"])
                        evt["metadata"]["queue_depth"] = len(self.billing_queue)
                        events.append(evt)

                session["last_zone"] = current_zone
            else:
                if current_zone:
                    # Check dwell
                    dwell_duration = (current_time - session["last_dwell_emit"]).total_seconds()
                    if dwell_duration >= 30:
                        session["seq"] += 1
                        total_dwell = (current_time - session["zone_enter_time"]).total_seconds() * 1000
                        evt = self._make_event(store_id, camera_id, v_id, "ZONE_DWELL", current_time, current_zone, conf, session["seq"], session["is_staff"])
                        evt["dwell_ms"] = int(total_dwell)
                        events.append(evt)
                        session["last_dwell_emit"] = current_time

        # Check missing tracks to emit EXIT
        for v_id, session in self.active_sessions.items():
            if session.get("status") == "ACTIVE" and v_id not in seen_v_ids:
                if frame_idx - session.get("last_seen_frame", frame_idx) > 30:
                    session["status"] = "EXITED"
                    self.exited_visitors[v_id] = current_time
                    session["seq"] += 1
                    events.append(self._make_event(store_id, camera_id, v_id, "EXIT", current_time, session.get("last_zone"), 1.0, session["seq"], session["is_staff"]))
                    
                    if session.get("last_zone"):
                        session["seq"] += 1
                        total_dwell = (current_time - session.get("zone_enter_time", current_time)).total_seconds() * 1000
                        evt = self._make_event(store_id, camera_id, v_id, "ZONE_EXIT", current_time, session["last_zone"], 1.0, session["seq"], session["is_staff"])
                        evt["dwell_ms"] = int(total_dwell)
                        events.append(evt)
                        if session["last_zone"] == "BILLING" and v_id in self.billing_queue:
                            self.billing_queue.remove(v_id)
                            session["seq"] += 1
                            events.append(self._make_event(store_id, camera_id, v_id, "BILLING_QUEUE_ABANDON", current_time, None, 1.0, session["seq"], session["is_staff"]))
                        session["last_zone"] = None

        return events

    def _get_zone_for_point(self, cx, cy, zones):
        for zone in zones:
            polygon = zone.get("polygon", [])
            if not polygon:
                continue
            
            # Ray casting algorithm
            n = len(polygon)
            inside = False
            p1x, p1y = polygon[0]
            for i in range(n + 1):
                p2x, p2y = polygon[i % n]
                if cy > min(p1y, p2y):
                    if cy <= max(p1y, p2y):
                        if cx <= max(p1x, p2x):
                            if p1y != p2y:
                                xints = (cy - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                                if p1x == p2x or cx <= xints:
                                    inside = not inside
                p1x, p1y = p2x, p2y
                
            if inside:
                return zone.get("zone_id")
                
        return None

    def _is_staff_color(self, frame, box):
        # Extract box color, check if it matches staff uniform
        x1, y1, x2, y2 = map(int, box)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
        if x2 <= x1 or y2 <= y1: return False
        
        # Focus on the upper body (blazer/shirt area)
        y_mid = y1 + (y2 - y1) // 2
        crop = frame[y1:y_mid, x1:x2]
        
        if crop.size == 0: return False
        
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        
        # Check for original Purple/Magenta
        lower_purple = np.array([130, 50, 50])
        upper_purple = np.array([170, 255, 255])
        mask_purple = cv2.inRange(hsv, lower_purple, upper_purple)
        
        # Check for Black Blazer (Low Value/Brightness)
        lower_black = np.array([0, 0, 0])
        upper_black = np.array([180, 255, 50])  # Value < 50 is very dark/black
        mask_black = cv2.inRange(hsv, lower_black, upper_black)
        
        # Combine masks
        mask = cv2.bitwise_or(mask_purple, mask_black)
        
        color_ratio = cv2.countNonZero(mask) / (mask.shape[0] * mask.shape[1] + 1e-6)
        
        # If more than 30% of the upper body is black or purple, flag as staff
        return color_ratio > 0.30

    def _make_event(self, store_id, camera_id, visitor_id, evt_type, ts, zone_id, conf, seq, is_staff=False):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": evt_type,
            "timestamp": ts.isoformat(),
            "zone_id": zone_id,
            "dwell_ms": 0,
            "is_staff": is_staff,
            "confidence": float(conf),
            "metadata": {
                "queue_depth": None,
                "sku_zone": zone_id if zone_id else None,
                "session_seq": seq
            }
        }
