# Minimal image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY app.py /app/app.py

RUN pip install --no-cache-dir requests

# Default envs (override at run-time)
ENV POLL_EVERY_HOURS=4 \
    HIGH_BORDER=6.5 \
    MEDIUM_BORDER=5.0 \
    MAX_FETCH=100 \
    BATCH_SIZE=50 \
    OPENAI_MODEL=gpt-5-nano

CMD ["python", "-u", "app.py"]
