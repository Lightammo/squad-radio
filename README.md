# 三角洲·战地播报（Squad Radio）

> 一个常驻 QQ/KOOK 群的主动型播报机器人——不等 `@`，只在"值得说话的时刻"开口。
> 底层是一套与平台解耦的触发引擎，可以看作未来 AstrBot / QQ / KOOK 插件的"大脑"。

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> ⚠️ **声明**：本项目由 AI 助手 **WorkBuddy** 生成，包含代码、文档、测试用例与示例数据。**内容请自行分辨与核实**，不保证完全准确、可靠或适用于生产环境；使用前请审阅关键逻辑、确认第三方数据源授权，并妥善保管 Token。

## 它解决什么问题

现有的三角洲插件（DeltaUID、AstrBot 三角洲插件等）都是**你问它答**：要先输入 `ss战绩`、`日报`、`ss价格` 才有响应。Squad Radio 反过来——**它替你盯着数据，有事才说话**。

```
数据源 → 触发条件引擎 → 噪声控制 → 播报编排 → 控制台 / Webhook / KOOK
   ↑                                                   │
   └──────────── 订阅偏好库（SQLite） ←── 群内指令 / 回复 ─┘
```

三个核心场景：

| 模块 | 类型 | 说明 |
| --- | --- | --- |
| 大红 / 高价值物资播报 | 社交货币 | 出大红自动播报并 `@` 出红者，把个人成就变成群内公共事件 |
| 物价异动预警 | 实用决策 | 关注物品 + 阈值 + 窗口，触发即播报，从"查价"变成"价格来找你" |
| 每日密码 + 特勤处提醒 | 习惯锚定 | 早八作战简报 + 制造完成 `@` 本人，养成"看群就知道今天干嘛" |

机器人的人格设定是《少女前线》**铁血工造·建筑师**：所有播报和回复会按语义自动带上"指挥官""嘻嘻""呢""哦""超——幸运""加倍"等口癖，而不是无脑贴尾巴。

## 已实现能力

- **规则引擎**
  - 物价异动：按物品、涨幅阈值、时间窗口触发
  - 大红播报：按估值阈值触发，自动 `@` 出红者
  - 每日密码 / 特勤处完成：事件驱动播报
- **噪声控制**（防止机器人从"有趣"变成"被禁言"）
  - 同事件去重窗口、每群每日播报上限、免打扰时段
  - 高优先级事件（如大红）可穿透限制
  - 用户 / 群退订
- **订阅闭环**
  - `订阅 钛合金 15 30`、`退订 钛合金`、`免打扰` / `取消免打扰`
- **KOOK 常驻机器人**
  - WebSocket 长连接保持在线，监听所有所在频道
  - 任何人说「今日密码」→ 立即同频道回复并 `@` 提问人
  - 密码按北京时间每日缓存，跨 0:00 自动刷新，双数据源校验
- **建筑师人格层**
  - 按事件语义选语气：出红/问候用幸运台词，物价用提醒语气，错误用"图纸对不上"式道歉
  - 强度可配：`off` / `light` / `normal` / `full`

## 快速开始

```bash
git clone https://github.com/Lightammo/squad-radio.git
cd squad-radio

python -m venv .venv
source .venv/Scripts/activate          # Windows Git Bash
# source .venv/bin/activate            # macOS / Linux

python -m pip install -r requirements.txt
# 若默认镜像找不到包，可换官方源：
# python -m pip install -i https://pypi.org/simple -r requirements.txt
python -m pip install --no-deps -e .

python -m squad_radio.cli demo         # 看四类播报效果
python -m pytest -q                    # 运行测试
```

`demo` 会注入示例事件，直接展示物价异动、大红、每日密码、特勤处完成四类播报。

## 一键部署（Windows）

不想记命令就用一个脚本，它把「装环境 → 找 token → 停旧实例 → 后台启动 → 等 KOOK 连上」全做完：

