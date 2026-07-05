"""
تست پینگ کانفیگ‌ها با هستهٔ واقعی Xray.

روش (هم‌راستا با health-check خود xray-core):
  - برای هر کانفیگ یه inbound سوکس محلی + outbound کانفیگ با xray بالا میاد.
  - از طریق سوکس یه درخواست HEAD به test_url زده می‌شه؛ *هر* پاسخی که با
    "HTTP" شروع بشه یعنی تونل سالمه (سرور مرده اصلاً جواب نمی‌ده).
  - چند نمونه گرفته و **کمترین** (min RTT) به‌عنوان پینگ برگردونده می‌شه.
  - fail-fast: اگه چند probe پشت‌سرهم بدون هیچ موفقیتی بمونه، مرده حساب و رها می‌شه.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import tempfile
import time
import urllib.parse

_DEAD_AFTER = 2          # بعد از این تعداد probe ناموفقِ پیاپی بدون موفقیت -> مرده
_LAUNCH_SPACING = 0.02   # فاصلهٔ حداقلی بین spawnها (جلوگیری از spawn storm)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _build_full_config(outbound: dict, socks_port: int) -> dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": socks_port,
            "protocol": "socks",
            "settings": {"udp": False, "auth": "noauth"},
        }],
        "outbounds": [outbound],
    }


async def _wait_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=1)
            w.close()
            with contextlib.suppress(Exception):
                await w.wait_closed()
            return True
        except Exception:  # noqa: BLE001
            await asyncio.sleep(0.04)
    return False


async def _socks_head(socks_port: int, host: str, port: int, path: str, timeout: float) -> bool:
    """یک درخواست HEAD از طریق SOCKS5 محلی. True اگه پاسخ HTTP گرفتیم."""
    r, w = await asyncio.wait_for(
        asyncio.open_connection("127.0.0.1", socks_port), timeout=timeout)
    try:
        # SOCKS5 greeting (no auth)
        w.write(b"\x05\x01\x00")
        await w.drain()
        greet = await asyncio.wait_for(r.readexactly(2), timeout=timeout)
        if greet[1] != 0x00:
            return False
        # CONNECT به host:port (نوع آدرس = دامنه)
        hb = host.encode()
        w.write(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + port.to_bytes(2, "big"))
        await w.drain()
        rep = await asyncio.wait_for(r.readexactly(4), timeout=timeout)
        if rep[1] != 0x00:
            return False
        atyp = rep[3]
        if atyp == 0x01:
            await r.readexactly(4)
        elif atyp == 0x03:
            ln = await r.readexactly(1)
            await r.readexactly(ln[0])
        elif atyp == 0x04:
            await r.readexactly(16)
        await r.readexactly(2)      # port
        # HTTP HEAD
        req = (f"HEAD {path} HTTP/1.1\r\nHost: {host}\r\n"
               f"User-Agent: Tiksar\r\nConnection: close\r\n\r\n")
        w.write(req.encode())
        await w.drain()
        line = await asyncio.wait_for(r.readline(), timeout=timeout)
        return line.startswith(b"HTTP")
    finally:
        w.close()
        with contextlib.suppress(Exception):
            await w.wait_closed()


class XrayTester:
    def __init__(self, xray_path: str, test_url: str, timeout_sec: float,
                 samples: int, concurrency: int):
        self.xray = xray_path
        self.timeout = timeout_sec
        self.samples = max(1, samples)
        self.sem = asyncio.Semaphore(concurrency)
        self._launch_lock = asyncio.Lock()
        self._last_launch = 0.0

        u = urllib.parse.urlparse(test_url)
        self.host = u.hostname or "cp.cloudflare.com"
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.path = u.path or "/"
        if u.query:
            self.path += "?" + u.query

    async def _spawn(self, cfg_path: str):
        # فاصله‌گذاری لانچ‌ها تا چند ده xray هم‌زمان بالا نیان.
        async with self._launch_lock:
            now = time.monotonic()
            wait = self._last_launch + _LAUNCH_SPACING - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_launch = time.monotonic()
        return await asyncio.create_subprocess_exec(
            self.xray, "run", "-c", cfg_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def test_one(self, cfg) -> float | None:
        """پینگ (ms) یا None اگه مرده باشه."""
        async with self.sem:
            socks_port = _free_port()
            full = _build_full_config(cfg.outbound, socks_port)
            fd, path = tempfile.mkstemp(suffix=".json", prefix="tiksar_")
            os.close(fd)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(full, f)

            proc = None
            try:
                proc = await self._spawn(path)
                if not await _wait_port(socks_port, timeout=5):
                    return None

                best: float | None = None
                fails = 0
                for _ in range(self.samples):
                    t0 = time.monotonic()
                    try:
                        ok = await _socks_head(
                            socks_port, self.host, self.port, self.path, self.timeout)
                    except Exception:  # noqa: BLE001
                        ok = False
                    if ok:
                        ms = (time.monotonic() - t0) * 1000
                        best = ms if best is None else min(best, ms)
                    else:
                        fails += 1
                        if best is None and fails >= _DEAD_AFTER:
                            break     # مرده — وقت تلف نکن
                return best
            finally:
                if proc is not None:
                    with contextlib.suppress(Exception):
                        proc.terminate()
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(proc.wait(), timeout=5)
                with contextlib.suppress(Exception):
                    os.remove(path)


async def test_all(configs: list, xray_path: str, test_url: str,
                   timeout_sec: float, samples: int, concurrency: int,
                   max_ping_ms: float) -> list:
    """همهٔ کانفیگ‌ها رو تست می‌کنه، پینگ رو ست می‌کنه، و لیستِ سالم‌های
    مرتب‌شده بر اساس پینگ رو برمی‌گردونه."""
    tester = XrayTester(xray_path, test_url, timeout_sec, samples, concurrency)

    done = 0
    total = len(configs)
    lock = asyncio.Lock()

    async def worker(cfg):
        nonlocal done
        ping = await tester.test_one(cfg)
        cfg.ping = ping
        async with lock:
            done += 1
            if done % 25 == 0 or done == total:
                alive = sum(1 for c in configs if c.ping is not None)
                print(f"  ... {done}/{total} تست شد (سالم تا الان: {alive})")

    await asyncio.gather(*(worker(c) for c in configs))

    healthy = [c for c in configs if c.ping is not None and c.ping <= max_ping_ms]
    healthy.sort(key=lambda c: c.ping)
    return healthy
