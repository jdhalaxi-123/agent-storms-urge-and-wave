#!/usr/bin/env bash
# 启动（Linux/macOS）：bash deploy/start_linux.sh
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT" || exit 1

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "[错误] 还没有安装运行环境，请先执行： bash deploy/setup_linux.sh"
  exit 1
fi

echo "================================================================"
echo "   风暴潮与海浪智能预报助手"
echo "   网页地址：http://localhost:7860"
echo "   按 Ctrl+C 停止服务"
echo "================================================================"
export PYTHONIOENCODING=utf-8
exec "$ROOT/.venv/bin/python" "$ROOT/main.py"
