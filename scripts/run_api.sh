#!/bin/bash
# LlamaIndex RAG API Watchdog Runner
# 自动重启崩溃的服务，确保 API 始终可用
# macOS 兼容版本

PROJECT_DIR="/Users/luopingcheng/Documents/GitHub/llamaindex-study"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"
API_PORT="${API_PORT:-37241}"
PID_FILE="$PROJECT_DIR/.api.pid"
WATCHDOG_PID_FILE="$PROJECT_DIR/.api_watchdog.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    local level="$1"
    local msg="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" | tee -a "$LOG_DIR/api_watchdog.log"
}

log_info() { log "INFO" "$1"; }
log_warn() { log "WARN" "$1"; }
log_error() { log "ERROR" "$1"; }

mkdir -p "$LOG_DIR"

is_watchdog_running() {
    if [ -f "$WATCHDOG_PID_FILE" ]; then
        local pid=$(cat "$WATCHDOG_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

acquire_lock() {
    if is_watchdog_running; then
        local pid=$(cat "$WATCHDOG_PID_FILE" 2>/dev/null)
        log_error "Another watchdog is already running (PID: $pid)"
        echo -e "${RED}✗ Another instance is running (PID: $pid)${NC}"
        exit 1
    fi
    echo $$ > "$WATCHDOG_PID_FILE"
}

cleanup_all() {
    log_info "Cleaning up all processes..."

    # 只通过端口清理进程，不依赖 PID 文件
    local port_pids=$(lsof -ti:$API_PORT 2>/dev/null) || true
    if [ -n "$port_pids" ]; then
        echo "$port_pids" | tr ' ' '\n' | xargs kill -9 2>/dev/null || true
    fi

    # 杀掉 api.py 进程
    local api_pids=$(ps aux 2>/dev/null | grep -E "[p]ython.*api\.py|[u]vicorn.*api:app" 2>/dev/null | awk '{print $2}' | tr '\n' ' ') || true
    if [ -n "$api_pids" ]; then
        echo "$api_pids" | tr ' ' '\n' | xargs kill -9 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    sleep 1
}

start_api() {
    log_info "Starting API server..."

    cd "$PROJECT_DIR"

    nohup uv run python api.py > "$LOG_DIR/api.stdout.log" 2>&1 &

    local pid=$!
    echo $pid > "$PID_FILE"

    sleep 5

    if kill -0 $pid 2>/dev/null; then
        log_info "API server started (PID: $pid, Port: $API_PORT)"
        echo -e "${GREEN}✓ API running at http://localhost:$API_PORT/docs${NC}"
        return 0
    else
        log_error "API server failed to start"
        echo -e "${RED}✗ API failed to start${NC}"
        tail -10 "$LOG_DIR/api.stderr.log" 2>/dev/null || true
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_api() {
    log_info "Stopping API server..."

    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ]; then
            kill $pid 2>/dev/null || true
            sleep 1
            kill -9 $pid 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi

    local port_pids=$(lsof -ti:$API_PORT 2>/dev/null) || true
    if [ -n "$port_pids" ]; then
        echo "$port_pids" | tr ' ' '\n' | xargs kill -9 2>/dev/null || true
    fi

    rm -f "$WATCHDOG_PID_FILE"
}

restart_api() {
    stop_api
    sleep 2
    start_api
}

check_uv() {
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}✗ uv is required but not installed${NC}"
        exit 1
    fi
}

check_api_health() {
    local response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$API_PORT/health" 2>/dev/null || echo "000")
    [ "$response" = "200" ]
}

status_api() {
    local port_pid=$(lsof -ti:$API_PORT 2>/dev/null)

    if [ -n "$port_pid" ] && check_api_health; then
        echo -e "${GREEN}✓ API is running${NC} (Port: $API_PORT, PID: $port_pid)"
        return 0
    elif [ -n "$port_pid" ]; then
        echo -e "${YELLOW}⚠ Port in use but not responding${NC} (PID: $port_pid)"
        return 1
    else
        echo -e "${RED}✗ API is not running${NC}"
        return 1
    fi
}

cleanup() {
    rm -f "$WATCHDOG_PID_FILE"
}
trap cleanup EXIT

case "${1:-start}" in
    start)
        check_uv
        acquire_lock

        if [ -f "$PROJECT_DIR/api.py" ] && [ -f "$PROJECT_DIR/pyproject.toml" ]; then
            log_info "Starting LlamaIndex RAG API..."
        else
            log_error "Required files not found"
            exit 1
        fi

        cleanup_all
        start_api

        log_info "Watchdog started - monitoring every 30 seconds"
        while true; do
            sleep 30
            if ! check_api_health; then
                log_warn "API not responding, restarting..."
                start_api
            fi
        done
        ;;

    stop)
        cleanup_all
        echo -e "${GREEN}✓ Stopped${NC}"
        ;;

    restart)
        check_uv
        acquire_lock
        restart_api
        echo -e "${GREEN}✓ Restarted${NC}"
        while true; do
            sleep 30
            if ! check_api_health; then
                log_warn "API not responding, restarting..."
                start_api
            fi
        done
        ;;

    status)
        status_api
        ;;

    logs)
        if [ -f "$LOG_DIR/api_watchdog.log" ]; then
            tail -30 "$LOG_DIR/api_watchdog.log"
        else
            echo "No log file"
        fi
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
