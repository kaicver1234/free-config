"""
پارس URIهای کانفیگ (vmess/vless/trojan/ss) به outbound هستهٔ Xray + rename.

هر کانفیگ به یه شیء Config تبدیل می‌شه که:
  - outbound: دیکشنری outbound برای ساخت config تست Xray
  - identity: کلید یکتاسازی (بدون در نظر گرفتن اسم) برای حذف تکراری‌ها
  - rename(name): همون URI رو دقیقاً با اسم جدید بازتولید می‌کنه (بقیهٔ پارامترها دست‌نخورده)

نکتهٔ مهم: اسم (remark) هیچ اثری روی تونل نداره؛ پس تستِ outbound = تستِ کانفیگِ
renameشده. اول rename، بعد تست — دقیقاً همون بایتی که publish می‌شه تست می‌شه.
"""

from __future__ import annotations

import base64
import json
import urllib.parse


class Config:
    __slots__ = ("protocol", "outbound", "identity", "_kind", "_payload", "ping", "name", "uri")

    def __init__(self, protocol: str, outbound: dict, identity: str, kind: str, payload):
        self.protocol = protocol          # vmess/vless/trojan/ss
        self.outbound = outbound          # دیکشنری outbound اکس‌ری
        self.identity = identity          # کلید dedup (lowercase)
        self._kind = kind                 # "vmess" (json) یا "frag" (اصلاح #fragment)
        self._payload = payload           # dict برای vmess، str (بدون fragment) برای بقیه
        self.ping: float | None = None
        self.name: str | None = None
        self.uri: str | None = None       # بعد از rename ست می‌شه

    def rename(self, name: str) -> str:
        """URI رو با اسم جدید بازتولید می‌کنه و برمی‌گردونه."""
        if self._kind == "vmess":
            j = dict(self._payload)
            j["ps"] = name
            raw = json.dumps(j, ensure_ascii=False)
            self.uri = "vmess://" + base64.b64encode(raw.encode("utf-8")).decode()
        else:
            self.uri = self._payload + "#" + urllib.parse.quote(name)
        self.name = name
        return self.uri


# ---------------------------------------------------------------------------
# هلپرها
# ---------------------------------------------------------------------------

def _b64decode(s: str) -> bytes:
    s = "".join(s.split()).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _qs(query: str) -> dict:
    d: dict[str, str] = {}
    for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True):
        d[k.lower()] = v
    return d


def _split_hostport(hp: str) -> tuple[str, int]:
    hp = hp.strip()
    if hp.startswith("["):                       # IPv6 داخل []
        host, _, rest = hp[1:].partition("]")
        port = rest.lstrip(":")
        return host, int(port or 0)
    host, _, port = hp.rpartition(":")
    if not host:                                 # پورت نداشت
        return hp, 0
    return host, int(port or 0)


def _stream_settings(net: str, security: str, p: dict) -> dict:
    """ساخت streamSettings از network/security و پارامترها."""
    net = (net or "tcp").lower()
    if net in ("h2", "http"):
        xnet = "http"
    elif net == "splithttp":
        xnet = "xhttp"
    else:
        xnet = net

    security = (security or "none").lower()
    if security not in ("tls", "reality", "xtls"):
        security = "none"

    ss: dict = {"network": xnet, "security": "tls" if security == "xtls" else security}

    sni = p.get("sni") or p.get("peer") or p.get("host") or ""
    fp = p.get("fp") or ""
    alpn = p.get("alpn") or ""

    if ss["security"] == "tls":
        t: dict = {"allowInsecure": True}
        if sni:
            t["serverName"] = sni
        if fp:
            t["fingerprint"] = fp
        if alpn:
            t["alpn"] = [a for a in alpn.split(",") if a]
        ss["tlsSettings"] = t
    elif ss["security"] == "reality":
        r: dict = {}
        if sni:
            r["serverName"] = sni
        if fp:
            r["fingerprint"] = fp
        if p.get("pbk"):
            r["publicKey"] = p["pbk"]
        if p.get("sid"):
            r["shortId"] = p["sid"]
        if p.get("spx"):
            r["spiderX"] = p["spx"]
        ss["realitySettings"] = r

    host = p.get("host") or ""
    path = p.get("path") or "/"

    if xnet == "ws":
        w: dict = {"path": path}
        if host:
            w["headers"] = {"Host": host}
        ss["wsSettings"] = w
    elif xnet == "grpc":
        g: dict = {"serviceName": p.get("servicename") or p.get("path") or ""}
        if p.get("mode") == "multi" or p.get("multimode") in ("true", "1"):
            g["multiMode"] = True
        ss["grpcSettings"] = g
    elif xnet == "http":
        h: dict = {"path": path}
        if host:
            h["host"] = [x for x in host.split(",") if x]
        ss["httpSettings"] = h
    elif xnet == "httpupgrade":
        hu: dict = {"path": path}
        if host:
            hu["host"] = host
        ss["httpupgradeSettings"] = hu
    elif xnet == "xhttp":
        xh: dict = {"path": path}
        if host:
            xh["host"] = host
        if p.get("mode"):
            xh["mode"] = p["mode"]
        ss["xhttpSettings"] = xh
    elif xnet == "tcp":
        if (p.get("headertype") or p.get("type")) == "http":
            req: dict = {"path": [path]}
            if host:
                req["headers"] = {"Host": [x for x in host.split(",") if x]}
            ss["tcpSettings"] = {"header": {"type": "http", "request": req}}
    elif xnet == "kcp":
        k: dict = {"header": {"type": p.get("headertype") or p.get("type") or "none"}}
        if p.get("seed"):
            k["seed"] = p["seed"]
        ss["kcpSettings"] = k
    elif xnet == "quic":
        ss["quicSettings"] = {
            "security": p.get("quicsecurity") or "none",
            "key": p.get("key") or "",
            "header": {"type": p.get("headertype") or "none"},
        }
    return ss


