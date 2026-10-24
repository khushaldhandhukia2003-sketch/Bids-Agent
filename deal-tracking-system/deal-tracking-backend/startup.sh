#!/bin/bash
cd /home/site/wwwroot

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
# B1: Tell Python's allocator to release memory back to OS after each request
export MALLOC_TRIM_THRESHOLD_=65536
export PYTHONMALLOC=malloc

gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app \
  --bind 0.0.0.0:8000 \
  --timeout 220 \
  --keep-alive 5 \
  --max-requests 200 \
  --max-requests-jitter 50 \
  --worker-tmp-dir /dev/shm
