#!/bin/bash
# LlamaIndex RAG API Watchdog Runner
# 自动重启崩溃的服务，确保 API 始终可用

set -e

PROJECT_DIR="/Users/luopingcheng/Documents/GitHub/llamaindex-study"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"
API_PORT="${API_PORT:-37241}"
PID_FILE="$PROJECT_DIR/.api.pid"
LOCK_FILE="$PROJECT_DIR/.api.lock"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    local level="$1"
    local msg="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" | tee -a "$LOG_DIR/api_watchdog.log"
}

log_info() { log "INFO" "$1"; }
log_warn() { log "WARN" "$1"; }
log_error() { log "ERROR" "$1"; }

# 创建日志目录
mkdir -p "$LOG_DIR"

# Find and kill existing API process on port
kill_existing_on_port() {
    local existing_pid=$(lsof -ti:$API_PORT 2>/dev/null)
    if [ -n "$existing_pid" ]; then
        log_warn "Found existing process on port $API_PORT (PID: $existing_pid), killing..."
        kill -9 $existing_pid 2>/dev/null || true
        sleep 1
    fi
}

# Clean up stale PID file and any orphaned processes
cleanup_stale() {
    if [ -f "$PID_FILE" ]; then
        local stale_pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$stale_pid" ] && [ "$stale_pid" != "0" ]; then
            if kill -0 $stale_pid 2>/dev/null; then
                log_warn "Found stale PID file (PID: $stale_pid), killing orphaned process..."
                kill -9 $stale_pid 2>/dev/null || true
            fi
        fi
        rm -f "$PID_FILE"
    fi

    # Also check for any orphaned api.py processes
    local orphaned=$(ps aux 2>/dev/null | grep -E "[a]pi\.py|[u]vicorn.*api:app" | awk '{print $2}' | tr '\n' ' ')
    if [ -n "$orphaned" ]; then
        log_warn "Found orphaned API processes (PIDs: $orphaned), killing..."
        echo "$orphaned" | tr ' ' '\n' | xargs kill -9 2>/dev/null || true
    fi
}

start_api() {
    log_info "Starting API server..."

    # 确保在项目目录
    cd "$PROJECT_DIR"

    # 使用 uv run 启动服务（关键修复：确保加载正确的虚拟环境依赖）
    # --python选项指定使用项目的虚拟环境Python
    nohup uv run --python "$VENV_DIR/bin/python" \
        uvicorn api:app \
        --host 0.0.0.0 \
        --port $API_PORT \
        >> "$LOG_DIR/api.stdout.log" 2>> "$LOG_DIR/api.stderr.log" &

    local pid=$!
    echo $pid > "$PID_FILE"

    sleep 3

    # Verify it started
    if kill -0 $pid 2>/dev/null; then
        log_info "API server started successfully on port $API_PORT (PID: $pid)"
        echo -e "${GREEN}✓ API server running at http://localhost:$API_PORT/docs${NC}"
    else
        log_error "API server failed to start. Check logs:"
        echo -e "${RED}✗ API server failed to start${NC}"
        echo -e "${YELLOW}See $LOG_DIR/api.stderr.log for details${NC}"
        tail -20 "$LOG_DIR/api.stderr.log" 2>/dev/null || true
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_api() {
    log_info "Stopping API server..."

    # 先尝试使用 PID 文件停止
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            kill $pid 2>/dev/null || true
            sleep 1
            # 如果还没停掉，强制杀死
            if kill -0 $pid 2>/dev/null; then
                kill -9 $pid 2>/dev/null || true
            fi
            log_info "API server (PID: $pid) stopped"
        fi
        rm -f "$PID_FILE"
    fi

    # 确保端口上没有残留进程
    local remaining=$(lsof -ti:$API_PORT 2>/dev/null)
    if [ -n "$remaining" ]; then
        log_warn "Killing remaining process on port $API_PORT (PID: $remaining)"
        kill -9 $remaining 2>/dev/null || true
    fi

    rm -f "$LOCK_FILE" "$PROJECT_DIR/.api_watchdog.pid"
}

restart_api() {
    log_info "Restarting API server..."
    stop_api
    sleep 2
    start_api
}

# Check if uv is available
check_uv() {
    if ! command -v uv &> /dev/null; then
        log_error "uv not found. Please install uv: https://github.com/astral-sh/uv"
        echo -e "${RED}✗ uv is required but not installed${NC}"
        exit 1
    fi
    log_info "uv version: $(uv --version)"
}

# Ensure virtual environment is set up
setup_venv() {
    cd "$PROJECT_DIR"

    if [ ! -d "$VENV_DIR" ]; then
        log_info "Creating virtual environment..."
        uv venv
        log_info "Virtual environment created"
    fi

    # 关键：始终同步依赖，确保 pyproject.toml 中的所有包都已安装
    log_info "Syncing dependencies with uv..."
    uv sync

    # 验证关键包已安装
    if ! uv run python -c "from llama_index.llms.ollama import Ollama" 2>/dev/null; then
        log_error "llama_index.llms.ollama not found after uv sync!"
        log_error "Please check pyproject.toml dependencies"
        return 1
    fi

    log_info "Dependencies verified"
}

# Pre-flight checks
preflight_checks() {
    log_info "Running pre-flight checks..."

    # 检查项目目录
    if [ ! -d "$PROJECT_DIR" ]; then
        log_error "Project directory not found: $PROJECT_DIR"
        exit 1
    fi

    # 检查 api.py 是否存在
    if [ ! -f "$PROJECT_DIR/api.py" ]; then
        log_error "api.py not found in $PROJECT_DIR"
        exit 1
    fi

    # 检查 pyproject.toml
    if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
        log_error "pyproject.toml not found in $PROJECT_DIR"
        exit 1
    fi

    log_info "Pre-flight checks passed"
}

# Check API health
check_api_health() {
    local response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$API_PORT/health" 2>/dev/null || echo "000")
    if [ "$response" = "200" ]; then
        return 0
    else
        return 1
    fi
}

# Status command
status_api() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
            if check_api_health; then
                echo -e "${GREEN}✓ API server is running${NC} (PID: $pid, Port: $API_PORT)"
                return 0
            else
                echo -e "${YELLOW}⚠ API process exists but not responding${NC} (PID: $pid, Port: $API_PORT)"
                return 1
            fi
        fi
    fi

    # 检查端口是否被占用
    local port_pid=$(lsof -ti:$API_PORT 2>/dev/null)
    if [ -n "$port_pid" ]; then
        echo -e "${YELLOW}⚠ Port $API_PORT is in use by PID $port_pid (no PID file)${NC}"
        return 1
    fi

    echo -e "${RED}✗ API server is not running${NC}"
    return 1
}

