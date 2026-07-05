#!/usr/bin/env python3
"""
Tiksar VPN — Config Tester  (نقطهٔ ورود اصلی)

جریان کار:
  1. دریافت کانفیگ‌ها از منابع  (fetcher)
  2. مرج با فایل خروجیِ فعلی  → کانفیگ‌های قبلی هم دوباره تست می‌شن
  3. پارس + حذف تکراری (dedup بر اساس هویت سرور، مستقل از اسم)
  4. rename همه به «Tiksar vpn - N»  (اول اسم، بعد تست)
  5. تست پینگ با هستهٔ Xray  → مرده‌ها حذف، سالم‌ها مرتب بر اساس پینگ
  6. نوشتن خروجی: فایل All + تفکیک بر اساس پروتکل + نسخهٔ base64

اجرا:  python run.py
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import platform
import sys

# روی ویندوز کنسول پیش‌فرض cp1252 هست و متن فارسی رو کرش می‌ده؛ به UTF-8 سوییچ کن.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import yaml

import fetcher
import parsers
import tester

HERE = os.path.dirname(os.path.abspath(__file__))

PROTO_FILES = {
    "vless": "vless.txt",
    "vmess": "vmess.txt",
    "trojan": "trojan.txt",
    "ss": "ss.txt",
}


def _load_config() -> dict:
    with open(os.path.join(HERE, "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _xray_binary(xray_dir: str) -> str:
    name = "xray.exe" if platform.system().lower() == "windows" else "xray"
    return os.path.join(HERE, xray_dir, name)


def _header(name: str) -> str:
    title = base64.b64encode(name.encode()).decode()
    return (
        f"#profile-title: base64:{title}\n"
        f"#profile-update-interval: 2\n"
        f"#support-url: https://t.me/tiksar_vpn\n"
        f"#profile-web-page-url: https://t.me/tiksar_vpn\n"
    )


def _read_existing(all_path: str) -> list[str]:
    """URIهای فایل خروجیِ فعلی رو می‌خونه تا دوباره تست بشن."""
    if not os.path.exists(all_path):
        return []
    with open(all_path, "r", encoding="utf-8") as f:
        text = f.read()
    return fetcher.extract_uris(text)


def _write(path: str, header: str, uris: list[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for u in uris:
            f.write(u + "\n")


async def _amain() -> int:
    cfg = _load_config()
    name = cfg.get("name", "Tiksar vpn")
    out = cfg["output"]
    tst = cfg["test"]

    out_dir = os.path.join(HERE, out["dir"])
    all_path = os.path.join(out_dir, out["all_file"])
    split_dir = os.path.join(out_dir, out["split_dir"])
    base64_path = os.path.join(out_dir, out["base64_all"])

    xray_bin = _xray_binary(cfg["xray"]["dir"])
    if not os.path.exists(xray_bin):
        print(f"[!] هستهٔ Xray پیدا نشد: {xray_bin}\n    اول اجرا کن:  python get_xray.py")
        return 1

    # 1) دریافت از منابع
    print("» دریافت کانفیگ‌ها از منابع...")
    fetched = fetcher.fetch_all(cfg["sources"])
    print(f"  مجموع (یکتا) از منابع: {len(fetched)}")

    # 2) مرج با فایل فعلی (re-test قبلی‌ها)
    existing = _read_existing(all_path)
    if existing:
        print(f"» {len(existing)} کانفیگ از فایل فعلی هم دوباره تست می‌شن.")
    raw_uris = fetched + existing

    # 3) پارس + dedup بر اساس هویت
    print("» پارس و حذف تکراری‌ها...")
    by_identity: dict[str, parsers.Config] = {}
    parsed_ok = 0
    for uri in raw_uris:
        c = parsers.parse(uri)
        if c is None:
            continue
        parsed_ok += 1
        by_identity.setdefault(c.identity, c)   # اولین نمونه از هر هویت می‌مونه
    configs = list(by_identity.values())
    print(f"  پارس موفق: {parsed_ok}  |  بعد از حذف تکراری: {len(configs)}")

    if not configs:
        print("[!] هیچ کانفیگ قابل‌تستی پیدا نشد.")
        return 1

    # 4) rename (اول اسم، بعد تست) — اسم یکتا با شماره
    for i, c in enumerate(configs, 1):
        c.rename(f"{name} - {i:04d}")

    # 5) تست پینگ با Xray
    print(f"» تست پینگ {len(configs)} کانفیگ با هستهٔ Xray "
          f"(هم‌زمانی={tst['concurrency']})...")
    healthy = await tester.test_all(
        configs,
        xray_path=xray_bin,
        test_url=tst["test_url"],
        timeout_sec=float(tst["timeout_sec"]),
        samples=int(tst["samples"]),
        concurrency=int(tst["concurrency"]),
        max_ping_ms=float(tst["max_ping_ms"]),
    )
    print(f"  سالم: {len(healthy)}  |  حذف‌شده (مرده/کند): {len(configs) - len(healthy)}")

    if not healthy:
        print("[!] هیچ کانفیگ سالمی نموند — خروجی دست‌نخورده باقی می‌مونه.")
        return 0

    # 6) نوشتن خروجی‌ها
    header = _header(name)
    all_uris = [c.uri for c in healthy]           # از قبل بر اساس پینگ مرتب‌اند
    _write(all_path, header, all_uris)
    print(f"  ✓ {out['all_file']}  ({len(all_uris)} کانفیگ)")

    for proto, fname in PROTO_FILES.items():
        uris = [c.uri for c in healthy if c.protocol == proto]
        _write(os.path.join(split_dir, fname), header, uris)
        print(f"  ✓ {out['split_dir']}/{fname}  ({len(uris)} کانفیگ)")

    # نسخهٔ base64 از فایل کامل
    with open(all_path, "r", encoding="utf-8") as f:
        content = f.read()
    os.makedirs(os.path.dirname(base64_path) or ".", exist_ok=True)
    with open(base64_path, "w", encoding="utf-8") as f:
        f.write(base64.b64encode(content.encode()).decode())
    print(f"  ✓ {out['base64_all']}")

    print("\n✅ تمام شد.")
    return 0


def main() -> None:
    if platform.system().lower() == "windows":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
