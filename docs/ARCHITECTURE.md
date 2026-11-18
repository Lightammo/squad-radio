# 架构说明

## 分层

```
数据源 / KOOK WS 事件
        │
        ▼
┌─────────────────────────────────────────────┐
│ 接入层                                       │
│  - kook_bot.py    常驻 WS，监听「今日密码」   │
│  - kook.py        KOOK REST 客户端 + 广播器   │
│  - cli.py         命令行入口                  │
│  - main.py        云端/Docker 入口            │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 领域层                                       │
│  - engine.py      RadioEngine + 噪声控制      │
│  - rules.py       4 类触发规则                │
│  - persona.py     建筑师人格语气              │
│  - rich.py        KMarkdown 排版（含密码表格）│
│  - password.py    每日密码缓存与双源校验       │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 基础设施层                                   │
│  - config.py      TOML 配置 + 北京时间        │
│  - storage.py     SQLite 订阅/状态/去重       │
│  - log_setup.py   日志落盘 + 50MB 清理        │
│  - health.py      可选 HTTP 健康检查端点      │
└─────────────────────────────────────────────┘
```

## 两条独立链路

项目里有**两条并行的消息链路**，不要混淆：

1. **通用播报链路（引擎）**：`Event → RadioEngine.process() → rules → persona → broadcaster`。
   支持物价异动 / 大红 / 每日密码事件 / 特勤处完工，带去重、每日上限、免打扰。
   目前通过 `demo` / `ingest-jsonl` 喂数据，**尚未接真实 KOOK 事件流**。

2. **今日密码常驻链路（已上线）**：`KookBot`（WS 监听）→ `build_reply()` → `format_password_table()` → `KookClient.send_message()`（REST）。
   这是当前真正在群里跑的功能，与上面的引擎是**独立实现**。

> 注意：群里发「订阅/退订/免打扰」等指令时，`RadioEngine.handle_command()` 已实现逻辑，但 `KookBot` 目前只识别「今日密码」，**没有把其他指令挂到 WS 入口**。

## 关键类职责

| 模块 | 类/函数 | 职责 |
| --- | --- | --- |
| `kook_bot.py` | `KookBot` | WS 常驻：握手、心跳、resume、优雅关闭、状态更新、触发回复 |
| `kook_bot.py` | `should_reply` | 纯函数判断是否触发（真人、非 bot、含触发词） |
| `kook_bot.py` | `build_reply` | 组装回复：@ + ❤️ + 标题 + 表格 + 彩蛋 + 脚注 |
| `password.py` | `PasswordCache` | 按北京时间日期缓存，主源 JSON / 备源文本，跨零点刷新 |
| `rich.py` | `format_password_table` | 等宽代码块表格，中文按 2 列补齐 |
| `persona.py` | `ArchitectPersona` | 按语义选语气，包装文案 |
| `log_setup.py` | `configure_logging` | 文件 handler（始终）+ 终端 handler（前台），启动时 + 运行中清理旧日志 |
| `health.py` | `HealthServer` / `HealthState` | 可选 HTTP 探针，暴露连接态/运行时长/回复数 |

## 数据流：一次「今日密码」触发

```
群友消息 → WS s=0 事件 → should_reply() 判定
   → handle_event(): state.mark_event()
   → cache.get()（当天缓存，不重复打上游）
   → build_reply(): mention + ❤️ + 表格 + 人格脚注
   → KookClient.send_message(channel, content, type=9)
   → state.mark_reply() → 记录日志
```

## 扩展点

- **接新的播报数据源**：实现 `sources.py` 的 poll 接口，产出 `Event` 喂给 `RadioEngine.process()`。
- **把指令挂到 KOOK**：在 `KookBot.should_reply` / `handle_event` 里分流文本，调用 `RadioEngine.handle_command()`。
- **新的人格风格**：`persona.py` 加 Tone 与台词，配置 `persona.style`。
- **新平台**：实现 `broadcasters.py` 的 `Broadcaster`；QQ 可走 Webhook。
