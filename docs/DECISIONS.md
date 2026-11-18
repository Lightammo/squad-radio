# 关键技术决策

记录"为什么这么做"，避免后续重复讨论或踩坑。

## 为什么用等宽代码块做表格，而不是真的表格
KOOK KMarkdown 不支持原生表格语法。用 fenced 代码块 + 按显示宽度（`unicodedata.east_asian_width`，中文算 2 列）补空格，是稳定渲染、最接近 Excel 的方案。测试断言每行显示宽度一致。

## 为什么彻底去掉图片
用户明确"不支持图片就算了，不要图片了"。KMarkdown 不支持内联图片，缩略图机制要求链接文字与地址完全一致且依赖第三方图床防盗链。虽曾实现过程序化生成头图上传 KOOK CDN，但已全部移除，消息保持纯文字。

## 为什么 WebSocket 和 HTTP 分开
按 KOOK 官方模型：WS 收事件 / 保在线，REST 发消息。两者独立限速。发消息不依赖 WS 是否在线。

## 为什么 PasswordCache 按北京时间日期缓存
三角洲密码每天早上按日期更新。按 Asia/Shanghai 自然日缓存，跨 0:00 自动刷新；上游未更新时保留旧缓存并重试，**不会拿昨天密码冒充今天**（避免误导群友）。

## 为什么日志既写文件又打终端
后台/容器里 stdout 可能没人看或被截断，必须落盘；前台开发时需要即时看到。用两个 handler：FileHandler 始终挂，StreamHandler 仅在 TTY 或显式开启时挂。

## 为什么日志清理按目录总量而非单文件轮转
需求是"默认 50M，超过删最早的"。用自定义 Handler 定期扫描目录下本项目日志，按 mtime 删最旧直到达标，当前活跃文件永不删（避免删除正在写的句柄）。比 `RotatingFileHandler` 的单文件轮转更贴合"总量控制"。

## 为什么健康检查默认关闭
不是所有部署都有探针需求，默认占端口会干扰本地开发。通过 `SQUAD_RADIO_HEALTH_PORT` / `--health-port` 显式开启，Docker 镜像里默认设 8080。

## 为什么优雅关闭用 threading.Event
信号处理器里不能做复杂操作；`Event.set()` 是信号安全的。WS 循环轮询 event，`time.sleep` 换成 `event.wait` 让停止信号能立即唤醒，避免退出延迟。

## 为什么测试要用项目 venv 的解释器
系统 Python 未装 pytest；`python -m pytest` 会失败。用 `.venv/Scripts/python.exe -m pytest`。

## Token 安全红线
Token 只从环境变量 / `.env.token` / `.env` 读取。`.gitignore` 忽略 `.env.*`、`*.token`、`config.toml`、运行时数据。提交前用 `git grep --cached` 扫描密钥。Git Bash 里传含 `/` 的 token 必须 `MSYS_NO_PATHCONV=1` 或用 token 文件。

## 为什么 deploy.ps1 要自己给参数加引号
`Start-Process -ArgumentList` 传字符串数组时用空格拼接，且**不会**为含空格的元素加引号。本项目路径包含 `Program Files (x86)`，直接传数组会把 `--token-file I:\Program Files (x86)\...` 拆成多个参数，argparse 报错、进程启动即退出。所以先用 `ConvertTo-ArgString` 把含空格/引号的参数包上双引号，再以**单条命令行字符串**传给 `-ArgumentList`。

## 为什么 deploy.ps1 不用 -RedirectStandard*

PowerShell 5.1 在准备重定向时会复制环境变量到大小写敏感的字典；机器上同时存在 `HTTPS_PROXY` 与 `https_proxy` 时直接抛"已添加项"异常，进程根本起不来。程序自己写 `logs/` 日志文件，stdout/stderr 不是必需，所以放弃重定向；启动失败时引导用户用 `-Foreground` 查看原始报错。

## 为什么部署成功要等 connected=true

健康检查端点起来 ≠ 机器人上线：进程可能停在 WS 握手或重连阶段。只等 HTTP 200 会把"端口起来了但没连上 KOOK"误报为成功。`deploy.ps1` 轮询 `/healthz` 直到 `connected=true`（最多 40s），并区分两种失败：端点已起但未连接（后台继续重试，给出日志指引）与端点都没起（打印日志尾部并退出 1）。
