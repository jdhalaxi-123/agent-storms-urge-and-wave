#!/usr/bin/env bash
# =====================================================================
#  stormsuregent 一键部署（Linux / macOS）
#  用法：bash deploy/setup_linux.sh
#        bash deploy/setup_linux.sh --mirror https://pypi.tuna.tsinghua.edu.cn/simple
#  做的事：找 Python3.9+ → 建 .venv → 装依赖 → 引导填 .env → 检查数据 → 启动
# =====================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT" || exit 1

MIRROR=""
SKIP_INSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mirror) MIRROR="$2"; shift 2 ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    *) shift ;;
  esac
done

C_OK="\033[32m"; C_WARN="\033[33m"; C_ERR="\033[31m"; C_INFO="\033[36m"; C_END="\033[0m"
say()  { printf "%b\n" "$1"; }
ok()   { printf "   ${C_OK}[OK]${C_END}   %s\n" "$1"; }
warn() { printf "   ${C_WARN}[注意]${C_END} %s\n" "$1"; }
bad()  { printf "   ${C_ERR}[失败]${C_END} %s\n" "$1"; }
step() { printf "\n${C_INFO}== [%s] %s ==${C_END}\n" "$1" "$2"; }

say ""
say "${C_INFO}================================================================${C_END}"
say "   风暴潮与海浪智能预报助手  ·  一键部署（Linux/macOS）"
say "${C_INFO}================================================================${C_END}"
say "   项目目录：$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"

# ------------------------------------------------------------------ #
step 1 "准备 Python 3.9+"
# ------------------------------------------------------------------ #
SYS_PY=""
for c in python3.10 python3.11 python3.12 python3.9 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "")
    if [ -n "$v" ]; then
      major=${v%%.*}; minor=${v##*.}
      if [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; then SYS_PY="$c"; PYVER="$v"; break; fi
    fi
  fi
done

if [ -z "$SYS_PY" ]; then
  bad "没有找到 Python 3.9+。请先安装，例如："
  say  "        Ubuntu/Debian:  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  say  "        CentOS/RHEL:    sudo yum install -y python3 python3-pip"
  say  "        macOS:          brew install python@3.10"
  exit 1
fi
ok "找到 Python $PYVER（$SYS_PY）"

# ------------------------------------------------------------------ #
step 2 "创建虚拟环境 .venv"
# ------------------------------------------------------------------ #
if [ -x "$PY" ]; then
  ok "已存在：$VENV"
else
  "$SYS_PY" -m venv "$VENV" || { bad "创建虚拟环境失败（Debian/Ubuntu 可能需要 sudo apt install python3-venv）"; exit 1; }
  ok "创建完成：$VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"

# ------------------------------------------------------------------ #
step 3 "安装依赖（约 1.5 GB，首次 5~20 分钟）"
# ------------------------------------------------------------------ #
if [ "$SKIP_INSTALL" -eq 1 ]; then
  warn "已指定 --skip-install，跳过依赖安装"
else
  python -m pip install --upgrade pip setuptools wheel -q --disable-pip-version-check || true

  if [ -n "$MIRROR" ]; then
    MIRRORS="$MIRROR"
  else
    MIRRORS="https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple https://pypi.org/simple"
  fi

  INSTALLED=0
  for m in $MIRRORS; do
    say "        使用源：$m"
    host=$(printf "%s" "$m" | sed -E 's#https?://([^/]+).*#\1#')
    if python -m pip install -r requirements.txt \
         --index-url "$m" --trusted-host "$host" \
         --timeout 60 --retries 2 --disable-pip-version-check; then
      INSTALLED=1; break
    fi
    warn "该源失败，换下一个源重试"
  done

  if [ "$INSTALLED" -ne 1 ]; then
    bad "依赖安装失败。netCDF4 在部分系统需要系统库："
    say  "        Ubuntu/Debian: sudo apt install -y libnetcdf-dev libhdf5-dev"
    exit 1
  fi
  ok "依赖安装完成"
fi

# ------------------------------------------------------------------ #
step 4 "配置 .env（密钥）"
# ------------------------------------------------------------------ #
ENV_FILE="$ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  ok ".env 已存在，跳过"
else
  [ -f "$ROOT/.env.example" ] && cp "$ROOT/.env.example" "$ENV_FILE" || touch "$ENV_FILE"
  say ""
  say "   请输入 DeepSeek API Key（形如 sk-xxxxxxxx，直接回车可跳过）"
  say "   获取地址：https://platform.deepseek.com"
  printf "   DeepSeek API Key: "
  read -r KEY || KEY=""
  if [ -n "$KEY" ]; then
    if grep -q '^[[:space:]]*DEEPSEEK_API_KEY=' "$ENV_FILE"; then
      sed -i.bak -E "s#^[[:space:]]*DEEPSEEK_API_KEY=.*#DEEPSEEK_API_KEY=$KEY#" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
    else
      printf "DEEPSEEK_API_KEY=%s\n" "$KEY" | cat - "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    fi
    ok "已写入 DEEPSEEK_API_KEY"
  else
    warn "未填密钥，请稍后编辑 $ENV_FILE"
  fi
fi

# ------------------------------------------------------------------ #
step 5 "检查数据目录"
# ------------------------------------------------------------------ #
DATA_DIR="${STORM_DATA_DIR:-$ROOT/data}"
if [ -d "$DATA_DIR" ]; then
  n=$(find "$DATA_DIR" -name '*.nc' 2>/dev/null | wc -l | tr -d ' ')
  ok "数据目录 $DATA_DIR，发现 $n 个 .nc 文件"
else
  warn "数据目录不存在：$DATA_DIR"
  say  "        不影响启动（会用骨架演示跑通链路），但没有真实预报数据。"
fi
mkdir -p "$ROOT/outputs"

# ------------------------------------------------------------------ #
step 6 "启动"
# ------------------------------------------------------------------ #
say ""
say "${C_OK}================================================================${C_END}"
say "   部署完成！以后启动： bash deploy/start_linux.sh"
say "   网页地址： http://localhost:7860"
say "${C_OK}================================================================${C_END}"
say ""
export PYTHONIOENCODING=utf-8
exec python "$ROOT/main.py"
