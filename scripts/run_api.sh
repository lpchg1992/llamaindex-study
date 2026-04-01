#!/bin/bash
# LlamaIndex RAG API Watchdog Runner
# 自动重启崩溃的服务，确保 API 始终可用

PROJECT_DIR="/Users/luopingcheng/Documents/GitHub/llamaindex-study"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"
API_PORT="${API_PORT:-37241}"
PID_FILE="$PROJECT_DIR/.api.pid"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_DIR/api_watchdog.log"
}

get_venv_python() {
    if [ -f "$VENV_DIR/bin/python" ]; then
        echo "$VENV_DIR/bin/python"
    elif [ -f "$VENV_DIR/bin/python3" ]; then
        echo "$VENV_DIR/bin/python3"
    else
        echo ""
    fi
}

# Find and kill existing API process on port
kill_existing_on_port() {
    local existing_pid=$(lsof -ti:$API_PORT 2>/dev/null)
    if [ -n "$existing_pid" ]; then
        log "Found existing process on port $API_PORT (PID: $existing_pid), killing..."
        kill -9 $existing_pid 2>/dev/null
        sleep 1
    fi
}

# Clean up stale PID file and any orphaned processes
cleanup_stale() {
    if [ -f "$PID_FILE" ]; then
        local stale_pid=$(cat "$PID_FILE")
        if [ -n "$stale_pid" ] && [ "$stale_pid" != "0" ]; then
            if kill -0 $stale_pid 2>/dev/null; then
                log "Found stale PID file (PID: $stale_pid), killing orphaned process..."
                kill -9 $stale_pid 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi

    # Also check for any orphaned api.py processes
    local orphaned=$(ps aux | grep -E "[a]pi\.py|[u]vicorn.*api:app" | awk '{print $2}')
    if [ -n "$orphaned" ]; then
        log "Found orphaned API processes (PIDs: $orphaned), killing..."
        echo "$orphaned" | xargs kill -9 2>/dev/null
    fi
}

start_api() {
    local python_path="$1"
    
    log "Starting API server..."
    
    # Start API using uv run
    cd "$PROJECT_DIR"
    PYTHONPATH="$PROJECT_DIR/src" $python_path -m uvicorn api:app --host 0.0.0.0 --port $API_PORT >> "$LOG_DIR/api.stdout.log" 2>> "$LOG_DIR/api.stderr.log" &
    local pid=$!
    echo $pid > "$PID_FILE"
    
    sleep 2
    
    # Verify it started
    if kill -0 $pid 2>/dev/null; then
        log "API server started on port $API_PORT (PID: $pid)"
    else
        log "ERROR: API server failed to start"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_api() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            kill $pid 2>/dev/null
            log "API server (PID: $pid) stopped"
        fi
        rm -f "$PID_FILE"
    fi
    
    # Ensure no lingering processes
    local remaining=$(lsof -ti:$API_PORT 2>/dev/null)
    if [ -n "$remaining" ]; then
        log "Killing remaining process on port $API_PORT (PID: $remaining)"
        kill -9 $remaining 2>/dev/null
    fi
}

restart_api() {
    local python_path="$1"
    log "Restarting API server..."
    stop_api
    sleep 1
    start_api "$python_path"
}

# Check if uv is available
if ! command -v uv &> /dev/null; then
    log "ERROR: uv not found. Please install uv: https://github.com/astral-sh/uv"
    exit 1
fi

# Pre-flight cleanup - kill any existing processes
log "Pre-flight cleanup..."
cleanup_stale
kill_existing_on_port

# Check if virtualenv exists, create if not
python_path=$(get_venv_python)
if [ -z "$python_path" ]; then
    log "Virtual environment not found, creating..."
    cd "$PROJECT_DIR"
    uv venv
    uv sync
    python_path=$(get_venv_python)
    if [ -z "$python_path" ]; then
        log "ERROR: Failed to create virtual environment"
        exit 1
    fi
    log "Virtual environment created successfully"
fi

# Initial start
log "API Watchdog started"
start_api "$python_path"

# Watchdog loop
while true; do
    sleep 30
    
    # Check if API is responding
    if ! curl -s "http://localhost:$API_PORT/health" > /dev/null 2>&1; then
        log "API not responding, restarting..."
        restart_api "$python_path"
    fi
done
