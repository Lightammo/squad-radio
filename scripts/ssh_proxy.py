"""SSH ProxyCommand 适配器：把 SSH 的 TCP 连接塞进 HTTP CONNECT / SOCKS5 代理。

用法（OpenSSH 会自己填 %h %p）：

    ssh -o ProxyCommand="python ssh_proxy.py %h %p" root@host -p 25736

代理地址取环境变量 SSH_PROXY，默认 socks5h://127.0.0.1:14455，支持：
    socks5://[user:pass@]host:port     本地解析域名
    socks5h://[user:pass@]host:port    交给代理解析（推荐）
    http://[user:pass@]host:port       HTTP CONNECT

自检模式（连上后打印服务端前若干字节，不发认证）：

    SSH_PROXY_PROBE=1 python ssh_proxy.py 目标 22
"""
from __future__ import annotations

import os
import socket
import struct
import sys
from urllib.parse import unquote, urlsplit


def _split_proxy(raw: str) -> tuple[str, int, int, str, str]:
    """返回 (scheme, host, port, user, password)。"""
    parts = urlsplit(raw if "://" in raw else "socks5h://" + raw)
    scheme = parts.scheme or "socks5h"
    return (
        scheme,
        parts.hostname or "127.0.0.1",
        parts.port or 1080,
        unquote(parts.username or ""),
        unquote(parts.password or ""),
    )


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("代理提前断开连接")
        buf += chunk
    return buf


def _socks5(sock: socket.socket, host: str, port: int, user: str, pwd: str, remote_dns: bool) -> None:
    methods = b"\x00\x02" if user else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise OSError(f"不是 SOCKS5 应答（ver={ver}）")
    if method == 0x02:
        u, p = user.encode(), pwd.encode()
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        if _recv_exact(sock, 2)[1] != 0:
            raise OSError("SOCKS5 用户名/密码认证失败")
    elif method != 0x00:
        raise OSError(f"代理不接受可用的认证方式（method={method}）")

    if remote_dns:
        name = host.encode()
        addr = b"\x03" + bytes([len(name)]) + name
    else:
        try:
            addr = b"\x01" + socket.inet_aton(socket.gethostbyname(host))
        except OSError:
            name = host.encode()
            addr = b"\x03" + bytes([len(name)]) + name
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))

    ver, rep, _, atyp = _recv_exact(sock, 4)
    if ver != 5:
        raise OSError(f"SOCKS5 应答版本异常（ver={ver}）")
    if rep != 0:
        reasons = {1: "代理内部错误", 2: "代理规则不允许", 3: "网络不可达", 4: "主机不可达",
                   5: "目标拒绝连接", 6: "TTL 过期", 7: "不支持的命令", 8: "不支持该地址类型"}
        raise OSError(f"SOCKS5 连接失败：{reasons.get(rep, f'code={rep}')}")
    if atyp == 1:
        _recv_exact(sock, 4)
    elif atyp == 3:
        _recv_exact(sock, _recv_exact(sock, 1)[0])
    elif atyp == 4:
        _recv_exact(sock, 16)
    _recv_exact(sock, 2)  # 绑定端口


def _http_connect(sock: socket.socket, host: str, port: int, user: str, pwd: str) -> None:
    import base64

    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if user:
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        req += f"Proxy-Authorization: Basic {token}\r\n"
    sock.sendall((req + "\r\n").encode())

    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)
        if not chunk:
            raise OSError("代理在 CONNECT 阶段断开")
        head += chunk
        if len(head) > 8192:
            raise OSError("代理应答过长")
    status = head.split(b"\r\n", 1)[0].decode("latin-1")
    if " 200" not in status:
        raise OSError(f"CONNECT 被拒绝：{status}")


def open_tunnel(host: str, port: int) -> socket.socket:
    scheme, phost, pport, user, pwd = _split_proxy(os.environ.get("SSH_PROXY", "socks5h://127.0.0.1:14455"))
    sock = socket.create_connection((phost, pport), timeout=30)
    sock.settimeout(None)
    if scheme.startswith("http"):
        _http_connect(sock, host, port, user, pwd)
    else:
        _socks5(sock, host, port, user, pwd, remote_dns=scheme.endswith("h"))
    return sock


def _pump(sock: socket.socket) -> None:
    """双向搬运 stdin/stdout 与 socket 的字节，直到任一端关闭。

    纯线程实现：Windows 的 select() 只能监听 socket，不能监听管道，
    所以这里不用 select。
    """
    import threading

    stdin_fd = sys.stdin.fileno()

    def stdin_to_sock() -> None:
        while True:
            try:
                data = os.read(stdin_fd, 65536)
            except OSError:
                data = b""
            if not data:
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                return
            try:
                sock.sendall(data)
            except OSError:
                return

    sender = threading.Thread(target=stdin_to_sock, name="stdin-to-sock", daemon=True)
    sender.start()

    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：python ssh_proxy.py <host> <port>", file=sys.stderr)
        return 2
    host, port = sys.argv[1], int(sys.argv[2])
    try:
        sock = open_tunnel(host, port)
    except OSError as exc:
        print(f"ssh_proxy: 连不上 {host}:{port} -> {exc}", file=sys.stderr)
        return 1

    if os.environ.get("SSH_PROXY_PROBE") == "1":
        sock.settimeout(12)
        try:
            data = sock.recv(128)
        except OSError as exc:
            print(f"ssh_proxy: 隧道已建立，但 12 秒内没收到任何数据（{exc}）", file=sys.stderr)
            return 3
        print(f"ssh_proxy: 隧道建立成功，服务端首包 {len(data)} 字节：{data[:60]!r}", file=sys.stderr)
        return 0

    _pump(sock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
