"""
دریافت کانفیگ‌ها از منابع اشتراکی (subscription) و استخراج URIهای خام.

- هر منبع یا متن خام خط‌به‌خطه یا کل فایل base64 (استاندارد یا URL-safe).
- HTML/متن آزاد هم پشتیبانی می‌شه: با regex همهٔ URIهای کانفیگ استخراج می‌شن.
"""

from __future__ import annotations

import base64
import re
import urllib.request

# فقط پروتکل‌هایی که هستهٔ Xray می‌تونه واقعاً تست کنه.
# (hy2/tuic/warp با هستهٔ Xray قابل تست نیستن و کنار گذاشته می‌شن.)
_URI_RE = re.compile(r'(?:vmess|vless|trojan|ss)://[^\s"\'<>\\`]+', re.IGNORECASE)

_HEADERS = {"User-Agent": "Mozilla/5.0 (TiksarVPN ConfigTester)"}


def _get(url: str, timeout: int = 20) -> str:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"  [!] دریافت نشد: {url}  ({e})")
        return ""


def _maybe_b64_decode(text: str) -> str:
    """اگر متن کل base64 باشه دیکد می‌کنه، وگرنه خودش رو برمی‌گردونه.

    هم base64 استاندارد و هم URL-safe ('-'/'_') رو درست هندل می‌کنه.
    """
    compact = "".join(text.split())
    if not compact:
        return text
    # ترجمهٔ URL-safe به استاندارد (برای متن استاندارد بی‌ضرره).
    compact = compact.replace("-", "+").replace("_", "/")
    compact += "=" * (-len(compact) % 4)
    try:
        decoded = base64.b64decode(compact).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return text
    # فقط وقتی قبولش کن که واقعاً به کانفیگ رسیدیم.
    return decoded if "://" in decoded else text


def extract_uris(text: str) -> list[str]:
    return _URI_RE.findall(text)


def fetch_all(urls: list[str]) -> list[str]:
    """همهٔ منابع رو می‌گیره و لیست یکتای URIها (به‌ترتیب دیده‌شدن) برمی‌گردونه."""
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        raw = _get(url)
        if not raw:
            continue
        # اگه "://" نداشت احتمالاً کل فایل base64 هست.
        text = raw if "://" in raw else _maybe_b64_decode(raw)
        found = extract_uris(text)
        for uri in found:
            uri = uri.strip().rstrip(",")
            if uri and uri not in seen:
                seen.add(uri)
                result.append(uri)
        print(f"  + {url}  →  {len(found)} کانفیگ")
    return result
