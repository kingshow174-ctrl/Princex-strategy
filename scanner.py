import os
import time
import json
import requests

API_KEY = os.environ["TWELVEDATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "XAU/USD"]
INTERVAL = "1min"
MAX_RUNTIME = 5 * 3600 + 50 * 60

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0
state = {s: {"last_candle_time": None} for s in SYMBOLS}

MAIN_KEYBOARD = {
    "keyboard": [["Current Price", "Auto Strategy"]],
    "resize_keyboard": True,
    "is_persistent": True
}

def get_candles(symbol, size=210):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={INTERVAL}&outputsize={size}&apikey={API_KEY}"
    r = requests.get(url, timeout=15).json()
    if "values" not in r:
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

def send_message(text, show_keyboard=True):
    payload = {"chat_id": CHAT_ID, "text": text}
    if show_keyboard:
        payload["reply_markup"] = json.dumps(MAIN_KEYBOARD)
    requests.post(f"{TELEGRAM_API}/sendMessage", data=payload)

def get_live_prices_text():
    lines = []
    for s in SYMBOLS:
        try:
            r = requests.get(f"https://api.twelvedata.com/price?symbol={s}&apikey={API_KEY}", timeout=10).json()
            lines.append(f"{s}: {r.get('price', 'N/A')}")
        except Exception:
            lines.append(f"{s}: error")
    return "Current prices:\n" + "\n".join(lines)

def get_strategy_status_text():
    return (f"Auto Strategy: ALWAYS ACTIVE ({INTERVAL} timeframe)\n"
            f"Mode: instant alert on any EMA200 cross\n"
            f"Markets watched: {', '.join(SYMBOLS)}")

def check_updates():
    global last_update_id
    r = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": last_update_id + 1, "timeout": 0}, timeout=10).json()
    for u in r.get("result", []):
        last_update_id = u["update_id"]
        text = u.get("message", {}).get("text", "").strip()
        if text == "/start":
            send_message("Princex Strategy bot online. Auto scanning is always running.")
        elif text in ("/price", "Current Price"):
            send_message(get_live_prices_text())
        elif text in ("/status", "Auto Strategy"):
            send_message(get_strategy_status_text())

def process_symbol(symbol):
    data = get_candles(symbol)
    if not data:
        return
    closes, times = data
    if len(closes) < 201:
        return

    st = state[symbol]
    current_candle_time = times[-1]

    # only act once per newly closed candle
    if st["last_candle_time"] == current_candle_time:
        return
    st["last_candle_time"] = current_candle_time

    emas = ema(closes, 200)
    prev_close, prev_ema = closes[-2], emas[-2]
    last_close, last_ema = closes[-1], emas[-1]

    if prev_close < prev_ema and last_close > last_ema:
        send_message(f"{symbol} candle crossed ABOVE EMA200 ({INTERVAL})\nClose: {last_close}\nEMA200: {round(last_ema, 5)}")
    elif prev_close > prev_ema and last_close < last_ema:
        send_message(f"{symbol} candle crossed BELOW EMA200 ({INTERVAL})\nClose: {last_close}\nEMA200: {round(last_ema, 5)}")

def main():
    start = time.time()
    last_check = 0
    while time.time() - start < MAX_RUNTIME:
        now = time.time()
        if now - last_check >= 20:
            for s in SYMBOLS:
                try:
                    process_symbol(s)
                except Exception as e:
                    print(f"Error {s}: {e}")
            last_check = now
        try:
            check_updates()
        except Exception as e:
            print(f"Update poll error: {e}")
        time.sleep(3)

if __name__ == "__main__":
    main()
