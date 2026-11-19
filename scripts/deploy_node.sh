#!/usr/bin/env bash
# 本机（Git Bash / macOS / Linux）执行：把 squad-radio 推到远端节点并部署。
#
#   ./scripts/deploy_node.sh            # 部署（默认 HOST/PORT 见下）
#   ./scripts/deploy_node.sh status     # 服务状态 + 健康检查
#   ./scripts/deploy_node.sh logs       # 最近 60 行日志
#   ./scripts/deploy_node.sh restart
#
# 覆盖参数：HOST / PORT / SSH_USER / SSH_KEY / APP_DIR / HEALTH_PORT
# KEEP_TOKEN=1：只更新代码，保留云端现有 .env.token（本地测试 token 与云端机器人不同时用）
# 走代理隧道（本地 14455 之类）：SSH_PROXY=socks5h://127.0.0.1:14455
#   HOST=1.2.3.4 PORT=2222 SSH_KEY=~/.ssh/team_ed25519 ./scripts/deploy_node.sh
set -euo pipefail

HOST="${HOST:-th-bkk02.altare.global}"
PORT="${PORT:-25736}"
SSH_USER="${SSH_USER:-root}"
APP_DIR="${APP_DIR:-/opt/squad-radio}"
SERVICE="${SERVICE:-squad-radio}"
HEALTH_PORT="${HEALTH_PORT:-18082}"
ACTION="${1:-deploy}"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SRC_DIR}"

SSH_OPTS=(-p "${PORT}" -o ConnectTimeout=15 -o ServerAliveInterval=15
          -o StrictHostKeyChecking=accept-new -o NumberOfPasswordPrompts=1)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "${SSH_KEY}")

# SSH_PROXY=socks5h://127.0.0.1:14455 / http://127.0.0.1:7890 / 127.0.0.1:1080
if [ -n "${SSH_PROXY:-}" ]; then
    PY_BIN="${PY_BIN:-$(command -v python3 || command -v python)}"
    [ -x "${PY_BIN}" ] || { printf '[deploy] 找不到 python，无法启用代理隧道\n' >&2; exit 1; }
    # 注意：Git Bash 的 TMPDIR 是 Windows 路径（C:\...），传给 sh 会被当成转义，这里固定用 /tmp
    WRAP="/tmp/squad_radio_proxy_$$.sh"
    printf '#!/bin/sh\nexec "%s" "%s" "$1" "$2"\n' "${PY_BIN}" "${SRC_DIR}/scripts/ssh_proxy.py" > "${WRAP}"
    chmod +x "${WRAP}"
    trap 'rm -f "${WRAP}"' EXIT
    SSH_OPTS+=(-o "ProxyCommand=${WRAP} %h %p")
fi

TARGET="${SSH_USER}@${HOST}"

say() { printf '\033[36m[deploy]\033[0m %s\n' "$*"; }
bad() { printf '\033[31m[deploy] %s\033[0m\n' "$*" >&2; }

remote() { ssh "${SSH_OPTS[@]}" "${TARGET}" "$@"; }

precheck() {
    say "检查 ${TARGET}:${PORT} 连通性"
    if ! remote "echo ok" >/dev/null 2>&1; then
        bad "SSH 连不上 ${TARGET}:${PORT}"
        bad "先确认节点已开机/在运行，端口没变，且你的密钥或密码可用："
        bad "  ssh ${SSH_USER}@${HOST} -p ${PORT}"
        exit 2
    fi
}

case "${ACTION}" in
    status)
        precheck
        remote "systemctl is-active ${SERVICE} 2>/dev/null; systemctl show -p ActiveEnterTimestamp,NRestarts ${SERVICE} 2>/dev/null | tr '\n' ' '; echo; curl -s --max-time 4 http://127.0.0.1:${HEALTH_PORT}/healthz || echo '(健康端点无响应)'"
        ;;
    logs)
        precheck
        remote "journalctl -u ${SERVICE} -n 60 --no-pager 2>/dev/null || tail -n 60 ${APP_DIR}/logs/*.log"
        ;;
    restart)
        precheck
        remote "systemctl restart ${SERVICE} && sleep 3 && systemctl is-active ${SERVICE}"
        ;;
    deploy)
        if [ "${KEEP_TOKEN:-0}" = "1" ]; then
            say "KEEP_TOKEN=1：保留云端现有 token，不覆盖"
            TOKEN=""
        else
            TOKEN="$(tr -d '\r\n' < .env.token 2>/dev/null || true)"
            if [ -z "${TOKEN}" ] && [ -z "${KOOK_TOKEN:-}" ]; then
                bad "本地没有 .env.token，也没有 KOOK_TOKEN 环境变量，无法部署"
                exit 1
            fi
        fi
        precheck

        say "打包源码并上传到 ${APP_DIR}"
        tar --exclude-vcs \
            --exclude='./.venv' --exclude='./data' --exclude='./logs' \
            --exclude='./.pytest_cache' --exclude='./.env.token' --exclude='./.env' \
            --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
            --exclude='*.log' --exclude='./config.toml' \
            -czf - . \
        | remote "mkdir -p '${APP_DIR}' && tar xzf - -C '${APP_DIR}' && sed -i 's/\r$//' '${APP_DIR}/scripts/remote_bootstrap.sh' '${APP_DIR}/scripts/deploy_node.sh'"

        if [ -n "${TOKEN}" ]; then
            say "写入 token 文件（600）"
            printf '%s' "${TOKEN}" | remote "umask 077; cat > '${APP_DIR}/.env.token'; chmod 600 '${APP_DIR}/.env.token'; wc -c < '${APP_DIR}/.env.token'"
        fi

        say "远端安装依赖并启动服务"
        remote "APP_DIR='${APP_DIR}' SERVICE='${SERVICE}' HEALTH_PORT='${HEALTH_PORT}' bash '${APP_DIR}/scripts/remote_bootstrap.sh'"
        ;;
    *)
        bad "未知动作：${ACTION}（可用：deploy | status | logs | restart）"
        exit 1
        ;;
esac