```powershell
.\deploy.ps1                       # 一键部署（后台常驻，健康检查端口默认 18082）
.\deploy.ps1 -Status               # 进程 / 连接状态 / 最新日志
.\deploy.ps1 -Logs                 # 看最新日志尾部 40 行
.\deploy.ps1 -Restart              # 重启
.\deploy.ps1 -Stop                 # 停止
.\deploy.ps1 -Foreground           # 前台运行，报错直接可见
.\deploy.ps1 -InstallAutoStart     # 注册"登录时自动启动"（计划任务 SquadRadio）
.\deploy.ps1 -UninstallAutoStart   # 取消自动启动

# 被执行策略拦截时
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

它会自动处理这些事：

- 没有 `.venv` 就创建，缺依赖就按 `requirements.txt` 安装
- token 依次读 `KOOK_TOKEN` → `.env.token`；都没有就提示粘贴一次（输入隐藏），写入被 git 忽略的 `.env.token`
- 启动前先停掉已在跑的实例，保证单实例
- 后台隐藏运行，不占终端窗口，日志只写 `logs/`
- **等到健康检查返回 `connected=true` 才算成功**，否则打印日志尾部并给出下一步提示

可选参数：`-HealthPort 18082`（健康检查端口，`0` 关闭）、`-MaxLogMb 50`（日志总量上限）。

`start.ps1` 仍保留，用于纯前台调试（`start.ps1 -CheckOnly` 只检查环境）。

## 配置

复制 `config.example.toml` 为 `config.toml` 后按需修改（`config.toml` 已被 `.gitignore` 忽略）：

```bash
cp config.example.toml config.toml
python -m squad_radio.cli demo --config config.toml
```

| 配置项 | 含义 |
| --- | --- |
| `noise.daily_cap` | 每群每日主动播报上限 |
| `noise.dedupe_minutes` | 同一事件键的去重窗口 |
| `noise.quiet_hours` | 免打扰时段，如 `01:00-07:30` |
| `noise.high_priority_passthrough` | 可穿过上限/免打扰的优先级 |
| `defaults.price_threshold_pct` | 默认涨幅阈值 |
| `defaults.red_min_value_wan` | 大红最低估值（万） |
| `persona.enabled` | 是否启用建筑师人格 |
| `persona.intensity` | 人格强度：`off` / `light` / `normal` / `full` |
| `persona.address` | 对群友的称呼，默认"指挥官" |

人格层示例（不同事件语义对应不同语气）：

```text
出红：指挥官，我真是超——幸运呢！@someone 的长弓溪谷之旅不太一样…… 这波施工记录我记下了哦。
物价：指挥官，行情图纸刷新了哦。钛合金 涨了 18% …… 建议先看一眼再施工哦。
密码：早八施工简报，指挥官请查收哦。今日作战密码：8865 ……
问候：嘻嘻，指挥官，好久不见哦！我们又相遇了呢。这可是加倍的幸运哦！
错误：指挥官，图纸对不上呢……格式：订阅 物品 [涨幅阈值] 请核对一下参数呢。
```

## 命令一览

```bash
python -m squad_radio.cli init-db                       # 初始化 SQLite
python -m squad_radio.cli demo                          # 演示完整链路
python -m squad_radio.cli ingest-jsonl --path data/events.example.jsonl
python -m squad_radio.cli command --group demo --user 10001 --text "订阅 钛合金 12 30"
python -m squad_radio.cli status                        # 查看本地状态

# KOOK 连通性自检
python -m squad_radio.cli kook-gateway
python -m squad_radio.cli kook-channels --guild <服务器ID>
python -m squad_radio.cli kook-send --channel <文字频道ID> --text "测试"

# 常驻监听「今日密码」并 @ 回复（日志写入 logs/，前台运行时同时打印到终端）
python -m squad_radio.cli kook-bot \
  --password-cache data/password_cache.json \
  --state-file data/kook_bot_state.json
#   --log-console on|off   # 强制打开/关闭终端输出，默认 auto 自动检测
#   --log-dir /path/logs   # 自定义日志目录
#   --max-log-mb 50        # 日志目录总大小上限(MB)，超过删最早的

# Windows 一键部署（后台常驻，自动装依赖/找 token/等 KOOK 连上）
.\deploy.ps1
.\deploy.ps1 -Status                   # 状态；另有 -Logs / -Stop / -Restart
.\deploy.ps1 -InstallAutoStart         # 登录时自动启动
# 若被执行策略拦截：powershell -ExecutionPolicy Bypass -File .\deploy.ps1

