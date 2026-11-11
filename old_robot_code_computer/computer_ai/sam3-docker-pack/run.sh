#!/usr/bin/env bash
# Run SAM3 FastAPI container (Linux/macOS)
# Run from the folder containing docker-compose.yml

cd "$(dirname "$0")"

echo "Building and starting SAM3 container..."
docker compose up -d --build

if [ $? -ne 0 ]; then
    echo "Failed."
    exit 1
fi

echo "Container is running. API: http://localhost:8222"
echo "  Health: http://localhost:8222/health"
echo "  GUI:    http://localhost:8222/gui"
