"""09 集成：MCP Client（蓝图 09 mcp_client 段，复用 zhao/mcp/client.py 移植）。

JSON-RPC 2.0 完整客户端，双传输（stdio 子进程 + Streamable HTTP），
Lifecycle → Tools → Resources → Prompts 四块。
保留 zhao 的线程模型（并发响应天然处理），async 侧 asyncio.to_thread 包一层。
register_all 绑定蓝图 11 ToolRegistry（外部副作用默认 CREATE_MODIFY 确认级）。
"""

import asyncio
import json
import subprocess
import threading
import urllib.error
import urllib.request


class MCPError(Exception):
    """JSON-RPC 错误：code + message（-32700 解析/-32601 方法不存在/-32000 超时等）。"""

    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class MCPClient:
    _PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, transport="stdio", command=None, args=None, env=None, url=None):
        self._transport = transport
        self._id = 0
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._server_info: dict = {}
        self._proc = None

        if transport == "http":
            self._url = url
            self._session_id = None
            self._session_ready = threading.Event()
            threading.Thread(target=self._sse_loop, daemon=True).start()
        else:
            self._proc = subprocess.Popen(
                [command] + (args or []),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env,
            )
            threading.Thread(target=self._read_loop, daemon=True).start()

    # ── Lifecycle ────────────────────────────────────────────

    def initialize(self) -> dict:
        result = self._request("initialize", {
            "protocolVersion": self._PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "assistant-mcp-client", "version": "0.1.0"},
        })
        self._server_info = result
        self._notify("notifications/initialized")
        return result

    def shutdown(self):
        if self._transport == "http":
            try:
                self._http_request("shutdown")
            except Exception:
                pass
            return
        try:
            self._stdio_request("shutdown")
        except Exception:
            pass
        self._notify("notifications/exited")
        try:
            self._proc.terminate()
        except Exception:
            pass

    # ── Tools / Resources / Prompts ──────────────────────────

    def list_tools(self) -> list[dict]:
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        r = self._request("tools/call", {"name": name, "arguments": arguments})
        content = r.get("content", [])
        if content and isinstance(content[0], dict):
            return content[0].get("text", str(content))
        return str(content)

    def register_all(self, registry) -> int:
        """把 server 所有工具注册进蓝图 ToolRegistry（外部副作用默认确认级）。

        返回注册条数。handler 必须 async def（lambda 不能 await，蓝图 09 适配点）。
        """
        from app.agent.tools import ToolDef, ToolLevel  # 延迟导入避免循环

        def make_async_handler(client, name):
            async def handler(user_id, params):
                return await asyncio.to_thread(client.call_tool, name, params)

            return handler

        count = 0
        for t in self.list_tools():
            registry.register(ToolDef(
                name=t["name"],
                description=t.get("description", ""),
                parameters_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                level=ToolLevel.CREATE_MODIFY,  # 外部副作用默认确认级，可配置覆盖
                handler=make_async_handler(self, t["name"]),
            ))
            count += 1
        return count

    def list_resources(self) -> list[dict]:
        return self._request("resources/list").get("resources", [])

    def read_resource(self, uri: str) -> list[dict]:
        return self._request("resources/read", {"uri": uri}).get("contents", [])

    def list_prompts(self) -> list[dict]:
        return self._request("prompts/list").get("prompts", [])

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return self._request("prompts/get", params)

    # ── JSON-RPC 内核（zhao 线程模型原样搬）───────────────────

    def _request(self, method: str, params: dict | None = None) -> dict:
        if self._transport == "http":
            return self._http_request(method, params)
        return self._stdio_request(method, params)

    def _notify(self, method: str):
        if self._transport == "http":
            self._http_post({"jsonrpc": "2.0", "method": method})
            return
        self._send({"jsonrpc": "2.0", "method": method})

    def _stdio_request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            event = threading.Event()
            self._pending[rid] = event
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params:
            req["params"] = params
        self._send(req)
        event.wait(timeout=60)
        with self._lock:
            self._pending.pop(rid, None)
            raw = self._results.pop(rid, None)
        if raw is None:
            raise MCPError(-32000, f"请求超时: {method}")
        if "error" in raw:
            raise MCPError(raw["error"]["code"], raw["error"]["message"])
        return raw.get("result", {})

    def _send(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        with self._send_lock:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

    def _read_loop(self):
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = data.get("id")
            if rid is not None:
                with self._lock:
                    self._results[rid] = data
                    event = self._pending.get(rid)
                if event:
                    event.set()

    def _http_request(self, method: str, params: dict | None = None) -> dict:
        if not self._session_ready.wait(timeout=10):
            raise MCPError(-32000, f"SSE 流未建立: {method}")
        with self._lock:
            self._id += 1
            rid = self._id
            event = threading.Event()
            self._pending[rid] = event
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params:
            req["params"] = params
        resp = self._http_post(req)
        if resp is None:  # 202 异步 → 等 SSE 推送
            if not event.wait(timeout=60):
                with self._lock:
                    self._pending.pop(rid, None)
                    self._results.pop(rid, None)
                raise MCPError(-32000, f"请求超时: {method}")
            with self._lock:
                self._pending.pop(rid, None)
                resp = self._results.pop(rid, None)
        if "error" in resp:
            raise MCPError(resp["error"]["code"], resp["error"]["message"])
        return resp.get("result", {})

    def _http_post(self, req: dict) -> dict | None:
        body = json.dumps(req, ensure_ascii=False).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        r = urllib.request.Request(self._url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                if resp.status == 202:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                raise MCPError(e.code, str(e))
        except urllib.error.URLError as e:
            raise MCPError(-32000, f"连接失败: {e.reason}")

    def _sse_loop(self):
        try:
            r = urllib.request.Request(self._url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(r, timeout=30) as resp:
                self._session_id = resp.headers.get("Mcp-Session-Id")
                self._session_ready.set()
                for line in resp:
                    line = line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    rid = data.get("id")
                    if rid is None:
                        continue
                    with self._lock:
                        self._results[rid] = data
                        event = self._pending.get(rid)
                    if event:
                        event.set()
        except Exception:
            self._session_ready.set()