# 纯前台调试启动
.\start.ps1
.\start.ps1 -CheckOnly                 # 只检查环境，不启动
# 若被执行策略拦截：powershell -ExecutionPolicy Bypass -File .\start.ps1
```

JSONL 事件格式（每行一个事件）：

```json
{"type":"price_snapshot","subject":"钛合金","value":8.2,"group_id":"demo"}
{"type":"red_drop","subject":"曼德尔超算单元","value":280,"group_id":"demo","user_id":"10001","payload":{"map":"长弓溪谷"}}
{"type":"daily_password","subject":"2026-11-18","group_id":"demo","payload":{"password":"8865"}}
{"type":"task_completed","subject":"特勤处制造","group_id":"demo","user_id":"10002"}
```

## KOOK 接入

### Token 安全

Token **只从环境变量或文件读取**，永远不要写进代码或提交到仓库。仓库已通过 `.gitignore` 忽略 `.env.*`、`*.token`、`config.toml` 和所有运行时数据。

```bash
# Git Bash / MSYS 环境：必须加 MSYS_NO_PATHCONV=1，否则 token 里的 /xxx 会被当成路径改写
MSYS_NO_PATHCONV=1 KOOK_TOKEN='你的机器人 Token' python -m squad_radio.cli kook-gateway

# PowerShell / 其他终端：直接设置即可
$env:KOOK_TOKEN = "你的机器人 Token"
```

更稳妥的方式是把 token 写进一个未提交的文件，用 `--token-file` 传入：

```bash
python -m squad_radio.cli kook-gateway --token-file .env.token
```

CLI 会检测被 Git Bash 改写的 token 并直接报错，不会拿坏 token 去请求。

### 双通道模型

KOOK 的 WebSocket 和 HTTP 是两条独立通道：

- **WebSocket**：只负责**接收事件**（群友消息），并维持机器人在线态。心跳 `PING {s:2,sn}` 每 30±5 秒，6 秒内必须收到 `PONG`，断线用 `sn + session_id` resume。
- **HTTP REST**：负责**发送消息**（`POST /api/v3/message/create`），不依赖 WS 是否在线，有独立限速和每日配额。

```text
GET gateway(compress=0) → WebSocket → HELLO(s=1,code=0)
→ PING/PONG 心跳 → 记录 sn/session_id → 断线 resume（s=6 确认补齐）
→ 收到 s=5 清状态重连 → 失败 2/4/8/16... 秒指数回退（最大 60 秒）
```

`compress=0` 表示服务端下发文本 JSON，无需自行解 zlib。发消息必须用 KMarkdown（`type=9`）才能让 `(met)用户ID(met)` 的 `@` 生效。

> 提示（来自官方 `kaiheila/api-docs`）：`message/create` 的 `target_id` **必须是文字频道 ID，不是服务器 ID**。每个开发者账号所有机器人每日发送上限 10,000 条，北京时间 12:00 重置。

### 今日密码监听

启动后机器人保持 WS 在线，监听所有所在频道；任何真人消息只要包含触发词（默认"今日密码"），立即在**同一频道**回复并 `@` 提问人。机器人自己和其他 bot 的消息会被忽略，避免循环。

密码缓存逻辑：

- 按北京时间日期存到 `data/password_cache.json`（已被 `.gitignore` 忽略）
- 启动时拉取当天密码；当天所有回复只读缓存，不再打上游
- 跨 0:00 自动刷新；上游尚未更新时保留旧缓存并重试，**不会拿昨天的密码冒充今天**
- 主源：`db.18183.com` 结构化 JSON（校验日期与六图完整性）；备源：`tmini.net` 文本接口

### 消息美化（KMarkdown 富文本）

所有发到 KOOK 的消息都经过 `squad_radio/rich.py` 排版，用官方文档支持的 KMarkdown 语法，而不是干巴巴的一行文字：

- **今日密码表格**：KOOK KMarkdown 没有原生表格语法，所以用等宽代码块画出表格；按显示宽度补齐空格，中文地图名与数字密码列对齐不乱
- **结构化排版**：加粗标题 + 分隔线 + 引用脚注
- **@ 提问人**：用 KOOK 原生 `(met)用户ID(met)` 语法，真实触发提醒
- **彩蛋**：用剧透语法 `(spl)...(spl)` 藏一句可点开的俏皮话，不占正文
- **建筑师语气**：脚注仍由人格层生成，「指挥官 / 施工简报 / 请查收哦」照旧

> 说明：KOOK KMarkdown 不支持 `![图](url)` 内联图片语法，所以消息保持纯文字卡片，避免用第三方图床时的防盗链问题。

当前密码消息的实际效果：

````text
(met)用户ID(met) **今日作战密码 · 2026-11-18**
```
地图      密码
--------  ----
零号大坝  8865
长弓溪谷  4565
巴克什    6468
航天基地  8572
潮汐监狱  2161
AZ3       2430
```
(spl)记不住没关系，随时在群里喊「今日密码」(spl)         ← 点击展开
---
> 早八施工简报，指挥官请查收哦。数据每天早上更新，以游戏内为准哦。
````

本地预览（不发送）：

```bash
python -m squad_radio.cli preview
```

调整美化程度（改 `squad_radio/rich.py` 的 `RichStyle`）：`show_splash` 关彩蛋、`show_actions` 关快捷指令提示。

## 日志

日志始终写入项目根目录下的 `logs/`，即使作为后台进程静默运行也不会丢记录：

```text
logs/squad-radio_20261118-223005_4321.log
       └─项目名  └─启动时间戳   └─进程ID
