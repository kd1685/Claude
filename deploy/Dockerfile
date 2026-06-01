FROM python:3.11-slim

# tesseract + adb for the live (adb) control backend and OCR scanner.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr android-tools-adb libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-adb.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-adb.txt

COPY . .

ENV HOST=0.0.0.0 PORT=8000 DB_PATH=/data/rok1685.db
VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
