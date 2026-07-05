# Tiksar VPN — Config Tester (خودکار روی GitHub)

ابزاری که کانفیگ‌های V2Ray/Xray رو از منابع اشتراکی می‌گیره، **اسمشون رو به `Tiksar vpn` عوض می‌کنه**،
با **هستهٔ رسمی Xray** تست پینگ می‌کنه، **تکراری/مرده‌ها رو حذف** می‌کنه و خروجی مرتب‌شده می‌سازه —
همه به‌صورت **خودکار هر ۲ ساعت** با GitHub Actions.

## جریان کار

1. **دریافت** کانفیگ‌ها از منابع (`config.yaml` → `sources`). base64 (استاندارد/URL-safe) و HTML خودکار هندل می‌شن.
2. **مرج با فایل فعلی**: کانفیگ‌های `All_Configs_Sub.txt` قبلی هم دوباره تست می‌شن تا اگه از کار افتادن پاک بشن.
3. **حذف تکراری** بر اساس هویت سرور (آدرس/پورت/شناسه/…)، مستقل از اسم.
4. **rename** همه به `Tiksar vpn - NNNN` — **اول اسم عوض می‌شه بعد تست**، تا هر کانفیگی که با اسم جدید کار نکنه همون‌جا حذف بشه.
5. **تست پینگ** با هستهٔ Xray: برای هر کانفیگ یه سوکس محلی بالا میاد و با HEAD به `cp.cloudflare.com/generate_204` پینگ گرفته می‌شه (روش health-check خود xray-core؛ min چند نمونه، fail-fast).
6. **خروجی**:
   - `All_Configs_Sub.txt` — همهٔ سالم‌ها، مرتب بر اساس پینگ.
   - `Splitted-By-Protocol/{vless,vmess,trojan,ss}.txt` — تفکیک بر اساس پروتکل.
   - `Base64/All_Configs_base64_Sub.txt` — نسخهٔ base64.

## اجرای دستی (لوکال)

```bash
pip install -r requirements.txt
python get_xray.py     # دانلود هستهٔ Xray برای سیستم فعلی
python run.py          # دریافت، rename، تست، ساخت خروجی
```

## اجرای خودکار (GitHub Actions)

فایل `.github/workflows/update.yml` هر ۲ ساعت اجرا می‌شه و نتیجه رو commit/push می‌کنه.
برای اجرای دستی: تب **Actions → Update & Test Configs → Run workflow**.

> اگه ریپو در حالت پیش‌فرض به Action اجازهٔ push نده، از
> **Settings → Actions → General → Workflow permissions** گزینهٔ **Read and write** رو فعال کن.

## ⚠️ نکتهٔ مهم دربارهٔ پینگ

تست از **دیتاسنتر GitHub (آمریکا/اروپا، اینترنت آزاد)** انجام می‌شه، نه از داخل ایران. یعنی:

- ✅ سرورهای **کاملاً مرده** درست حذف می‌شن.
- ❌ عددِ پینگ و «آیا از ایران خوب کار می‌کنه» را نشون **نمی‌ده** — سرورِ فیلترشده در ایران ممکنه اینجا «سالم» دیده بشه.

برای پینگِ واقعیِ ایران باید از یه ماشین داخل ایران (مثل Termux روی گوشی) تست بگیری.

## تنظیمات

همه‌چی در `config.yaml`:

| کلید | کار |
|---|---|
| `name` | اسم جدید کانفیگ‌ها (پیش‌فرض `Tiksar vpn`) |
| `sources` | لیست لینک منابع |
| `test.test_url` | آدرس سنجش پینگ |
| `test.max_ping_ms` | سقف پینگ برای سالم‌بودن |
| `test.concurrency` | تعداد تست هم‌زمان |
| `test.timeout_sec` / `test.samples` | تایم‌اوت و تعداد نمونهٔ هر کانفیگ |
| `output.*` | مسیر فایل‌های خروجی |

## پروتکل‌های پشتیبانی‌شده

`vmess`, `vless`, `trojan`, `ss` با ترنسپورت‌های tcp/ws/grpc/http/httpupgrade/xhttp/kcp/quic و امنیت tls/reality.
`hy2`/`tuic`/`warp` چون با هستهٔ Xray قابل تست نیستن، کنار گذاشته می‌شن.
