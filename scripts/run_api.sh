#!/bin/bash
# LlamaIndex RAG API Watchdog Runner
# 自动重启崩溃的服务，确保 API 始终可用

PROJECT_DIR="/Users/luopingcheng/Documents/GitHub/llamaindex-study"
LOG_DIR="$PROJECT_DIR/logs"
API_PORT="${API_PORT:-37241}"
MAX_RETRIES=10
RETRY_DELAY=5

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_DIR/api_watchdog.log"
}

restart_api() {
    log "Restarting API server..."
    
    # Kill existing process if any
    pkill -f "uvicorn api:app.*port=$API_PORT" 2>/dev/null
    sleep 1
    
    # Start API using poetry's venv (poetry keeps creating it at wol-wake-pc)
    cd "$PROJECT_DIR"
    PYTHONPATH="$PROJECT_DIR/src" /Users/luopingcheng/Documents/GitHub/wol-wake-pc/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port $API_PORT >> "$LOG_DIR/api.stdout.log" 2>> "$LOG_DIR/api.stderr.log" &
    
    log "API server started on port $API_PORT"
}

# Initial start
log "API Watchdog started"
restart_api

# Watchdog loop
while true; do
    sleep 30
    
    # Check if API is responding
    if ! curl -s "http://localhost:$API_PORT/health" > /dev/null 2>&1; then
        log "API not responding, restarting..."
        restart_api
    fi
done
