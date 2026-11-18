# Squad Radio 项目文档索引

> 本目录是给 AI agent / 新开发者看的**技术事实源**。用户-facing 说明见根目录 `README.md`。
> 文档随代码更新；改动架构、部署方式或关键决策时，请同步更新对应文档。

## 文档清单

| 文件 | 内容 | 什么时候读 |
| --- | --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 模块划分、数据流、类职责、扩展点 | 要改代码、加功能、理解结构时 |
| [STATUS.md](STATUS.md) | 当前已实现 / 未实现 / 已知限制 | 接手项目、评估能力边界时 |
| [OPERATIONS.md](OPERATIONS.md) | 本地启动、云端部署、Docker、日志、健康检查、优雅关闭 | 部署 / 运维 / 排障时 |
| [KOOK_INTEGRATION.md](KOOK_INTEGRATION.md) | KOOK WS/REST 协议要点、KMarkdown、踩坑记录 | 改 KOOK 接入、排查连接问题时 |
| [DECISIONS.md](DECISIONS.md) | 关键技术决策与原因（避免重复踩坑） | 想改方案、质疑现有做法时 |
| [AGENT_GUIDE.md](AGENT_GUIDE.md) | 给 agent 的开发约定：测试命令、环境变量、禁止事项 | 开始任何开发任务前 |

## 30 秒速览

- **产品**：三角洲·战地播报 / Squad Radio，常驻 KOOK 群的主动型播报机器人。
- **核心已上线功能**：任意频道喊「今日密码」→ 立即同频道 @ 回复一张表格；按北京时间每日缓存、跨零点刷新；建筑师人格语气。
- **技术栈**：Python 3.11+，标准库 + `websocket-client` + SQLite + pytest，无 Web 框架。
- **双通道**：WebSocket 收事件 / 保在线，HTTP REST 发消息。
- **入口**：`python main.py`（云端/Docker）、`python -m squad_radio.cli kook-bot`（CLI）、`start.ps1`（Windows 本地）。
- **测试**：`python -m pytest -q`（需用项目 `.venv` 的解释器）。

## 安全红线

Token 只能来自环境变量或本地文件，**绝不写进代码、文档或提交到 git**。`git grep` 扫描通过后再提交。