# ---------------------------------------------------------------------------
# پارسرهای هر پروتکل
# ---------------------------------------------------------------------------

def _parse_vmess(uri: str) -> Config:
    j = json.loads(_b64decode(uri[len("vmess://"):]).decode("utf-8", "ignore"))
    add = str(j.get("add", ""))
    port = int(str(j.get("port", "0")) or 0)
    uid = str(j.get("id", ""))
    net = str(j.get("net", "tcp")).lower()
    tls = str(j.get("tls", "")).lower()
    sec = "tls" if tls == "tls" else ("reality" if tls == "reality" else "none")

    p = {
        "host": str(j.get("host", "")),
        "path": str(j.get("path", "/")),
        "sni": str(j.get("sni", "")) or str(j.get("host", "")),
        "fp": str(j.get("fp", "")),
        "alpn": str(j.get("alpn", "")),
        "type": str(j.get("type", "none")),
        "headertype": str(j.get("type", "none")),
        "servicename": str(j.get("path", "")) if net == "grpc" else "",
        "seed": str(j.get("path", "")) if net == "kcp" else "",
        "mode": str(j.get("type", "")) if net == "grpc" else "",
        "pbk": str(j.get("pbk", "")),
        "sid": str(j.get("sid", "")),
        "spx": str(j.get("spx", "")),
    }
    out = {
        "protocol": "vmess",
        "settings": {"vnext": [{
            "address": add, "port": port,
            "users": [{"id": uid, "alterId": int(str(j.get("aid", 0)) or 0),
                       "security": str(j.get("scy", "auto")) or "auto"}],
        }]},
        "streamSettings": _stream_settings(net, sec, p),
    }
    ident = f"vmess|{add}|{port}|{uid}|{net}|{p['path']}|{p['host']}".lower()
    return Config("vmess", out, ident, "vmess", j)


def _parse_vless(uri: str) -> Config:
    body = uri[len("vless://"):]
    base, _, _frag = body.partition("#")
    userinfo, _, hostpart = base.partition("@")
    hostport, _, query = hostpart.partition("?")
    add, port = _split_hostport(hostport)
    p = _qs(query)
    net = p.get("type", "tcp")
    sec = p.get("security", "none")
    out = {
        "protocol": "vless",
        "settings": {"vnext": [{
            "address": add, "port": port,
            "users": [{"id": userinfo, "encryption": p.get("encryption", "none") or "none",
                       "flow": p.get("flow", "")}],
        }]},
        "streamSettings": _stream_settings(net, sec, p),
    }
    ident = (f"vless|{add}|{port}|{userinfo}|{net}|"
             f"{p.get('path', '')}|{p.get('host', '')}|{p.get('servicename', '')}").lower()
    return Config("vless", out, ident, "frag", "vless://" + base)


def _parse_trojan(uri: str) -> Config:
    body = uri[len("trojan://"):]
    base, _, _frag = body.partition("#")
    userinfo, _, hostpart = base.partition("@")
    password = urllib.parse.unquote(userinfo)
    hostport, _, query = hostpart.partition("?")
    add, port = _split_hostport(hostport)
    p = _qs(query)
    net = p.get("type", "tcp")
    sec = p.get("security", "tls")     # trojan پیش‌فرض tls
    out = {
        "protocol": "trojan",
        "settings": {"servers": [{"address": add, "port": port, "password": password}]},
        "streamSettings": _stream_settings(net, sec, p),
    }
    ident = f"trojan|{add}|{port}|{password}|{net}".lower()
    return Config("trojan", out, ident, "frag", "trojan://" + base)


def _parse_ss(uri: str) -> Config:
    body = uri[len("ss://"):]
    base, _, _frag = body.partition("#")
    base_noq, _, _query = base.partition("?")

    if "@" in base_noq:
        userinfo, _, hostport = base_noq.partition("@")
        try:
            dec = _b64decode(userinfo).decode("utf-8", "ignore")
            method, password = dec.split(":", 1)
        except Exception:  # noqa: BLE001
            method, password = urllib.parse.unquote(userinfo).split(":", 1)
        add, port = _split_hostport(hostport)
    else:
        dec = _b64decode(base_noq).decode("utf-8", "ignore")
        creds, _, hostport = dec.rpartition("@")
        method, password = creds.split(":", 1)
        add, port = _split_hostport(hostport)

    out = {
        "protocol": "shadowsocks",
        "settings": {"servers": [{
            "address": add, "port": port, "method": method, "password": password,
        }]},
    }
    ident = f"ss|{add}|{port}|{method}|{password}".lower()
    return Config("ss", out, ident, "frag", "ss://" + base)


def parse(uri: str) -> Config | None:
    """پارس یک URI. در صورت خطا/پروتکل ناشناخته None برمی‌گردونه."""
    uri = uri.strip()
    try:
        if uri.startswith("vmess://"):
            return _parse_vmess(uri)
        if uri.startswith("vless://"):
            return _parse_vless(uri)
        if uri.startswith("trojan://"):
            return _parse_trojan(uri)
        if uri.startswith("ss://"):
            return _parse_ss(uri)
    except Exception:  # noqa: BLE001
        return None
    return None
