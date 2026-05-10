#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WEBUI_DIR="$PROJECT_DIR/webui"

echo "=== LlamaIndex Frontend Build ==="
echo "Project root: $PROJECT_DIR"
echo "WebUI dir: $WEBUI_DIR"
echo

if [ ! -d "$WEBUI_DIR" ]; then
    echo "Error: webui directory not found at $WEBUI_DIR"
    exit 1
fi

cd "$WEBUI_DIR"

if [ ! -f "package.json" ]; then
    echo "Error: package.json not found in $WEBUI_DIR"
    exit 1
fi

echo "[1/3] Installing dependencies..."
npm ci

echo
echo "[2/3] Building frontend..."
npm run build

echo
echo "[3/3] Build complete!"
echo "Output: $WEBUI_DIR/dist"
echo
echo "To serve the frontend via API, restart the API server:"
echo "  uv run llamaindex-study service restart"
echo
echo "Or to serve separately on port 5173:"
echo "  npm run preview -- --host"
