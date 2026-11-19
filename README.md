# TradingView Webhook Tester & JSON Inspector (Free OSS Lite Edition)

Zero-dependency Python 3 local webhook server (`http.server` on `127.0.0.1:8787`) for testing and debugging **TradingView Alert JSON** payloads before connecting real exchange capital.

Keywords: `TradingView Webhook`, `PineScript Alert JSON`, `Local Webhook Tester`, `Bybit`, `Binance Futures`, `Crypto Bot`

---

## English Documentation

### What It Does
- **Local HTTP server (`127.0.0.1:8787`):** Instant zero-dependency receiver via Python's `ThreadingHTTPServer`.
- **JSON Validation & Diagnostics:** Catches broken TradingView alert JSON syntax (`HTTP 400`), missing `ticker`/`action` fields, and optional `secret`/`passphrase` mismatches (`HTTP 401`).
- **Parsed Signal & Timing Output:** Displays normalized `symbol`, `action`, `order_type`, `price`, `qty`, `timeframe`, and exact parse latency in milliseconds (`latency_ms`).
- **JSONL Logging:** Optionally save every incoming alert to disk (`--log-file alerts.jsonl`).

### Quick Start
```bash
# Start local TradingView webhook inspector on 127.0.0.1:8787
python webhook_tester.py

# Require a shared secret & save alerts to JSONL
python webhook_tester.py --port 8787 --secret mysecret123 --log-file alerts.jsonl

# Send a test alert via curl (in another terminal)
curl -X POST http://127.0.0.1:8787/webhook \
  -H "Content-Type: application/json" \
  -d '{"ticker":"BTCUSDT","action":"buy","price":94500,"qty":0.05,"strategy":"Breakout"}'

# Run built-in end-to-end HTTP self-tests
python webhook_tester.py --self-test
```

Expose locally to TradingView cloud alerts using `ngrok http 8787` or Cloudflare Tunnel (`cloudflared tunnel --url http://127.0.0.1:8787`).

---

### Need Production Execution to Bybit v5 / Binance Futures + Auto Risk Sizing + PineScript v6 Template?

This free Lite server helps you inspect and validate TradingView JSON payloads locally. When you are ready to **automatically execute TradingView alerts on real markets** with proper safeguards:
- Direct **Bybit v5** & **Binance Futures** order execution engine (Market / Limit / TP & SL)
- **Automatic % Equity Risk Sizing** & leverage management per trade
- Ready-to-paste **PineScript v6 Alert JSON Template** (no broken placeholders or duplicate triggers)
- Built-in secret auth, duplicate signal cooldown, and Telegram execution notifications

👉 **Get the Full Production Webhook Execution Bot (Instant Auto-Delivery on FunPay):**
- EN: https://funpay.com/en/lots/offer?id=82596233
- RU: https://funpay.com/lots/offer?id=82596233

---

## Документация на русском (RU)

### Возможности бесплатного инспектора вебхуков
- **Локальный HTTP-сервер (`127.0.0.1:8787`):** работает на чистом Python 3 без установки сторонних пакетов.
- **Валидация JSON-пейлоада TradingView:** мгновенно выявляет синтаксические ошибки JSON (`HTTP 400`), неверный секретный ключ (`HTTP 401`) и отсутствие ключевых полей сигнала.
- **Парсинг сигнала и замер задержки:** выводит распарсенные `symbol`, `action`, `price`, `qty`, `timeframe` и время обработки в миллисекундах.
- **Встроенный `--self-test`:** проверяет все сценарии HTTP-запросов автоматически.

### Быстрый запуск
```bash
# Запустить локальный инспектор на 127.0.0.1:8787
python webhook_tester.py

# Запуск с проверкой секрета и сохранением логов
python webhook_tester.py --secret mysecret123 --log-file alerts.jsonl

# Самопроверка HTTP-сервера и валидации JSON
python webhook_tester.py --self-test
```

### Нужен готовый боевой бот для Bybit v5 / Binance Futures + Auto Risk Sizing + шаблон PineScript v6?

Бесплатный Lite-скрипт только принимает и проверяет JSON локально. Для **реальной автоматической торговли по алертам TradingView** с расчётом риска и защитой от дублей забирайте готовый Pro-исполнитель с автовыдачей:
- Исполнение ордеров на **Bybit v5** и **Binance Futures** (Market/Limit, автоматические TP/SL)
- **Автоматический расчёт объёма позиции** от процента риска на сделку
- Готовый шаблон алерта на **PineScript v6** + уведомления в Telegram
- EN: https://funpay.com/en/lots/offer?id=82596233
- RU: https://funpay.com/lots/offer?id=82596233
