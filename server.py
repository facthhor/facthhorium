"""Start Loom and open the llama-swap upstream port once the model is ready."""
import asyncio
import contextlib
import ctypes
from datetime import datetime
import errno
import http.client
import json
import os
import re
import shutil
from pathlib import Path
import signal
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
MODEL_ID = os.environ.get("RATI0_LOOM_MODEL_ID", "inkling-2-full")
MODEL_CARD = str(ROOT / "facthhorium.json")

# The weights' real path, so llama_log.rs names the model the way it names a
# llama.cpp run: its `-m` stem, Inkling-2-Mini-UD-Q4_K_M.
WEIGHTS = "Inkling-2-Mini-UD-Q4_K_M.gguf"

# rati0's decode-speed card reads llama-server.log. Loom does not write it, so
# the relay appends one request's timing there per completion, in llama.cpp's
# own line shapes. See llama_log.rs:151.
LOG_DIR = Path(os.environ.get("FACTHHORIUM_LOG_DIR", ROOT / "logs"))
LOG_PATH = str(LOG_DIR / "llama-server.log")

# loom-serve's own stderr goes here. The relay used to discard it (bare
# `except: pass`), so when Loom terminated a generation the reason was lost and
# llama-swap only saw a bare "upstream disconnection". This file records why:
# capacity/context errors, "terminated", and other fatal messages.
LOOM_LOG_PATH = str(LOG_DIR / "loom-serve.log")

LOG_DIR.mkdir(parents=True, exist_ok=True)

# Per-process bookkeeping: the run's epoch base (for the relative timestamps)
# and a task counter. Token counts are snapshotted per request, not shared, so
# concurrent relays and health checks cannot clobber each other's baseline.
_SPEED = {"base": 0.0, "task": 0}


SSE_KEEPALIVE_SECONDS = 15


def relative_time():
    """Seconds since the run's start, as llama.cpp's `min.sec.ms.us` field."""
    elapsed = max(0.0, time.time() - _SPEED["base"])
    minutes = int(elapsed // 60)
    rem = elapsed - minutes * 60
    secs = int(rem)
    millis = int((rem - secs) * 1000)
    micros = int(((rem - secs) * 1000 - millis) * 1000)
    return f"{minutes}.{secs:02d}.{millis:03d}.{micros:03d}"


def record_speed(prompt_tokens, gen_tokens, started, first_token, last_token):
    # The first generated token ends prefill. Only subsequent tokens have
    # measured decode intervals. Keep total context based on the full usage.
    prompt_ms = (first_token - started) * 1000.0
    gen_ms = (last_token - first_token) * 1000.0
    _SPEED["task"] += 1
    task = _SPEED["task"]
    rel = relative_time()
    ctx = prompt_tokens + gen_tokens
    line = (
        f"{rel} I slot print_timing: id  0 | task {task} | prompt eval time = {prompt_ms:.2f} ms / {prompt_tokens} tokens (prompt)\n"
        f"{rel} I slot print_timing: id  0 | task {task} |        eval time = {gen_ms:.2f} ms / {gen_tokens - 1} tokens (generation)\n"
        f"{rel} I slot      release: id  0 | task {task} | stop processing: n_tokens = {ctx}, truncated = 0\n"
    )
    with contextlib.suppress(OSError):
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line)


def mark_run_start():
    """Write the run header llama_log.rs keys on."""
    _SPEED["base"] = time.time()
    iso = datetime.now().astimezone().isoformat(timespec="seconds")
    header = (
        f"\n===== {iso}  start: -m {WEIGHTS} =====\n"
        "===== engine=facthhorium@loom drafter=none =====\n"
    )
    with contextlib.suppress(OSError):
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(header)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=2):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def model_status(path):
    with contextlib.closing(UnixHTTPConnection(path)) as connection:
        connection.request("GET", "/v1/status")
        response = connection.getresponse()
        if response.status != 200:
            return {}
        data = json.load(response)
    return next((entry["loom"] for entry in data["data"] if entry["id"] == MODEL_ID), {})


def warmup(path):
    with contextlib.closing(UnixHTTPConnection(path, timeout=120)) as connection:
        payload = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "What is 17 plus 25? Answer with the number only."}],
            "max_tokens": 96,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "none"},
        }
        connection.request("POST", "/v1/chat/completions", json.dumps(payload),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        result = json.load(response)
    if response.status != 200 or not result["choices"][0]["message"].get("content"):
        raise RuntimeError(f"Loom warmup failed: {result}")


def log_relay(message):
    with contextlib.suppress(OSError), open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"relay: {message}\n")


async def close_writer(writer):
    if writer is not None:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


