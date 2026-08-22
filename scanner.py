import os
import time
import json
import requests
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

API_KEY = os.environ["TWELVEDATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD"]
FOREX_SYMBOLS = ["EUR/USD", "XAU/USD"]
SYMBOLS = CRYPTO_SYMBOLS + FOREX_SYMBOLS

INTERVAL = "1min"
MAX_RUNTIME = 5 * 3600 + 50 * 60
SCAN_INTERVAL_SECONDS = 15 * 60

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0
state = {s: {"last_candle_time": None} for s in SYMBOLS}
cache = {s: {"price": None, "ema200": None, "updated": None, "closes": None, "emas": None} for s in SYMBOLS}

MAIN_KEYBOARD = {
    "keyboard": [["Current Price", "Auto Strategy"]],
    "resize_keyboard": True,
    "is_persistent": True
}

def is_forex_market_open():
    now = datetime.now(timezone.utc)
    wd = now.weekday()  # 0=Mon ... 5=Sat, 6=Sun
    # Forex/gold: closed from Fri 21:00 UTC to Sun 21:00 UTC (approx standard hours)
    if wd == 5:  # Saturday - always closed
        return False
    if wd == 4 and now.hour >= 21:  # Friday after 21:00 UTC
        return False
    if wd == 6 and now.hour < 21:  # Sunday before 21:00 UTC
        return False
    return True

def get_candles(symbol, size=210):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={INTERVAL}&outputsize={size}&apikey={API_KEY}"
    r = requests.get(url, timeout=15).json()
    if "values" not in r:
        print(f"Candle fetch error for {symbol}: {r}")
        return None
    values = list(reversed(r["values"]))
    closes = [float(v["close"]) for v in values]
    times = [v["datetime"] for v in values]
    return closes, times

def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    out = [e]
    for v in values[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def send_to_me(text, show_keyboard=True):
    payload = {"chat_id": CHAT_ID, "text": text}
    if show_keyboard:
        payload["reply_markup"] = json.dumps(MAIN_KEYBOARD)
    requests.post(f"{TELEGRAM_API}/sendMessage", data=payload)

def send_photo_to_me(path, caption=""):
    with open(path, "rb") as f:
        requests.post(f"{TELEGRAM_API}/sendPhoto", data={"chat_id": CHAT_ID, "caption": caption}, files={"photo": f})

def send_photo_to_channel(path, caption=""):
    with open(path, "rb") as f:
        requests.post(f"{TELEGRAM_API}/sendPhoto", data={"chat_id": CHANNEL_ID, "caption": caption}, files={"photo": f})

def make_chart(symbol, closes, emas, show_ema=True):
    path = "/tmp/chart.png"
    last_n = 60
    c = closes[-last_n:]
    plt.figure(figsize=(8, 4.5), facecolor="#0d1117")
    ax = plt.gca()
    ax.set_facecolor("#0d1117")
    ax.plot(c, color="#4fd1c5", linewidth=1.5, label="Price")
    if show_ema:
        e = emas[-last_n:]
        ax.plot(e, color="#ff5c5c", linewidth=1.5, label="EMA200")
    ax.set_title(f"{symbol} - {INTERVAL}", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")
    ax.legend(facecolor="#131722", labelcolor="white")
    plt.tight_layout()
    plt.savefig(path, facecolor="#0d1117")
    plt.close()
    return path

def get_cached_prices_text():
    lines = []
    for s in SYMBOLS:
        c = cache[s]
        if c["price"] is None:
            lines.append(f"{s}: not fetched yet, wait for next scan")
        else:
            lines.append(f"{s}: price {c['price']} | EMA200 {round(c['ema200'], 5)} | as of {c['updated']}")
    return "Latest cached data (updates every 15 min):\n" + "\n".join(lines)

def get_strategy_status_text():
    fx_status = "OPEN" if is_forex_market_open() else "CLOSED (weekend)"
    return (f"Auto Strategy: ALWAYS ACTIVE ({INTERVAL} timeframe)\n"
            f"Mode: instant channel alert on any EMA200 cross\n"
            f"Crypto watched: {', '.join(CRYPTO_SYMBOLS)} (24/7)\n"
            f"Forex/Gold watched: {', '.join(FOREX_SYMBOLS)} (market {fx_status})\n"
            f"Scan interval: every {SCAN_INTERVAL_SECONDS // 60} min")

def check_updates():
    global last_update_id
    r = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": last_update_id + 1, "timeout": 0}, timeout=10).json()
    for u in r.get("result", []):
        last_update_id = u["update_id"]
        text = u.get("message", {}).get("text", "").strip()
        if text == "/start":
            send_to_me("Princex Strategy bot online. Auto scanning is always running.")
        elif text in ("/price", "Current Price"):
            send_to_me(get_cached_prices_text())
            for s in SYMBOLS:
                c = cache[s]
                if c["closes"]:
                    path = make_chart(s, c["closes"], c["emas"], show_ema=True)
                    send_photo_to_me(path, caption=f"{s} price vs EMA200")
        elif text in ("/status", "Auto Strategy"):
            send_to_me(get_strategy_status_text())

def process_symbol(symbol):
    data = get_candles(symbol)
    if not data:
        return
    closes, times = data
    if len(closes) < 201:
        return

    emas = ema(closes, 200)
    last_close, last_ema = closes[-1], emas[-1]
    cache[symbol] = {"price": last_close, "ema200": last_ema, "updated": times[-1], "closes": closes, "emas": emas}

    st = state[symbol]
    current_candle_time = times[-1]
    if st["last_candle_time"] == current_candle_time:
        return
    st["last_candle_time"] = current_candle_time

    prev_close, prev_ema = closes[-2], emas[-2]
    crossed_up = prev_close < prev_ema and last_close > last_ema
    crossed_down = prev_close > prev_ema and last_close < last_ema
    if crossed_up or crossed_down:
        path = make_chart(symbol, closes, emas, show_ema=False)
        send_photo_to_channel(path, caption=f"GET READY — {symbol} setup forming ({INTERVAL})")

def main():
    start = time.time()
    last_check = 0
    while time.time() - start < MAX_RUNTIME:
        now = time.time()
        if now - last_check >= SCAN_INTERVAL_SECONDS:
            fx_open = is_forex_market_open()
            active_symbols = CRYPTO_SYMBOLS + (FOREX_SYMBOLS if fx_open else [])
            for s in active_symbols:
                try:
                    process_symbol(s)
                except Exception as e:
                    print(f"Error {s}: {e}")
                time.sleep(1)
            send_to_me(get_cached_prices_text() + ("\n\n(Forex/Gold market closed, not scanned)" if not fx_open else ""))
            last_check = now
        try:
            check_updates()
        except Exception as e:
            print(f"Update poll error: {e}")
        time.sleep(3)

if __name__ == "__main__":
    main()
