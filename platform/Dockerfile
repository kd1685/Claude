FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (all modules: signals, bots, execution, auth, AI…)
COPY *.py ./
COPY static/ ./static/

EXPOSE 8000

# --proxy-headers: trust X-Forwarded-For from Caddy so per-IP security
# (brute-force lockout, rate limits) sees the REAL client IP, not the proxy.
# Safe here because port 8000 is only exposed on the internal compose network.
# NEVER add --workers >1: bots, caches and quotas are in-process state.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
