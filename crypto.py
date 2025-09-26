import os
import time
import schedule
import pandas as pd
import numpy as np
import ccxt
import telegram
from telegram.error import TelegramError
import logging
from dotenv import load_dotenv
import traceback

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class CryptoSignalBot:
    def __init__(self):
        # إعدادات التلغرام
        self.telegram_token = os.getenv('TELEGRAM_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.bot = telegram.Bot(token=self.telegram_token) if self.telegram_token else None
        
        # إعداد exchange
        self.exchange = ccxt.binance({
            'rateLimit': 1200,
            'enableRateLimit': True,
        })
        
        # قائمة العملات المراقبة
        self.symbols = [
            'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT',
            'SOL/USDT', 'DOT/USDT', 'LTC/USDT', 'LINK/USDT', 'BCH/USDT'
        ]

    def health_check(self):
        """فحص صحة البوت"""
        try:
            if self.bot:
                self.bot.get_me()
            self.exchange.fetch_ticker('BTC/USDT')
            logging.info("فحص الصحة OK")
            return True
        except Exception as e:
            logging.error(f"فشل فحص الصحة: {e}")
            return False

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=50):
        """جلب بيانات السعر"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except Exception as e:
            logging.error(f"خطأ في جلب البيانات لـ {symbol}: {e}")
            return None

    def calculate_rsi(self, df, period=14):
        """حساب RSI"""
        try:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            current_rsi = rsi.iloc[-1]
            
            if current_rsi < 30:
                strength = min(80, (30 - current_rsi) / 30 * 80)
                return {'signal': 'BUY', 'strength': strength}
            elif current_rsi > 70:
                strength = min(80, (current_rsi - 70) / 30 * 80)
                return {'signal': 'SELL', 'strength': strength}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0}
        except Exception as e:
            return None

    def calculate_macd(self, df):
        """حساب MACD"""
        try:
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9).mean()
            histogram = macd - signal
            
            current_hist = histogram.iloc[-1]
            
            if current_hist > 0:
                strength = min(80, abs(current_hist) / df['close'].iloc[-1] * 5000)
                return {'signal': 'BUY', 'strength': strength}
            else:
                strength = min(80, abs(current_hist) / df['close'].iloc[-1] * 5000)
                return {'signal': 'SELL', 'strength': strength}
        except Exception as e:
            return None

    def calculate_bollinger(self, df, period=20):
        """حساب Bollinger Bands"""
        try:
            sma = df['close'].rolling(period).mean()
            std = df['close'].rolling(period).std()
            upper_band = sma + (std * 2)
            lower_band = sma - (std * 2)
            
            current_close = df['close'].iloc[-1]
            
            if current_close <= lower_band.iloc[-1]:
                strength = min(80, ((lower_band.iloc[-1] - current_close) / current_close) * 1000)
                return {'signal': 'BUY', 'strength': strength}
            elif current_close >= upper_band.iloc[-1]:
                strength = min(80, ((current_close - upper_band.iloc[-1]) / current_close) * 1000)
                return {'signal': 'SELL', 'strength': strength}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0}
        except Exception as e:
            return None

    def analyze_symbol(self, symbol):
        """تحليل عملة واحدة"""
        try:
            df = self.fetch_ohlcv(symbol)
            if df is None or len(df) < 20:
                return None
            
            indicators = {
                'rsi': self.calculate_rsi(df),
                'macd': self.calculate_macd(df),
                'bollinger': self.calculate_bollinger(df)
            }
            
            valid_indicators = {}
            total_strength = 0
            buy_signals = 0
            sell_signals = 0
            
            for name, result in indicators.items():
                if result and result['strength'] > 50:
                    valid_indicators[name] = result
                    total_strength += result['strength']
                    
                    if result['signal'] == 'BUY':
                        buy_signals += 1
                    elif result['signal'] == 'SELL':
                        sell_signals += 1
            
            if not valid_indicators:
                return None
            
            overall_strength = total_strength / len(valid_indicators)
            overall_signal = 'BUY' if buy_signals > sell_signals else 'SELL'
            
            return {
                'symbol': symbol,
                'signal': overall_signal,
                'strength': overall_strength,
                'indicators': valid_indicators
            }
            
        except Exception as e:
            logging.error(f"خطأ في تحليل {symbol}: {e}")
            return None

    def send_signal(self, analysis):
        """إرسال الإشارة إلى التلغرام"""
        if not self.bot or not analysis:
            return False
        
        try:
            symbol = analysis['symbol']
            signal = analysis['signal']
            strength = analysis['strength']
            indicators = analysis['indicators']
            
            message = f"🚨 إشارة {signal} 🚨\n"
            message += f"العملة: {symbol}\n"
            message += f"القوة الإجمالية: {strength:.1f}%\n"
            message += f"المؤشرات المشاركة: {len(indicators)}\n\n"
            
            for ind_name, ind_data in indicators.items():
                message += f"• {ind_name}: {ind_data['signal']} ({ind_data['strength']:.1f}%)\n"
            
            message += f"\nالوقت: {time.strftime('%Y-%m-%d %H:%M')}"
            
            self.bot.send_message(chat_id=self.chat_id, text=message)
            logging.info(f"تم إرسال إشارة لـ {symbol}")
            return True
            
        except Exception as e:
            logging.error(f"خطأ في إرسال الرسالة: {e}")
            return False

    def scan_market(self):
        """فحص السوق"""
        try:
            logging.info("بدء فحص السوق...")
            
            if not self.health_check():
                return
            
            for symbol in self.symbols:
                analysis = self.analyze_symbol(symbol)
                if analysis and analysis['strength'] > 60:
                    self.send_signal(analysis)
                    time.sleep(1)
            
            logging.info("اكتمل فحص السوق")
            
        except Exception as e:
            logging.error(f"خطأ في فحص السوق: {e}")

    def run(self):
        """تشغيل البوت"""
        try:
            logging.info("بدء تشغيل بوت الإشارات...")
            
            if not self.telegram_token or not self.chat_id:
                logging.error("لم يتم تعيين إعدادات التلغرام!")
                return
            
            # فحص أولي
            self.scan_market()
            
            # جدولة
            schedule.every(15).minutes.do(self.scan_market)
            
            while True:
                schedule.run_pending()
                time.sleep(60)
                
        except KeyboardInterrupt:
            logging.info("إيقاف البوت...")
        except Exception as e:
            logging.error(f"خطأ غير متوقع: {e}")

if __name__ == "__main__":
    bot = CryptoSignalBot()
    bot.run()
