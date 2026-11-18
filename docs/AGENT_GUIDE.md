# Agent 开发约定

给 AI agent / 协作者的可操作约定，开始任务前先读。

## 环境

- 项目根：`squad-radio/`，Python 3.11+，虚拟环境 `.venv`。
- 装依赖：`python -m pip install -e . && python -m pip install pytest`（默认镜像缺包时用 `-i https://pypi.org/simple`）。
- **跑测试必须用 `.venv/Scripts/python.exe -m pytest -q`**，系统 Python 没有 pytest。

## 改代码前

1. 读 `docs/README.md` 找对应文档，读 `docs/STATUS.md` 确认能力边界。
2. 区分两条链路：改「今日密码」在线行为 → `kook_bot.py`；改通用播报规则 → `engine.py` / `rules.py`。两者独立。
3. 涉及 KOOK 协议改动，先看 `docs/KOOK_INTEGRATION.md` 的踩坑记录。

## 改代码后

- 跑全量测试，确保全绿。
- 改了架构 / 部署 / 决策，同步更新 `docs/` 对应文件（尤其 `STATUS.md` 和 `DECISIONS.md`）。
- 消息格式改动用 `python -m squad_radio.cli preview` 本地预览，不要往真实群发测试消息。

## 安全红线（违反会造成事故）

- **绝不**把 KOOK token 写进代码、测试、文档、README 或提交。
- **绝不**提交 `.env`、`.env.token`、`config.toml`、`data/*.json`、日志。
- 提交前 `git grep --cached -n '1/'` 之类扫描敏感串。
- Git Bash 里处理 token：命令前加 `MSYS_NO_PATHCONV=1`，或用 `--token-file`。

## 常见任务速查

| 任务 | 入口 |
| --- | --- |
| 加一条播报规则 | `rules.py` 继承 `Rule`，注册到 `default_rules()`，加测试 |
| 改人格台词 | `persona.py` 的 `_OPENINGS` / `_SUFFIXES` |
| 改密码表格样式 | `rich.py::format_password_table` |
| 改触发词 | `kook_bot.py` 的 `trigger` 参数（默认"今日密码"） |
| 加环境变量 | `main.py` 的 `_log_*` / `_health_port` + `cli.py` 参数 + `.env.example` + `docs/OPERATIONS.md` |
| 改日志清理策略 | `log_setup.py::cleanup_old_logs` / `_CleaningFileHandler` |
| 加健康检查字段 | `health.py::HealthState` |

## 不要做的事

- 不要往群里发真实测试消息（会打扰群友），除非用户明确要求。
- 不要引入重型 Web 框架 / ORM；项目刻意保持标准库为主。
- 不要恢复图片方案（用户已明确不要）。
- 不要把订阅指令逻辑误接到错误的链路（见 `ARCHITECTURE.md` 的两条链路）。
