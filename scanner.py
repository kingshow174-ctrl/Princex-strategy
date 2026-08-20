import os
import requests
import pandas as pd

API_KEY = os.environ["TWELVEDATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "XAU/USD"]
INTERVAL = "15min"

def get_candles(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={INTERVAL}&outputsize=210&apikey={API_KEY}"
    r = requests.get(url, timeout=15).json()
    if "values" not in r:
        print(f"Error fetching {symbol}: {r}")
        return None
    df = pd.DataFrame(r["values"])
    df["close"] = df["close"].astype(float)
    df = df.iloc[::-1].reset_index(drop=True)
    return df

def send_alert(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": message})

def check_cross(symbol):
    df = get_candles(symbol)
    if df is None or len(df) < 201:
        return
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    prev_close, prev_ema = df["close"].iloc[-2], df["ema200"].iloc[-2]
    last_close, last_ema = df["close"].iloc[-1], df["ema200"].iloc[-1]
    if prev_close < prev_ema and last_close > last_ema:
        send_alert(f"UP: {symbol} crossed ABOVE EMA200 ({INTERVAL})\nPrice: {last_close}")
    elif prev_close > prev_ema and last_close < last_ema:
        send_alert(f"DOWN: {symbol} crossed BELOW EMA200 ({INTERVAL})\nPrice: {last_close}")

def main():
    for s in SYMBOLS:
        try:
            check_cross(s)
        except Exception as e:
            print(f"Error on {s}: {e}")

if __name__ == "__main__":
    main()