class StreamTiming:
    """Observe Loom's unencoded SSE without retaining response text."""
    def __init__(self):
        self.pending = bytearray()
        self.first = self.last = None
        self.usage = None
        self.done = self.failed = False
        self.skip_line = False

    def feed(self, data, now):
        # Loom emits one data line per event. Long tool arguments still pass
        # through in full. Limit the observer's private copy of any one line.
        parts = data.split(b"\n")
        for i, part in enumerate(parts):
            if len(self.pending) + len(part) > 1024 * 1024:
                self.skip_line = True
                self.pending.clear()
            if not self.skip_line:
                self.pending.extend(part)
            if i == len(parts) - 1:
                break
            if not self.skip_line and self.pending.startswith(b"data:"):
                payload = self.pending[5:].strip()
                if payload == b"[DONE]":
                    self.done = True
                else:
                    try:
                        event = json.loads(payload)
                    except (ValueError, UnicodeError):
                        event = None
                    if isinstance(event, dict):
                        self.failed |= "error" in event
                        if event.get("usage"):
                            self.usage = event["usage"]
                        for choice in event.get("choices", []):
                            delta = choice.get("delta") or {}
                            if any(delta.get(k) for k in ("content", "reasoning_content", "tool_calls")):
                                if self.first is None:
                                    self.first = now
                                self.last = now
            self.pending.clear()
            self.skip_line = False

    def record(self, started):
        if self.done and not self.failed and self.usage and self.first and self.last > self.first:
            prompt = self.usage.get("prompt_tokens", 0)
            generated = self.usage.get("completion_tokens", 0)
            if prompt > 0 and generated > 1:
                record_speed(prompt, generated, started, self.first, self.last)


class SSEFrames:
    """Publish complete events so an upstream failure cannot tear a JSON delta."""
    separator = re.compile(rb"\r?\n\r?\n")

    def __init__(self):
        self.pending = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        self.tail = b""

    async def forward(self, data, writer, timing):
        prefix = len(self.tail)
        scan = self.tail + data if prefix else data
        start = 0
        for match in self.separator.finditer(scan):
            end = match.end() - prefix
            if end <= 0:
                continue
            piece = data[start:end]
            now = time.monotonic()
            if self.pending.tell():
                self.pending.write(piece)
                self.pending.seek(0)
                while part := self.pending.read(65536):
                    timing.feed(part, now)
                    writer.write(part)
                    await writer.drain()
                self.pending.seek(0)
                self.pending.truncate()
            else:
                timing.feed(piece, now)
                writer.write(piece)
            start = end
        if start < len(data):
            self.pending.write(data[start:])
            self.tail = scan[-3:] if not start else data[start:][-3:]
        else:
            self.tail = b""
        await writer.drain()


