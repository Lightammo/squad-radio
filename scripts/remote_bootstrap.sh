#!/usr/bin/env bash
# 在目标节点上以 root 执行（由 scripts/deploy_node.sh 上传并调用）。
# 职责：装基础依赖 -> 建 venv -> 装 Python 包 -> 写 systemd 单元 -> 启动 -> 等 KOOK 连上。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/squad-radio}"
SERVICE="${SERVICE:-squad-radio}"
HEALTH_PORT="${HEALTH_PORT:-18082}"
PY="${APP_DIR}/.venv/bin/python"
UNIT="/etc/systemd/system/${SERVICE}.service"

log()  { printf '[bootstrap] %s\n' "$*"; }
warn() { printf '[bootstrap] 警告：%s\n' "$*" >&2; }
die()  { printf '[bootstrap] 失败：%s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "需要 root 身份运行"
[ -f "${APP_DIR}/main.py" ] || die "${APP_DIR}/main.py 不存在，代码没上传成功？"

# ---------- 1. 系统依赖 ----------
if [ "${SKIP_PKGS:-0}" = "1" ]; then
    log "SKIP_PKGS=1，跳过系统包安装"
elif command -v apt-get >/dev/null 2>&1; then
    log "安装系统依赖（apt）"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null 2>&1 || warn "apt-get update 失败，继续尝试安装"
    apt-get install -y -qq python3 python3-venv python3-pip curl ca-certificates tar >/dev/null 2>&1 \
        || die "apt 安装 python3/venv 失败"
elif command -v dnf >/dev/null 2>&1; then
    log "安装系统依赖（dnf）"
    dnf install -y python3 python3-pip curl tar >/dev/null 2>&1 || die "dnf 安装失败"
elif command -v yum >/dev/null 2>&1; then
    log "安装系统依赖（yum）"
    yum install -y python3 python3-pip curl tar >/dev/null 2>&1 || die "yum 安装失败"
elif command -v apk >/dev/null 2>&1; then
    log "安装系统依赖（apk）"
    apk add --no-cache python3 py3-pip curl tar >/dev/null 2>&1 || die "apk 安装失败"
else
    warn "未知发行版，跳过包安装，直接使用已有 python3"
fi

command -v python3 >/dev/null 2>&1 || die "python3 仍不可用"
log "python: $(python3 -V 2>&1)"

# ---------- 2. 虚拟环境与依赖 ----------
if [ ! -x "${PY}" ]; then
    log "创建 venv：${APP_DIR}/.venv"
    python3 -m venv "${APP_DIR}/.venv" || die "python3 -m venv 失败（缺 python3-venv？）"
fi

log "安装 Python 依赖"
"${APP_DIR}/.venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || warn "升级 pip 失败，继续"
"${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt" >/dev/null 2>&1 \
    || "${APP_DIR}/.venv/bin/pip" install -q -i https://pypi.org/simple -r "${APP_DIR}/requirements.txt" \
    || die "pip 安装 requirements.txt 失败"
"${PY}" -c "import websocket; print('[bootstrap] websocket-client', websocket.__version__)"

# ---------- 3. 目录与 token ----------
mkdir -p "${APP_DIR}/data" "${APP_DIR}/logs"
if [ -s "${APP_DIR}/.env.token" ]; then
    chmod 600 "${APP_DIR}/.env.token"
    log "token 文件就绪：${APP_DIR}/.env.token"
elif [ -n "${KOOK_TOKEN:-}" ]; then
    umask 077
    printf '%s' "${KOOK_TOKEN}" > "${APP_DIR}/.env.token"
    log "token 已由环境变量写入"
else
    die "缺少 token：${APP_DIR}/.env.token 为空且未设置 KOOK_TOKEN"
fi

# ---------- 4. systemd 单元 ----------
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    log "写入 systemd 单元：${UNIT}"
    cat > "${UNIT}" <<EOF
[Unit]
Description=Squad Radio KOOK Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${PY} main.py
Environment=SQUAD_RADIO_LOG_CONSOLE=off
Environment=SQUAD_RADIO_LOG_DIR=${APP_DIR}/logs
Environment=SQUAD_RADIO_MAX_LOG_MB=50
Environment=SQUAD_RADIO_HEALTH_PORT=${HEALTH_PORT}
Environment=SQUAD_RADIO_HEALTH_HOST=127.0.0.1
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE}" >/dev/null 2>&1 || warn "enable 开机自启失败"
    systemctl restart "${SERVICE}"
    log "服务已启动：systemctl status ${SERVICE}"
    MODE=systemd
else
    warn "本机没有 systemd，改用 nohup + 自愈循环"
    pkill -f "${APP_DIR}/.venv/bin/python main.py" >/dev/null 2>&1 || true
    pkill -f "${APP_DIR}/run_forever.sh" >/dev/null 2>&1 || true
    cat > "${APP_DIR}/run_forever.sh" <<EOF
#!/bin/sh
# 进程挂了 10 秒后自动重启；容器重启后需要重新执行本脚本（无 systemd 环境）
cd "${APP_DIR}" || exit 1
export SQUAD_RADIO_LOG_CONSOLE=off
export SQUAD_RADIO_LOG_DIR="${APP_DIR}/logs"
export SQUAD_RADIO_MAX_LOG_MB=50
export SQUAD_RADIO_HEALTH_PORT=${HEALTH_PORT}
export SQUAD_RADIO_HEALTH_HOST=127.0.0.1
while true; do
    "${PY}" main.py
    echo "[\$(date '+%F %T')] main.py 退出（code \$?），10 秒后重启" >> "${APP_DIR}/logs/supervisor.log"
    sleep 10
done
EOF
    chmod +x "${APP_DIR}/run_forever.sh"
    setsid nohup "${APP_DIR}/run_forever.sh" >/dev/null 2>&1 &
    echo $! > "${APP_DIR}/.pid"
    log "已后台启动（自愈循环），supervisor pid $(cat "${APP_DIR}/.pid")"
    MODE=nohup
fi

# ---------- 5. 等待 KOOK 真正连上 ----------
log "等待健康检查（最多 60 秒）…"
ok=0
for _ in $(seq 1 30); do
    sleep 2
    out=$("${PY}" -c "
import json,urllib.request
try:
    d=json.load(urllib.request.urlopen('http://127.0.0.1:${HEALTH_PORT}/healthz',timeout=3))
    print('connected' if d.get('connected') else 'waiting', d.get('status'), d.get('reconnects'))
except Exception as e:
    print('down', type(e).__name__)
" 2>&1) || out="down"
    case "${out}" in
        connected*) log "健康检查通过：${out}"; ok=1; break ;;
    esac
done

if [ "${ok}" != "1" ]; then
    warn "60 秒内未连上 KOOK，下面是最近日志"
    if [ "${MODE}" = "systemd" ]; then
        journalctl -u "${SERVICE}" -n 40 --no-pager || true
    else
        tail -n 40 "${APP_DIR}"/logs/*.log 2>/dev/null || true
    fi
    exit 1
fi

log "部署完成：服务 ${SERVICE} 常驻，健康端点 127.0.0.1:${HEALTH_PORT}/healthz"
