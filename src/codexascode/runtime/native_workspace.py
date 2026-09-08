"""Bounded stdio client for the installed Codex app-server."""
import json, select, subprocess, time

class NativeError(ValueError):pass

class Client:
    def __enter__(self):
        self.process = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.buffer = b""
        self.next_id = 0
        try:
            self.request("initialize", {"clientInfo": {"name": "cac-workspace", "version": "1.0.0"}, "capabilities": {"experimentalApi": True}})
            self.process.stdin.write((json.dumps({"method": "initialized"}) + "\n").encode())
            self.process.stdin.flush()
        except Exception:
            self.__exit__();raise
        return self

    def __exit__(self, *args):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()  # Only the client process launched above.
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        self.process.stdout.close()

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.process.stdin.write((json.dumps({"id": request_id, "method": method, "params": params}) + "\n").encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            while b"\n" not in self.buffer:
                if not select.select([self.process.stdout], [], [], max(0, deadline - time.monotonic()))[0]:
                    raise TimeoutError(f"{method}: response timed out")
                import os
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise NativeError("app-server closed before response")
                self.buffer += chunk
                if len(self.buffer)>1024*1024:raise NativeError("app-server response exceeds limit")
            line, self.buffer = self.buffer.split(b"\n", 1)
            value = json.loads(line)
            if not isinstance(value,dict):raise NativeError("invalid app-server response")
            if value.get("id") != request_id:
                continue
            if "error" in value:
                raise NativeError(f"{method}: native request failed")
            return value["result"]
        raise TimeoutError(f"{method}: response timed out")