is_daemon_mode() {
    for arg in "$@"; do
        if [[ "$arg" == "--daemon" ]] || [[ "$arg" == "-d" ]]; then
            return 0
        fi
    done
    return 1
}

acquire_lock() {
    exec 200>"$LOCK_FILE"
    if ! flock -n 200; then
        local existing_pid=$(cat "$PROJECT_DIR/.api_watchdog.pid" 2>/dev/null || echo "unknown")
        log_error "Another instance is already running (PID: $existing_pid)"
        echo -e "${RED}✗ Another instance is already running (PID: $existing_pid)${NC}"
        exit 1
    fi
}

daemonize() {
    local cmd="$0"
    local args="$@"
    log_info "Daemonizing API runner..."
    nohup setsid "$cmd" $args > "$LOG_DIR/api_watchdog.stdout.log" 2>&1 &
    echo $! > "$PROJECT_DIR/.api_watchdog.pid"
    echo -e "${GREEN}✓ API runner daemonized (PID: $(cat $PROJECT_DIR/.api_watchdog.pid))${NC}"
    echo -e "${GREEN}✓ Logs: $LOG_DIR/api_watchdog.log${NC}"
    exit 0
}

# Main command dispatcher
case "${1:-start}" in
    start)
        if is_daemon_mode "$@"; then
            local new_args=$(echo "$@" | sed 's/--daemon//g' | sed 's/-d//g' | sed 's/^ *//' | sed 's/ *$//')
            daemonize ${new_args:-$1}
        fi

        acquire_lock

        check_uv
        preflight_checks
        log_info "=== Starting LlamaIndex RAG API ==="
        setup_venv
        cleanup_stale
        kill_existing_on_port
        start_api

        # 启动看门狗循环
        log_info "API Watchdog started - monitoring every 30 seconds"
        while true; do
            sleep 30

            if ! check_api_health; then
                log_warn "API not responding, restarting..."
                echo -e "${YELLOW}⚠ API not responding, restarting...${NC}"
                restart_api
            fi
        done
        ;;

    stop)
        log_info "Stopping API server..."
        stop_api
        echo -e "${GREEN}✓ API server stopped${NC}"
        ;;

    restart)
        check_uv
        log_info "Restarting API server..."
        restart_api
        echo -e "${GREEN}✓ API server restarted${NC}"
        ;;

    status)
        status_api
        ;;

    logs)
        if [ -f "$LOG_DIR/api_watchdog.log" ]; then
            tail -50 "$LOG_DIR/api_watchdog.log"
        else
            echo "No log file found"
        fi
        ;;

    tail)
        if [ -f "$LOG_DIR/api.stderr.log" ]; then
            tail -f "$LOG_DIR/api.stderr.log"
        else
            echo "No stderr log file found"
        fi
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|logs|tail}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the API server with watchdog (default)"
        echo "  stop    - Stop the API server"
        echo "  restart - Restart the API server"
        echo "  status  - Check if API server is running"
        echo "  logs    - Show recent watchdog logs"
        echo "  tail    - Follow API stderr log"
        exit 1
        ;;
esac