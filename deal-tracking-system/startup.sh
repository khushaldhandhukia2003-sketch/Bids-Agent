#!/bin/bash
cd /home/site/wwwroot

# Create venv only if it doesn't exist
if [ ! -d "antenv" ]; then
    python -m venv antenv
fi

# Activate it
source antenv/bin/activate

# Install packages into the venv
pip install -r requirements.txt

# Start with the venv's gunicorn
antenv/bin/gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --timeout 120