```

- **后台运行**：只写文件，`stdout` 没有输出。
- **前台运行**：自动检测交互式终端，文件 + 终端同时输出。
- **自动清理**：`logs/` 目录总大小默认上限 **50MB**，超过就按修改时间删除最早的文件（当前正在写的日志始终保留）。运行中每 5 秒检查一次，启动时也会先清一遍历史堆积。
  - CLI：`--max-log-mb 50` 调整上限，`--log-dir` 改目录。
  - 云端入口 `main.py`：环境变量 `SQUAD_RADIO_MAX_LOG_MB=50`、`SQUAD_RADIO_LOG_DIR=/path/logs`。
- 可用 `--log-console on|off` 强制开关终端输出，云端入口 `main.py` 自动检测，也可设环境变量 `SQUAD_RADIO_LOG_CONSOLE=on|off` 控制。

日志文件已被 `.gitignore` 忽略，不会提交到仓库。

## 部署到服务器

### Windows 一键部署（推荐）

双击 `一键部署远端.cmd`，或在本目录用 PowerShell 运行：

```powershell
.\deploy_remote.ps1                  # 部署到云端节点（默认动作）
.\deploy_remote.ps1 -Action status   # 状态 + 健康检查
.\deploy_remote.ps1 -Action logs     # 最近日志
.\deploy_remote.ps1 -Action restart  # 重启服务
```

它替你封装了远端部署脚本和所有参数，重点是**安全默认值**：

- **默认 `KEEP_TOKEN=1`**：只更新代码，不覆盖云端正在用的机器人 token（本地 `.env.token` 通常是另一个测试机器人）。确实要替换时加 `-WithToken`。
- **默认走本地代理隧道** `socks5h://127.0.0.1:14455`（直连节点会被丢包）；换代理用 `-Proxy`，直连用 `-NoProxy`。
- 自动定位 Git for Windows 的 `bash.exe`（避开 WSL 占位程序），并固定用项目 venv 的 python 驱动代理隧道。
- 部署后自动等到 KOOK 真正连上才返回。脚本会先找 Git Bash；若检测失败可用 `-BashPath` 指定。

> 想让远端跑 GitHub 上的最新代码，先 `git push`，再执行上面的部署。

### 一条命令部署（任意外网 Linux 主机 / 跨平台）

本机（Git Bash / macOS / Linux）执行，脚本会打包上传、装依赖、建 venv、写 systemd 单元、启动并**等到 KOOK 真正连上**才返回：

