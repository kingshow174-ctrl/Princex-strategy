import os
import time
import json
import requests

API_KEY = os.environ["TWELVEDATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "XAU/USD"]
INTERVAL = "1min"
CONFIRM_CANDLES = 3
RR_RATIO = 2.5
MAX_RUNTIME = 5 * 3600 + 50 * 60

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0
state = {s: {"in_setup": False, "direction": None, "candles_seen": 0, "swing_price": None} for s in SYMBOLS}

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
    highs = [float(v["high"]) for v in values]
    lows = [float(v["low"]) for v in values]
    return closes, highs, lows

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
    lines = [f"Auto Strategy: ALWAYS ACTIVE ({INTERVAL} timeframe)",
             f"Confirmation: {CONFIRM_CANDLES} candles after EMA200 cross",
             f"Take Profit: 1:{RR_RATIO} risk-reward",
             "Stop Loss: swing high/low at cross point",
             "", "Live setup status:"]
    for s in SYMBOLS:
        st = state[s]
        if st["in_setup"]:
            lines.append(f"{s}: watching {st['direction']} setup ({st['candles_seen']}/{CONFIRM_CANDLES} candles)")
        else:
            lines.append(f"{s}: no active setup")
    return "\n".join(lines)

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
    closes, highs, lows = data
    if len(closes) < 201:
        return
    emas = ema(closes, 200)
    prev_close, prev_ema = closes[-2], emas[-2]
    last_close, last_ema = closes[-1], emas[-1]
    st = state[symbol]

    if not st["in_setup"]:
        if prev_close < prev_ema and last_close > last_ema:
            st.update(in_setup=True, direction="BUY", candles_seen=0, swing_price=lows[-1])
        elif prev_close > prev_ema and last_close < last_ema:
            st.update(in_setup=True, direction="SELL", candles_seen=0, swing_price=highs[-1])
        return

    if st["direction"] == "BUY":
        st["swing_price"] = min(st["swing_price"], lows[-1])
    else:
        st["swing_price"] = max(st["swing_price"], highs[-1])
    st["candles_seen"] += 1

    if st["candles_seen"] >= CONFIRM_CANDLES:
        entry = last_close
        sl = st["swing_price"]
        risk = abs(entry - sl)
        if risk == 0:
            st["in_setup"] = False
            return
        tp = entry + risk * RR_RATIO if st["direction"] == "BUY" else entry - risk * RR_RATIO
        msg = (f"{symbol} {st['direction']} SETUP ({INTERVAL}, EMA200 cross confirmed)\n"
               f"Entry: {entry}\nStop Loss: {sl}\nTake Profit (1:{RR_RATIO}): {round(tp, 5)}\n"
               f"Confirmed after {CONFIRM_CANDLES} candles")
        send_message(msg)
        st["in_setup"] = False

def main():
    start = time.time()
    last_check = 0
    while time.time() - start < MAX_RUNTIME:
        now = time.time()
        if now - last_check >= 60:
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
