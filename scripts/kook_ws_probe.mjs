import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const token = process.env.KOOK_TOKEN;

if (!token) {
  console.error("请先设置环境变量 KOOK_TOKEN");
  process.exit(1);
}

const base = "https://www.kookapp.cn/api/v3";
const stateFile = "data/kook_ws_state.json";

function loadState() {
  try {
    if (!existsSync(stateFile)) return null;
    const state = JSON.parse(readFileSync(stateFile, "utf8"));
    if (state && state.session_id) return state;
  } catch {
    return null;
  }
  return null;
}

function saveState(state) {
  mkdirSync(dirname(stateFile), { recursive: true });
  writeFileSync(stateFile, JSON.stringify(state, null, 2), "utf8");
}

function clearState() {
  try {
    if (existsSync(stateFile)) writeFileSync(stateFile, "{}", "utf8");
  } catch {
    // ignore
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function heartbeatInterval() {
  return 30000 + Math.floor(Math.random() * 10000) - 5000;
}

async function getGateway(resumeState) {
  const res = await fetch(`${base}/gateway/index?compress=0`, {
    headers: { Authorization: `Bot ${token}`, Accept: "application/json" },
  });
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    const error = new Error(`gateway 返回非 JSON: ${text.slice(0, 300)}`);
    error.fatal = true;
    throw error;
  }
  if (body.code !== 0) {
    const error = new Error(`gateway 失败: code=${body.code} message=${body.message}`);
    error.fatal = true;
    throw error;
  }

  let url = body.data.url;
  if (resumeState && resumeState.session_id) {
    const parsed = new URL(url);
    parsed.searchParams.set("resume", "1");
    parsed.searchParams.set("sn", String(resumeState.sn || 0));
    parsed.searchParams.set("session_id", resumeState.session_id);
    url = parsed.toString();
    console.log(`resume 参数已附加: sn=${resumeState.sn || 0}`);
  }
  return url;
}

function connectOnce(resumeState) {
  return getGateway(resumeState).then(
    (url) =>
      new Promise((resolve) => {
        console.log("gateway ok, connecting websocket...");
        const ws = new WebSocket(url);
        let lastSn = resumeState?.sn || 0;
        let sessionId = resumeState?.session_id || null;
        let helloTimer;
        let pongTimer;
        let heartbeat;
        let settled = false;
        let reconnectRequested = false;
        let helloFailed = false;

        const finish = (reason) => {
          if (settled) return;
          settled = true;
          clearTimeout(helloTimer);
          clearTimeout(pongTimer);
          clearInterval(heartbeat);
          try {
            ws.close();
          } catch {
            // ignore
          }
          resolve({ reason, sn: lastSn, sessionId, reconnectRequested, helloFailed });
        };

        const startHeartbeat = () => {
          clearInterval(heartbeat);
          heartbeat = setInterval(() => {
            if (ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ s: 2, sn: lastSn }));
            console.log("PING sent, sn=", lastSn);
            clearTimeout(pongTimer);
            pongTimer = setTimeout(() => {
              console.error("PONG 超时：6 秒内未收到心跳回应");
              finish("pong_timeout");
            }, 6000);
          }, heartbeatInterval());
        };

        ws.onopen = () => {
          console.log("websocket open");
          helloTimer = setTimeout(() => {
            console.error("HELLO 超时：6 秒内未收到握手包");
            helloFailed = true;
            finish("hello_timeout");
          }, 6000);
        };

        ws.onmessage = (event) => {
          let message;
          try {
            message = JSON.parse(event.data);
          } catch {
            console.log("non-json frame", String(event.data).slice(0, 200));
            return;
          }

          if (typeof message.sn === "number") {
            lastSn = Math.max(lastSn, message.sn);
          }

          if (message.s === 1) {
            clearTimeout(helloTimer);
            if (message.d && message.d.code === 0) {
              sessionId = message.d.session_id || sessionId;
              saveState({ sn: lastSn, session_id: sessionId });
              console.log("HELLO ok, session ready");
              startHeartbeat();
            } else {
              console.error("HELLO failed", JSON.stringify(message.d));
              helloFailed = true;
              finish("hello_failed");
            }
            return;
          }

          if (message.s === 3) {
            clearTimeout(pongTimer);
            console.log("PONG ok");
            return;
          }

          if (message.s === 5) {
            reconnectRequested = true;
            console.error("RECONNECT requested", JSON.stringify(message.d));
            finish("reconnect");
            return;
          }

          if (message.s === 6) {
            sessionId = message.d?.session_id || sessionId;
            saveState({ sn: lastSn, session_id: sessionId });
            console.log("RESUME ACK, 离线消息已补齐");
            return;
          }

          if (message.s === 0) {
            saveState({ sn: lastSn, session_id: sessionId });
            console.log("EVENT", message.d?.type ?? "unknown", "sn=", message.sn);
            return;
          }

          console.log("signal", message.s, JSON.stringify(message).slice(0, 300));
        };

        ws.onerror = (event) => {
          console.error("websocket error", event.message || "unknown");
          finish("error");
        };

        ws.onclose = (event) => {
          if (!settled) finish(`closed:${event.code}`);
        };
      }),
  );
}

(async () => {
  let resumeState = loadState();
  let delay = 2000;

  for (;;) {
    try {
      const outcome = await connectOnce(resumeState);
      if (outcome.reconnectRequested || outcome.helloFailed) {
        clearState();
        resumeState = null;
      } else {
        resumeState = {
          sn: outcome.sn,
          session_id: outcome.sessionId,
        };
      }
      console.log(`连接结束(${outcome.reason})，${delay / 1000}s 后重试`);
    } catch (error) {
      if (error.fatal) {
        console.error(error.message);
        console.error("鉴权失败，停止重试。请检查 Token 或运行环境。");
        process.exit(1);
      }
      console.error(error.message);
    }

    await sleep(delay);
    delay = Math.min(delay * 2, 60000);
  }
})();
