"""
دانلود باینری هستهٔ Xray از ریلیز رسمی XTLS/Xray-core داخل پوشهٔ ./xray/.

فقط اجرا کن:  python get_xray.py

روی GitHub Actions (لینوکس x64) نسخهٔ Xray-linux-64 رو می‌گیره؛ روی ویندوز/مک/ترموکس
هم معماری درست رو خودش تشخیص می‌ده تا بشه لوکال هم تست کرد.
"""

from __future__ import annotations

import contextlib
import io
import os
import platform
import stat
import sys
import urllib.request
import zipfile

# روی ویندوز کنسول پیش‌فرض cp1252 هست و متن فارسی رو کرش می‌ده؛ به UTF-8 سوییچ کن.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

HERE = os.path.dirname(os.path.abspath(__file__))
DEST_DIR = os.path.join(HERE, "xray")

# https://github.com/XTLS/Xray-core/releases/latest/download/<asset>
BASE = "https://github.com/XTLS/Xray-core/releases/latest/download"


def _asset_name() -> str:
    system = platform.system().lower()          # windows / linux / darwin
    machine = platform.machine().lower()        # amd64 / x86_64 / arm64 / aarch64 / armv7l ...

    is_arm64 = machine in ("arm64", "aarch64")
    # armv8l = چیپ ۶۴بیتی با userland ۳۲بیتی -> باید نسخهٔ v7a رو بگیره.
    is_arm32 = (not is_arm64) and (machine.startswith("arm") or machine == "armhf")
    is_x64 = machine in ("amd64", "x86_64", "x64")

    if system == "windows":
        if is_arm64:
            return "Xray-windows-arm64-v8a.zip"
        return "Xray-windows-64.zip" if is_x64 else "Xray-windows-32.zip"
    if system == "darwin":
        return "Xray-macos-arm64-v8a.zip" if is_arm64 else "Xray-macos-64.zip"
    if system == "linux":
        if is_arm64:
            return "Xray-linux-arm64-v8a.zip"
        if is_arm32:
            return "Xray-linux-arm32-v7a.zip"
        return "Xray-linux-64.zip" if is_x64 else "Xray-linux-32.zip"

    raise RuntimeError(f"سیستم‌عامل پشتیبانی‌نشده: {system}/{machine}")


def binary_name() -> str:
    return "xray.exe" if platform.system().lower() == "windows" else "xray"


def binary_path() -> str:
    return os.path.join(DEST_DIR, binary_name())


def fetch_core() -> bool:
    """دانلود + استخراج هستهٔ Xray. در صورت موفقیت True برمی‌گردونه."""
    try:
        asset = _asset_name()
    except RuntimeError as e:
        print(f"[!] {e}")
        return False

    url = f"{BASE}/{asset}"
    print(f"در حال دانلود هستهٔ Xray:\n  {url}\n")

    req = urllib.request.Request(url, headers={"User-Agent": "TiksarVPN/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
    except Exception as e:  # noqa: BLE001
        print(f"[!] دانلود نشد: {e}")
        return False

    os.makedirs(DEST_DIR, exist_ok=True)
    binary = binary_name()
    extracted = False
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            base = os.path.basename(member)
            # باینری xray + فایل‌های geo که ممکنه لازم بشن
            if base in (binary, "geoip.dat", "geosite.dat"):
                target = os.path.join(DEST_DIR, base)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                if base == binary and platform.system().lower() != "windows":
                    os.chmod(target, os.stat(target).st_mode | stat.S_IEXEC)
                if base == binary:
                    extracted = True
                print(f"  + {base}")

    if not extracted:
        print("[!] فایل اجرایی xray توی آرشیو پیدا نشد.")
        return False

    print(f"\nهسته آماده شد: {binary_path()}")
    return True


def main() -> None:
    sys.exit(0 if fetch_core() else 1)


if __name__ == "__main__":
    main()
