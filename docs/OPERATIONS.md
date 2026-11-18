# 部署与运维

## 环境变量

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `KOOK_TOKEN` | 机器人 Token（必填） | - |
| `KOOK_CHANNEL_ID` | 一次性发送测试的频道 ID（非必需） | - |
| `SQUAD_RADIO_LOG_DIR` | 日志目录 | 项目根 `logs/` |
| `SQUAD_RADIO_LOG_CONSOLE` | 终端输出 `on`/`off` | 自动检测 TTY |
| `SQUAD_RADIO_MAX_LOG_MB` | 日志目录总大小上限 MB | 50 |
| `SQUAD_RADIO_HEALTH_PORT` | 健康检查端口，不设则关闭 | - |

## 本地启动（Windows）

```
deploy.ps1                       # 一键部署：后台常驻，装依赖/找 token/等连接
deploy.ps1 -Status               # 状态：进程 + connected + 最新日志
deploy.ps1 -Logs                 # 最新日志尾部 40 行
deploy.ps1 -Stop                 # 停止
deploy.ps1 -Restart              # 重启
deploy.ps1 -Foreground           # 前台调试
deploy.ps1 -InstallAutoStart     # 登录时自动启动（计划任务 SquadRadio）
deploy.ps1 -UninstallAutoStart   # 取消自动启动

start.ps1                        # 仅前台启动
start.ps1 -CheckOnly             # 只检查环境
```
Token 放 `.env.token` 或设 `KOOK_TOKEN`；`deploy.ps1` 在两者都没有时会提示粘贴一次并写入 `.env.token`。
`start.ps1` 前台显式加 `--log-console on`；`deploy.ps1` 后台用 `--log-console off`，日志只进 `logs/`。
`deploy.ps1` 的 `-HealthPort` 默认 18082，`-MaxLogMb` 默认 50。

## CLI 启动

```bash
python -m squad_radio.cli kook-bot \
  --password-cache data/password_cache.json \
  --state-file data/kook_bot_state.json \
  --log-console auto \
  --log-dir logs \
  --max-log-mb 50 \
  --health-port 8080
```

常用自检命令：`kook-gateway`、`kook-channels --guild <ID>`、`kook-channel-view --channel <ID>`、`kook-send`、`preview`。

## 云端（systemd）

```ini
[Unit]
Description=Squad Radio KOOK Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/squad-radio
ExecStart=/opt/squad-radio/.venv/bin/python main.py
Environment=KOOK_TOKEN=你的token
Environment=SQUAD_RADIO_LOG_CONSOLE=off
Environment=SQUAD_RADIO_HEALTH_PORT=8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
`main.py` 用基于 `__file__` 的绝对路径定位数据/日志，不依赖工作目录。

## Docker

```bash
docker compose up -d --build
docker compose logs -f squad-radio
```
- 镜像以非 root `appuser` 运行，数据卷 `./data`、`./logs`。
- `KOOK_TOKEN` 从 `.env` 注入（`env_file`），`--env-file .env` 也行，**不要写进镜像**。
- compose 已配 healthcheck，探针打 `http://127.0.0.1:8080/healthz`。

## 健康检查

开启后（`SQUAD_RADIO_HEALTH_PORT=8080` 或 `--health-port 8080`）：

```
GET /healthz  →  200
{
  "status": "ok",              # 连上 WS = ok，否则 degraded
  "service": "squad-radio",
  "uptime_seconds": 123,
  "connected": true,
  "last_event_at": "...",
  "seconds_since_last_event": 42,
  "replies_sent": 7,
  "reconnects": 0,
  "timestamp": "..."
}
```
默认关闭，避免占用端口。容器/编排平台可据此配 liveness / readiness（注意 `degraded` 仍返回 200，如需自动重启可改 handler 返回 503）。

## 日志

- 始终写文件：`logs/squad-radio_<YYYYmmdd-HHMMSS>_<pid>.log`
- 前台自动同时打终端；后台只写文件。
- 目录总量超 `--max-log-mb`（默认 50）时按 mtime 删最早的，当前活跃文件保留；运行中每 5 秒检查一次。

## 优雅关闭

`SIGINT` / `SIGTERM` → `stop()` → WS 循环退出 → 保存 `sn/session_id` → 停健康检查 → 记录日志。
`Restart=always` 与 compose `restart` 依赖此机制，避免硬杀导致状态丢失。

## 排障

| 现象 | 排查 |
| --- | --- |
| 401「登录环境异常」 | Git Bash 把 token 里的 `/xxx` 当路径改写；命令前加 `MSYS_NO_PATHCONV=1` 或用 `--token-file` |
| `40107 Session expired` 循环 | 已自愈：清状态重连；若反复出现检查网络与 token 权限 |
| WS 连上但没回复 | 确认 `target_id` 是文字频道 ID；看日志是否收到 `s=0` 事件 |
| 密码是昨天的 | 上游未更新当天数据时会重试，不会拿旧密码冒充；稍后再问 |
| Windows 本地测优雅关闭用 `os.kill(pid, SIGTERM)` 无效 | Windows 上该调用走 `TerminateProcess`，绕过 Python 处理器；用 Ctrl+C（SIGINT）或直接 `bot.stop()` 验证。Linux/容器内 SIGTERM 正常 |
| `deploy.ps1` 等到 40s 仍 `connected=false` | 端点已起说明进程活着、在后台重试；看 `.\deploy.ps1 -Logs` 查 token 与网络。若连端点都没有，进程是启动即退出，改用 `.\deploy.ps1 -Foreground` 看报错 |
