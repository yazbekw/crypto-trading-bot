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
            
            high_26 = df['high'].rolling(26).max()
            low_26 = df['low'].rolling(26).min()
            kijun_sen = (high_26 + low_26) / 2
            
            senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)
            
            high_52 = df['high'].rolling(52).max()
            low_52 = df['low'].rolling(52).min()
            senkou_span_b = ((high_52 + low_52) / 2).shift(26)
            
            current_close = df['close'].iloc[-1]
            current_tenkan = tenkan_sen.iloc[-1]
            current_kijun = kijun_sen.iloc[-1]
            
            if current_close > current_tenkan and current_tenkan > current_kijun:
                strength = min(100, abs(current_close - current_tenkan) / current_close * 1000)
                return {'signal': 'BUY', 'strength': strength, 'value': current_tenkan}
            elif current_close < current_tenkan and current_tenkan < current_kijun:
                strength = min(100, abs(current_close - current_tenkan) / current_close * 1000)
                return {'signal': 'SELL', 'strength': strength, 'value': current_tenkan}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0, 'value': current_tenkan}
                
        except Exception as e:
            logging.error(f"خطأ في حساب Ichimoku: {e}")
            return None

    def calculate_stochastic(self, df):
        """حساب Stochastic"""
        try:
            low_14 = df['low'].rolling(14).min()
            high_14 = df['high'].rolling(14).max()
            k_percent = 100 * ((df['close'] - low_14) / (high_14 - low_14))
            d_percent = k_percent.rolling(3).mean()
            
            current_k = k_percent.iloc[-1]
            current_d = d_percent.iloc[-1]
            
            if current_k < 20 and current_d < 20:
                strength = min(100, (20 - min(current_k, current_d)) / 20 * 100)
                return {'signal': 'BUY', 'strength': strength, 'value': current_k}
            elif current_k > 80 and current_d > 80:
                strength = min(100, (max(current_k, current_d) - 80) / 20 * 100)
                return {'signal': 'SELL', 'strength': strength, 'value': current_k}
            else:
                return {'signal': 'NEUTRAL', 'strength': 0, 'value': current_k}
                
        except Exception as e:
            logging.error(f"خطأ في حساب Stochastic: {e}")
            return None

    def analyze_symbol(self, symbol):
        """تحليل عملة واحدة"""
        try:
            df = self.fetch_ohlcv(symbol)
            if df is None or len(df) < 100:
                return None
            
            indicator_results = {}
            valid_indicators = 0
            total_strength = 0
            buy_signals = 0
            sell_signals = 0
            
            for indicator_name, indicator_func in self.indicators.items():
                result = indicator_func(df)
                if result and result['strength'] > 50:
                    indicator_results[indicator_name] = result
                    total_strength += result['strength']
                    valid_indicators += 1
                    
                    if result['signal'] == 'BUY':
                        buy_signals += 1
                    elif result['signal'] == 'SELL':
                        sell_signals += 1
            
            if valid_indicators == 0:
                return None
            
            overall_strength = total_strength / valid_indicators
            overall_signal = 'BUY' if buy_signals > sell_signals else 'SELL'
            
            return {
                'symbol': symbol,
                'signal': overall_signal,
                'strength': overall_strength,
                'indicators': indicator_results,
                'valid_indicators': valid_indicators
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
            
            message = f"🚨 **إشارة {signal}** 🚨\n"
            message += f"**العملة:** {symbol}\n"
            message += f"**القوة الإجمالية:** {strength:.2f}%\n"
            message += f"**عدد المؤشرات المشاركة:** {len(indicators)}\n\n"
            message += "**تفاصيل المؤشرات:**\n"
            
            for ind_name, ind_data in indicators.items():
                message += f"• {ind_name.upper()}: {ind_data['signal']} ({ind_data['strength']:.2f}%)\n"
            
            message += f"\n⏰ الوقت: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            
            logging.info(f"تم إرسال إشارة لـ {symbol}")
            return True
            
        except TelegramError as e:
            logging.error(f"خطأ في إرسال الرسالة: {e}")
            return False
        except Exception as e:
            logging.error(f"خطأ غير متوقع في الإرسال: {e}")
            return False

    def send_alert(self, message):
        """إرسال تنبيه إلى التلغرام"""
        if not self.bot:
            return False
        
        try:
            self.bot.send_message(
                chat_id=self.chat_id,
                text=f"⚠️ {message}"
            )
            return True
        except Exception as e:
            logging.error(f"خطأ في إرسال التنبيه: {e}")
            return False

    def scan_market(self):
        """فحص السوق الرئيسي"""
        try:
            logging.info("بدء فحص السوق...")
            
            # فحص الصحة أولاً
            if not self.health_check():
                logging.warning("فحص الصحة فشل، تأجيل الفحص")
                return
            
            strong_signals = []
            
            for symbol in self.symbols:
                analysis = self.analyze_symbol(symbol)
                if analysis and analysis['strength'] > 60:
                    strong_signals.append(analysis)
            
            # إرسال الإشارات القوية
            for signal in strong_signals:
                self.send_signal(signal)
                time.sleep(1)  # تجنب rate limiting
            
            logging.info(f"اكتمل الفحص. تم العثور على {len(strong_signals)} إشارة قوية")
            
        except Exception as e:
            logging.error(f"خطأ في فحص السوق: {e}")
            traceback.print_exc()

    def run(self):
        """تشغيل البوت"""
        try:
            logging.info("بدء تشغيل بوت الإشارات...")
            
            # فحص الإعدادات
            if not self.telegram_token or not self.chat_id:
                logging.error("لم يتم تعيين إعدادات التلغرام!")
                return
            
            # جدولة المهام
            schedule.every(15).minutes.do(self.scan_market)
            schedule.every(5).minutes.do(self.health_check)
            
            # فحص أولي
            self.scan_market()
            
            # التشغيل المستمر
            while True:
                schedule.run_pending()
                time.sleep(1)
                
        except KeyboardInterrupt:
            logging.info("إيقاف البوت...")
        except Exception as e:
            logging.error(f"خطأ غير متوقع: {e}")
            traceback.print_exc()

def main():
    """الدالة الرئيسية"""
    bot = CryptoSignalBot()
    bot.run()

if __name__ == "__main__":
    main()
