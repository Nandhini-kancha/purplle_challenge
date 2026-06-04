# Apex Retail: Store Intelligence Project
## A Simple Explanation of the Solution

### 1. The Core Problem
Apex Retail has 40 physical stores and wants to track customer behavior in these stores, similar to how they track clicks and sessions on their website. They have raw CCTV video footage, but no easy way to turn that video into actionable business data.

The goal of this project was to build a system that takes raw camera video, detects customer behavior, and turns it into real-time metrics like "Conversion Rate", "Queue Depth", and "Zone Popularity".

### 2. What We Built
We built an end-to-end "Store Intelligence" pipeline broken down into a few main stages:

* **Detection Layer (The "Eyes")**: This runs on the camera side. It watches the video and detects people, tracks their movement, and figures out if they are a customer or staff. 
* **Event Stream (The "Messenger")**: Instead of sending heavy video data or sending a message every single second a person is on screen, the system only sends important "events"—like when someone enters a specific zone (e.g., the Skincare aisle), stays there for 30 seconds (dwell time), or joins the billing queue.
* **Intelligence API (The "Brain")**: A centralized server that ingests all these events from multiple stores, saves them in a database, and calculates real-time analytics.

### 3. How We Addressed the Problem (Key Decisions)

We had to make several architectural choices to make sure the system is fast, reliable, and can handle edge cases like crowded billing lines.

* **Choosing the Right AI Vision Model**: We chose **YOLOv8** combined with **ByteTrack**. Why? While other models like RT-DETR might be slightly more accurate, YOLOv8 is incredibly fast. Since we have to process 120 camera streams across 40 stores, speed is critical. ByteTrack is excellent at keeping track of a person's ID even if they briefly walk behind an obstacle or another person (partial occlusion).
* **Smart Data Schema**: AI tools initially suggested sending a raw update for every frame of video. We chose to **override this** and instead send "Stateful Transition Events" (e.g., only send a message when a person *enters* or *leaves* an area). This reduces the amount of data sent over the network by 99% and prevents our backend servers from crashing under the load.
* **Strong Database Choice**: We used **SQLite** instead of NoSQL alternatives. Our store events are highly structured (we know exactly what an event looks like), and SQLite is incredibly good at running the complex math required for conversion funnels natively, while offering unmatched simplicity and zero-configuration setup that is well-suited for a lightweight analytics pipeline.
* **Scalable Anomaly Detection**: We agreed with AI suggestions to use statistical methods (like rolling averages and standard deviation over a 7-day period) to flag anomalies, rather than hardcoding static limits. This means the system will automatically adapt to each store's unique traffic patterns.

### Summary
In short, we built a highly scalable pipeline that converts unstructured video into structured, actionable business events, while making intentional trade-offs to prioritize speed, reduce network bandwidth, and keep infrastructure simple and robust.
