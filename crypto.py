import os
import time
import schedule
import pandas as pd
import numpy as np
import ccxt
from telegram import Bot
from telegram.error import TelegramError
import logging
from dotenv import load_dotenv
import traceback

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

class CryptoSignalBot:
    def __init__(self):
        # إعدادات التلغرام
        self.telegram_token = os.getenv('TELEGRAM_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.bot = Bot(token=self.telegram_token) if self.telegram_token else None
        
        # إعداد exchange
        self.exchange = ccxt.binance({
            'rateLimit': 1200,
            'enableRateLimit': True,
            'timeout': 30000,
        })
        
        # قائمة العملات المراقبة
        self.symbols = [
            'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT',
            'SOL/USDT', 'DOT/USDT', 'LTC/USDT', 'LINK/USDT', 'BCH/USDT'
        ]
        
        # إعدادات المؤشرات
        self.indicators = {
            'macd': self.calculate_macd,
            'rsi': self.calculate_rsi,
            'bollinger': self.calculate_bollinger,
            'ichimoku': self.calculate_ichimoku,
            'stochastic': self.calculate_stochastic
        }
        
        # إعدادات الفحص الصحي
        self.health_check_interval = 300  # 5 دقائق
        self.last_health_check = time.time()
        self.error_count = 0
        self.max_errors = 5

    def health_check(self):
        """فحص صحة البوت والاتصالات"""
        try:
            current_time = time.time()
            
            # فحص اتصال التلغرام
            if self.bot:
                self.bot.get_me()
            
            # فحص اتصال exchange
            self.exchange.fetch_ticker('BTC/USDT')
            
            # فحص الوقت منذ آخر فحص صحي
            if current_time - self.last_health_check > self.health_check_interval * 2:
                logging.warning("تأخر في الفحوصات الصحية")
                self.error_count += 1
            else:
                self.error_count = max(0, self.error_count - 1)
            
            self.last_health_check = current_time
            
            if self.error_count >= self.max_errors:
                self.send_alert("⚠️ البوت يعاني من مشاكل متكررة. يلزم التدخل الفوري!")
                self.error_count = 0
            
            logging.info("فحص الصحة OK")
            return True
            
        except Exception as e:
            logging.error(f"فشل فحص الصحة: {e}")
            self.error_count += 1
            return False

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=100):
        """جلب بيانات OHLCV"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logging.error(f"خطأ في جلب البيانات لـ {symbol}: {e}")
            return None

    def calculate_macd(self, df):
        """حساب مؤشر MACD"""
        try:
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9).mean()
            histogram = macd - signal
            
            # حساب قوة الإشارة
            current_macd = macd.iloc[-1]
            current_signal = signal.iloc[-1]
            current_hist = histogram.iloc[-1]
            
            if current_macd > current_signal and current_hist > 0:
                strength = min(100, abs(current_hist) / df['close'].iloc[-1] * 1000)
                return {'signal': 'BUY', 'strength': strength, 'value': current_macd}
            else:
                strength = min(100, abs(current_hist) / df['close'].iloc[-1] * 1000)
                return {'signal': 'SELL', 'strength': strength, 'value': current_macd}
                
        except Exception as e:
            logging.error(f"خطأ في حساب MACD: {e}")
            return None

    def calculate_rsi(self, df, period=14):
        """حساب مؤشر RSI"""
        try:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            current_rsi = rsi.iloc[-1]
            
            if current_rsi < 30:
                strength = min(100, (30 - current_rsi) / 30 * 100)
                return {'signal': 'BUY', 'strength': strength, 'value': current_rsi}
            elif current_rsi > 70:
                strength = min(100, (current_rsi - 70) / 30 * 100)
                return {'signal': 'SELL', 'strength': strength, 'value': current_rsi}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0, 'value': current_rsi}
                
        except Exception as e:
            logging.error(f"خطأ في حساب RSI: {e}")
            return None

    def calculate_bollinger(self, df, period=20):
        """حساب Bollinger Bands"""
        try:
            sma = df['close'].rolling(period).mean()
            std = df['close'].rolling(period).std()
            upper_band = sma + (std * 2)
            lower_band = sma - (std * 2)
            
            current_close = df['close'].iloc[-1]
            current_upper = upper_band.iloc[-1]
            current_lower = lower_band.iloc[-1]
            current_sma = sma.iloc[-1]
            
            if current_close <= current_lower:
                strength = min(100, ((current_lower - current_close) / current_close) * 1000)
                return {'signal': 'BUY', 'strength': strength, 'value': current_close}
            elif current_close >= current_upper:
                strength = min(100, ((current_close - current_upper) / current_close) * 1000)
                return {'signal': 'SELL', 'strength': strength, 'value': current_close}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0, 'value': current_close}
                
        except Exception as e:
            logging.error(f"خطأ في حساب Bollinger Bands: {e}")
            return None

    def calculate_ichimoku(self, df):
        """حساب إيشيموكو"""
        try:
            # حساب مكونات إيشيموكو
            high_9 = df['high'].rolling(9).max()
            low_9 = df['low'].rolling(9).min()
            tenkan_sen = (high_9 + low_9) / 2
            
            high_26 = df['
