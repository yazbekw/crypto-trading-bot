import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
from telegram import Bot
import schedule
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import os
from fastapi import FastAPI
import uvicorn
import logging
from datetime import datetime

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# تحميل المتغيرات البيئية
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# إعداد البوت
telegram_bot = Bot(token=TELEGRAM_TOKEN)

# إعداد منصة التداول (Binance كمثال)
exchange = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_API_SECRET,
    'enableRateLimit': True,
})

# قائمة العملات (أكثر 10 عملات موثوقة بناءً على الحجم والتقلب)
SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT', 'XRP/USDT',
    'SOL/USDT', 'DOT/USDT', 'LTC/USDT', 'LINK/USDT', 'MATIC/USDT'
]

# إعداد FastAPI لفحص الصحة
app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# دالة لجلب البيانات
def fetch_ohlcv(symbol, timeframe='1h', limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        return None

# دالة لحساب المؤشرات الفنية
def calculate_indicators(df):
    try:
        # RSI
        df['rsi'] = ta.rsi(df['close'], length=14)
        # MACD
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        df['macd'] = macd['MACD_12_26_9']
        df['macd_signal'] = macd['MACDs_12_26_9']
        # EMA
        df['ema_fast'] = ta.ema(df['close'], length=12)
        df['ema_slow'] = ta.ema(df['close'], length=26)
        # Stochastic
        stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
        df['stoch_k'] = stoch['STOCHk_14_3_3']
        df['stoch_d'] = stoch['STOCHd_14_3_3']
        # Bollinger Bands
        bbands = ta.bbands(df['close'], length=20)
        df['bb_upper'] = bbands['BBU_20_2.0']
        df['bb_lower'] = bbands['BBL_20_2.0']
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {e}")
        return None

# دالة لحساب قوة الإشارة لكل مؤشر
def get_signal_strength(df):
    buy_signals = []
    sell_signals = []

    last_row = df.iloc[-1]

    # 1. RSI
    rsi = last_row['rsi']
    rsi_buy_strength = (rsi - 30) / (70 - 30) * 100 if 30 <= rsi <= 70 else 0
    rsi_sell_strength = (70 - rsi) / (70 - 30) * 100 if 30 <= rsi <= 70 else 0
    if rsi_buy_strength > 50:
        buy_signals.append(('RSI', rsi_buy_strength))
    if rsi_sell_strength > 50:
        sell_signals.append(('RSI', rsi_sell_strength))

    # 2. MACD
    macd = last_row['macd']
    macd_signal = last_row['macd_signal']
    macd_buy_strength = ((macd - macd_signal) / abs(macd_signal) * 100) if macd > macd_signal else 0
    macd_sell_strength = ((macd_signal - macd) / abs(macd_signal) * 100) if macd < macd_signal else 0
    if macd_buy_strength > 50:
        buy_signals.append(('MACD', macd_buy_strength))
    if macd_sell_strength > 50:
        sell_signals.append(('MACD', macd_sell_strength))

    # 3. EMA Crossover
    ema_fast = last_row['ema_fast']
    ema_slow = last_row['ema_slow']
    ema_buy_strength = ((ema_fast - ema_slow) / abs(ema_slow) * 100) if ema_fast > ema_slow else 0
    ema_sell_strength = ((ema_slow - ema_fast) / abs(ema_slow) * 100) if ema_fast < ema_slow else 0
    if ema_buy_strength > 50:
        buy_signals.append(('EMA', ema_buy_strength))
    if ema_sell_strength > 50:
        sell_signals.append(('EMA', ema_sell_strength))

    # 4. Stochastic
    stoch_k = last_row['stoch_k']
    stoch_d = last_row['stoch_d']
    stoch_buy_strength = (stoch_k - 20) / (80 - 20) * 100 if 20 <= stoch_k <= 80 else 0
    stoch_sell_strength = (80 - stoch_k) / (80 - 20) * 100 if 20 <= stoch_k <= 80 else 0
    if stoch_buy_strength > 50:
        buy_signals.append(('Stochastic', stoch_buy_strength))
    if stoch_sell_strength > 50:
        sell_signals.append(('Stochastic', stoch_sell_strength))

    # 5. Bollinger Bands
    close = last_row['close']
    bb_upper = last_row['bb_upper']
    bb_lower = last_row['bb_lower']
    bb_buy_strength = ((close - bb_lower) / (bb_upper - bb_lower) * 100) if close < bb_lower else 0
    bb_sell_strength = ((bb_upper - close) / (bb_upper - bb_lower) * 100) if close > bb_upper else 0
    if bb_buy_strength > 50:
        buy_signals.append(('Bollinger', bb_buy_strength))
    if bb_sell_strength > 50:
        sell_signals.append(('Bollinger', bb_sell_strength))

    # حساب القوة الإجمالية
    buy_total = sum(strength for _, strength in buy_signals) / max(len(buy_signals), 1)
    sell_total = sum(strength for _, strength in sell_signals) / max(len(sell_signals), 1)

    return buy_signals, sell_signals, buy_total, sell_total

# دالة لإرسال إشعار Telegram
async def send_telegram_message(message):
    try:
        await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.info("Telegram message sent successfully")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

# دالة رئيسية لفحص السوق
def check_market():
    logger.info("Starting market check...")
    for symbol in SYMBOLS:
        try:
            df = fetch_ohlcv(symbol)
            if df is None or len(df) < 50:
                continue

            df = calculate_indicators(df)
            if df is None:
                continue

            buy_signals, sell_signals, buy_total, sell_total = get_signal_strength(df)

            # إرسال إشعار إذا كانت القوة > 60%
            if buy_total > 60:
                message = f"📈 Buy Signal for {symbol}\nTotal Strength: {buy_total:.2f}%\nDetails:\n"
                for indicator, strength in buy_signals:
                    message += f"{indicator}: {strength:.2f}%\n"
                asyncio.run(send_telegram_message(message))

            if sell_total > 60:
                message = f"📉 Sell Signal for {symbol}\nTotal Strength: {sell_total:.2f}%\nDetails:\n"
                for indicator, strength in sell_signals:
                    message += f"{indicator}: {strength:.2f}%\n"
                asyncio.run(send_telegram_message(message))

        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")

# إعداد الجدولة
scheduler = AsyncIOScheduler()
scheduler.add_job(check_market, 'interval', minutes=15)
scheduler.start()

# تشغيل FastAPI لفحص الصحة على Render
if __name__ == "__main__":
    logger.info("Starting bot...")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
