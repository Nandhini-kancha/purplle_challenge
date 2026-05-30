FROM python:3.11-slim

WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY pipeline/ ./pipeline/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