async def relay(path, client_reader, client_writer):
    upstream = None
    wrote_response = False
    started = time.monotonic()
    timing = frames = None
    side = "client request"
    try:
        header = await client_reader.readuntil(b"\r\n\r\n")
        lines = [line for line in header.split(b"\r\n")
                 if line.lower().rstrip(b" \t") != b"accept-encoding:"]
        header = b"\r\n".join(lines)
        fields = {key.lower(): value.strip() for line in lines[1:] if b":" in line
                  for key, value in [line.split(b":", 1)]}
        is_chat = lines[0].split(b" ")[:2] == [b"POST", b"/v1/chat/completions"]
        if b"transfer-encoding" in fields:
            # Preserve the original streaming upload path; no replay.
            side = "upstream connection"
            reader, upstream = await asyncio.open_unix_connection(path)
            upstream.write(header)
            async def upload():
                while piece := await client_reader.read(65536):
                    upstream.write(piece)
                    await upstream.drain()
                if upstream.can_write_eof():
                    upstream.write_eof()
            task = asyncio.create_task(upload())
            try:
                while piece := await reader.read(65536):
                    client_writer.write(piece)
                    await client_writer.drain()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            return
        size = int(fields.get(b"content-length", b"0"))
        if size < 0 or size > 8388608:
            client_writer.write(b"HTTP/1.1 413 Payload Too Large\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            await client_writer.drain()
            return
        body = await client_reader.readexactly(size)
        attempts = 3 if is_chat and body else 1
        for attempt in range(1, attempts + 1):
            try:
                side = "upstream request"
                reader, upstream = await asyncio.open_unix_connection(path)
                upstream.writelines((header, body))
                await upstream.drain()
                response = await reader.readuntil(b"\r\n\r\n")
                break
            except (OSError, asyncio.IncompleteReadError) as exc:
                await close_writer(upstream)
                upstream = None
                if attempt == attempts:
                    raise
                log_relay(f"retry {attempt}/{attempts-1} before headers ({type(exc).__name__})")
                await asyncio.sleep(0.1)
        side = "downstream write"
        wrote_response = True
        client_writer.write(response)
        await client_writer.drain()
        resp_fields = {key.lower(): value.strip().lower() for line in response.split(b"\r\n")[1:]
                       if b":" in line for key, value in [line.split(b":", 1)]}
        # Loom uses close-delimited, uncompressed SSE. Only that framing
        # permits insertion of SSE comment events without HTTP re-encoding.
        if (is_chat and resp_fields.get(b"content-type", b"").split(b";")[0] == b"text/event-stream"
                and not {b"content-length", b"transfer-encoding", b"content-encoding"} & resp_fields.keys()):
            timing = StreamTiming()
            frames = SSEFrames()
        while True:
            side = "upstream read"
            if timing is None:
                piece = await reader.read(65536)
            else:
                try:
                    piece = await asyncio.wait_for(reader.read(65536), SSE_KEEPALIVE_SECONDS)
                except TimeoutError:
                    if not timing.done:
                        side = "downstream keepalive"
                        client_writer.write(b": keepalive\n\n")
                        await client_writer.drain()
                    continue
            if not piece:
                if timing is not None and not timing.done:
                    raise EOFError("stream ended before [DONE]")
                break
            side = "downstream write"
            if frames is not None:
                await frames.forward(piece, client_writer, timing)
            else:
                client_writer.write(piece)
                await client_writer.drain()
        if timing is not None:
            timing.record(started)
    except (OSError, EOFError, ValueError, asyncio.LimitOverrunError) as exc:
        log_relay(f"{side}: {type(exc).__name__} ({exc}); response_started={wrote_response}")
        with contextlib.suppress(OSError):
            if side.startswith("upstream") and not wrote_response:
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            elif side == "upstream read" and timing and not timing.done:
                client_writer.write(b'data: {"error":{"message":"Loom stream ended before completion","type":"upstream_error"}}\n\ndata: [DONE]\n\n')
            await client_writer.drain()
    finally:
        if frames is not None:
            frames.pending.close()
        await close_writer(upstream)
        await close_writer(client_writer)


def exec_loom(path):
    # IREE falls back to POSIX I/O when io_uring is unavailable. Scope this to
    # the Loom child so buffered reads work under the user manager's memlock limit.
    seccomp = ctypes.CDLL("libseccomp.so.2")
    seccomp.seccomp_init.argtypes = (ctypes.c_uint32,)
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
    seccomp.seccomp_rule_add.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint)
    seccomp.seccomp_load.argtypes = (ctypes.c_void_p,)
    seccomp.seccomp_release.argtypes = (ctypes.c_void_p,)
    seccomp.seccomp_release.restype = None
    allow = 0x7FFF0000  # SCMP_ACT_ALLOW
    return_enosys = 0x00050000 | errno.ENOSYS  # SCMP_ACT_ERRNO(ENOSYS)
    context = seccomp.seccomp_init(allow)
    if not context:
        raise RuntimeError("Unable to initialize Loom's syscall filter")
    try:
        result = seccomp.seccomp_rule_add(
            context, return_enosys, seccomp.seccomp_syscall_resolve_name(b"io_uring_setup"), 0
        )
        if result == 0:
            result = seccomp.seccomp_load(context)
        if result != 0:
            raise OSError(-result, os.strerror(-result))
    finally:
        seccomp.seccomp_release(context)
    loom = shutil.which("loom-serve")
    if not loom:
        raise RuntimeError("loom-serve was not found on PATH; install hrx-loom first")
    light = os.environ.get("RATI0_LOOM_LIGHT") == "1"
    device = "amdgpu" if light else "amdgpu://?completion_spin_ns=4294967295"
    resource_options = [
        "--wait_mode=blocking",
        "--workers=4",
        "--workspace_idle_ms=8000",
        "--parameter_idle_ms=60000",
        "--memory_bytes=26gib",
    ] if light else []
    os.execv(loom, [
        loom,
        "--model=" + MODEL_CARD,
        "--device=" + device,
        "--listen=unix:" + path,
        "--parameter_mode=file",
        "--weight_slab_bytes=64mib",
        "--state_slab_bytes=8mib",
        *resource_options,
    ])


async def serve(port, path):
    # Capture loom-serve's stderr. It is exec'd (os.execv) so this file receives
    # the runtime's fatal messages (capacity, context, "terminated", panics)
    # that were previously discarded, leaving only llama-swap's opaque
    # "upstream disconnection during streaming" with no cause.
    loom_log = open(LOOM_LOG_PATH, "a", encoding="utf-8")
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, __file__, "--exec-loom", path, stderr=loom_log
        )
    finally:
        loom_log.close()
    exited = asyncio.create_task(process.wait())
    try:
        while not exited.done():
            try:
                status = await asyncio.to_thread(model_status, path)
            except (OSError, http.client.HTTPException):
                status = {}
            if status.get("registration") == "failed":
                raise RuntimeError(status.get("error", "Loom model preparation failed"))
            if status.get("registration") == "ready":
                break
            await asyncio.sleep(0.25)
        if exited.done():
            raise RuntimeError(f"Loom exited during startup with status {exited.result()}")
        await asyncio.to_thread(warmup, path)
        await asyncio.to_thread(mark_run_start)
        server = await asyncio.start_server(lambda r, w: relay(path, r, w), "127.0.0.1", port)
        async with server:
            code = await asyncio.shield(exited)
        if code:
            raise RuntimeError(f"Loom exited with status {code}")
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(exited), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await exited


async def main(port):
    with tempfile.TemporaryDirectory(prefix="rati0-loom-") as directory:
        task = asyncio.create_task(serve(port, str(Path(directory) / "api.sock")))
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    if sys.argv[1] == "--exec-loom":
        exec_loom(sys.argv[2])
    else:
        asyncio.run(main(int(sys.argv[1])))