```bash
./scripts/deploy_node.sh                    # 部署到默认节点（见脚本顶部 HOST/PORT）
./scripts/deploy_node.sh status             # 服务状态 + 健康检查
./scripts/deploy_node.sh logs               # 最近 60 行日志
./scripts/deploy_node.sh restart

# 换机器 / 换端口 / 换密钥
HOST=1.2.3.4 PORT=2222 SSH_KEY=~/.ssh/team_ed25519 ./scripts/deploy_node.sh

# 直连被墙（TCP 超时）时走本地代理隧道，支持 socks5/socks5h/http
SSH_PROXY=socks5h://127.0.0.1:14455 ./scripts/deploy_node.sh
```

- 代码落在 `/opt/squad-radio`，服务名 `squad-radio`，健康端点只监听 `127.0.0.1:18082/healthz`。
- Token 从本机 `.env.token` 读取，远端写成 `/opt/squad-radio/.env.token`（600），不进 tar 包。
- 远端没有 systemd（裸容器）时自动改用 `run_forever.sh` 自愈循环：进程异常退出 10 秒后拉起，但**容器重启后需重新执行一次部署脚本**。
- 代理隧道由 `scripts/ssh_proxy.py` 提供（纯标准库实现 HTTP CONNECT / SOCKS5，可直接当 SSH 的 `ProxyCommand`）。

### 手动部署

以一台装好 Python 3.11+ 的 Linux 服务器为例：

```bash
# 1. 拉代码 & 装依赖
git clone https://github.com/Lightammo/squad-radio.git
cd squad-radio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 把 token 放进受保护文件（不要进 git）
printf '%s' '你的机器人Token' > .env.token
chmod 600 .env.token

# 3. 先用 systemd 托管常驻服务
sudo tee /etc/systemd/system/squad-radio.service > /dev/null <<'EOF'
[Unit]
Description=Squad Radio KOOK Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/squad-radio
ExecStart=/path/to/squad-radio/.venv/bin/python -m squad_radio.cli kook-bot \
  --token-file /path/to/squad-radio/.env.token \
  --password-cache data/password_cache.json \
  --state-file data/kook_bot_state.json
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now squad-radio
sudo journalctl -u squad-radio -f       # 看日志
```

> 服务器若是国内线路且 KOOK API 可达性不稳定，可按需配置代理；`websocket-client` 与 REST 均使用系统网络栈。

## 目录结构

```text
squad-radio/
├── .env.example              # 环境变量模板
├── deploy.ps1                # Windows 一键部署（后台常驻 + 状态/停止/日志/自启）
├── start.ps1                 # Windows 前台启动脚本
├── config.example.toml       # 配置模板
├── pyproject.toml
├── requirements.txt
├── data/
│   └── events.example.jsonl  # 示例事件（运行时数据均被忽略）
├── scripts/
│   └── kook_ws_probe.mjs     # Node 版 WebSocket 探测脚本
├── squad_radio/
│   ├── cli.py                # 命令行入口
│   ├── config.py             # 配置加载与本地时区
│   ├── engine.py             # 引擎、噪声控制、指令处理
│   ├── kook.py               # KOOK REST API 与播报适配器
│   ├── kook_bot.py           # 常驻监听：今日密码即触发并 @ 回复
│   ├── models.py             # Event / Broadcast 数据模型
│   ├── password.py           # 每日密码缓存与数据源校验
│   ├── persona.py            # 建筑师人格层与语义语气选择
│   ├── rich.py               # KMarkdown 纯文字富文本排版
│   ├── rules.py              # 触发规则与文案模板
│   ├── sources.py            # 数据源适配器
│   ├── storage.py            # SQLite 存储
│   └── broadcasters.py       # 输出适配器
└── tests/
```

## 下一步

- 接入 AstrBot 插件入口，把 `RadioEngine.process()` 挂到定时 / 事件回调
- 用真实价格流与出红事件流替换 `MockSource`
- 增加播报"价值分"与 A/B 文案模板
- 增加每群消息占比、订阅转化、退订率指标看板

## 数据说明

免费开源的 `DeltaForcePrice` 价格库已于 2026-01-11 停止更新，不能作为生产数据源。生产使用请先确认数据授权与更新粒度（数据帝开放平台的低价价格接口约 40 分钟一次，若需分钟级异动需另寻数据源）。

## License

MIT
