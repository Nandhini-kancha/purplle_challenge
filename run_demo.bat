@echo off
cd C:\Users\Nandhini\OneDrive\Desktop\purple\store-intelligence
set PYTHONPATH=.
echo Launching AI Detection Pipeline for CAM 1.mp4...
echo Press 'q' on the video window to close it.
python pipeline/detect.py --video "../dataset/CAM 1.mp4" --layout "../dataset/Brigade Road - Store layoutc5f5d56.xlsx" --store_id ST1008 --camera_id CAM_01 --show
pause
