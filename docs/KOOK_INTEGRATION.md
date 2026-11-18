# KOOK 接入要点

## 双通道模型

- **WebSocket**：只收事件、维持在线。不用来发消息。
- **HTTP REST**：发消息（`POST /api/v3/message/create`），有独立限速与每日配额。

## Gateway 连接流程

```
GET /api/v3/gateway/index?compress=0   →  wss 地址
WebSocket 连接
  ← HELLO  s=1, code=0, session_id     （6s 超时）
  → PING   s=2, sn                     （每 30±5s）
  ← PONG   s=3                         （6s 内必须收到，否则判超时重连）
  ← EVENT  s=0, sn
  → 记录 sn / session_id 到状态文件
断线：带 ?resume=1&sn=X&session_id=Y 重连
  ← s=6  RESUME ACK，离线消息补齐
  ← s=5  RECONNECT / 40107 / 40108 → 清状态，重新取 gateway
失败：指数回退 2/4/8/16... 秒，最大 60 秒
```
`compress=0`：服务端下发文本 JSON，无需自己解 zlib。

## 发消息

- 端点 `POST /api/v3/message/create`，`target_id` 必须是**文字频道 ID**（不是服务器 ID）。
- `type=9` 才是 KMarkdown；`(met)用户ID(met)` 的 @ 只有 KMarkdown 下生效。
- 每个开发者账号所有机器人**每日 10,000 条**，北京时间 12:00 重置。

## KMarkdown 能力

支持：加粗 `**`、行内代码 `` ` ``、引用 `>`、分隔线 `---`、@ `(met)id(met)`、剧透 `(spl)..(spl)`、emoji、fenced 代码块 ``` ``` ```。

不支持：内联图片 `![alt](url)`、原生表格。
- 密码表格因此用 fenced 代码块 + 按显示宽度补空格（中文算 2 列）实现。
- 图片若真需要，得先 `POST /api/v3/asset/create` 上传到 KOOK CDN 拿 `img.kookapp.cn` 链接（本项目已按要求不做图片）。

## 踩坑记录

| 坑 | 现象 | 解决 |
| --- | --- | --- |
| Git Bash 路径改写 | token 含 `/xxx` 被改成盘符路径，KOOK 统一返回 401「登录环境异常」 | `MSYS_NO_PATHCONV=1` 或 `--token-file`；CLI 会检测坏 token |
| 过期 session 死循环 | `40107 Session expired` 反复 resume | `_connect()` 识别 `s=5`/40107/40108，清状态用新 gateway 重连 |
| 每次启动的 session_id | HELLO 每次下发新 `session_id` | resume 只是可选增强；过期就丢弃重连 |
| 假图链接 | 某下载站返回 148MB 的 exe（MZ 头）诱饵 | 只用官方 CDN，勿信第三方图床 |
| 机器人自触发 | 自己发的消息又被当成触发 | `should_reply` 忽略 `author_id == 1`、bot 标记、自身 ID |

## 调试脚本

`scripts/kook_ws_probe.mjs`（Node）做完整 WS 探测：HELLO / PING / PONG / resume / 指数回退，含成功日志。需 Node 环境，非运行时依赖。
