from flask import Flask, render_template_string
import threading
import time
import os
import ccxt
import numpy as np
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# --- الثوابت والإعدادات ---
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'LTC/USDT', 'XRP/USDT']
TRADE_AMOUNT_USD = 3.0
BUY_THRESHOLD_RSI = 30
SELL_THRESHOLD_RSI = 70
RSI_PERIOD = 14
API_TIMEOUT = 10  # ثواني

# إعدادات الاستراتيجية الزمنية (بتوقيت دمشق +3 UTC)
# === إعدادات الوقت ===
DAILY_BUY_TIME_RANGE = (5, 9)     # 5am - 9am توقيت دمشق
DAILY_SELL_TIME_RANGE = (15, 21)  # 3pm - 9pm توقيت دمشق
WEEKLY_BUY_DAYS = [0, 1]          # الإثنين والثلاثاء
WEEKLY_SELL_DAYS = [0, 1, 2, 3, 4] # من الإثنين إلى الجمعة

# --- إعدادات التسجيل ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)

# --- تهيئة الحالة ---
bot_status = {symbol: "انتظار" for symbol in SYMBOLS}
last_price = {symbol: None for symbol in SYMBOLS}
last_rsi = {symbol: None for symbol in SYMBOLS}
trade_history = []  # سجل موحد لجميع الصفقات
prices = {symbol: [] for symbol in SYMBOLS}
total_balance_usdt = 9.85
profits_usdt = 0.0

print(f"Buy Time Range: {DAILY_BUY_TIME_RANGE}")
print(f"Sell Time Range: {DAILY_SELL_TIME_RANGE}")
print(f"Sell Days: {WEEKLY_SELL_DAYS}")

# --- اتصال CoinEx مع وقت انتظار أقصر ---
exchange = ccxt.coinex({
    'apiKey': os.getenv('COINEX_API_KEY'),
    'secret': os.getenv('COINEX_SECRET_KEY'),
    'enableRateLimit': True,
    'timeout': API_TIMEOUT * 1000,  # تحويل إلى ميلي ثانية
    'options': {
        'adjustForTimeDifference': True,
    }
})

# --- الدوال المساعدة ---
def get_damascus_time():
    """الحصول على الوقت الحالي بتوقيت دمشق (UTC+3)"""
    return datetime.now(timezone.utc) + timedelta(hours=3)

def is_time_to_trade():
    """تحديد إذا كان الوقت مناسبًا للتداول حسب الاستراتيجية الزمنية"""
    now = get_damascus_time()
    current_hour = now.hour
    current_day = now.weekday()
    
    # شرط الشراء
    if (current_day in WEEKLY_BUY_DAYS and 
        DAILY_BUY_TIME_RANGE[0] <= current_hour < DAILY_BUY_TIME_RANGE[1]):
        return 'buy'
    
    # شرط البيع (المضاف حديثاً)
    if (current_day in WEEKLY_SELL_DAYS and 
        DAILY_SELL_TIME_RANGE[0] <= current_hour < DAILY_SELL_TIME_RANGE[1]):
        return 'sell'
    
    return None

def calculate_rsi(prices, period=RSI_PERIOD):
    """حساب مؤشر القوة النسبية"""
    if len(prices) < period:
        return None
    
    deltas = np.diff(prices)
    gains = deltas[deltas >= 0]
    losses = -deltas[deltas < 0]
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period]) if len(losses) > 0 else 0
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def execute_trade(symbol, side):
    """تنفيذ الصفقة مع تحديث الرصيد والأرباح"""
    global total_balance_usdt, profits_usdt
    
    try:
        price = last_price[symbol]
        if not price:
            logging.error(f"لا يوجد سعر لـ {symbol}")
            return False

        amount = TRADE_AMOUNT_USD / price
        
        order = exchange.create_order(
            symbol=symbol,
            type='limit',
            side=side,
            amount=amount,
            price=price
        )
        
        # تحديث الرصيد والأرباح
        if side == 'buy':
            total_balance_usdt -= TRADE_AMOUNT_USD
            log_msg = f"شراء {amount:.6f} {symbol.split('/')[0]} بالسعر {price:.2f}"
        else:
            profit = (price * amount) - TRADE_AMOUNT_USD
            total_balance_usdt += TRADE_AMOUNT_USD
            profits_usdt += profit
            log_msg = f"بيع {amount:.6f} {symbol.split('/')[0]} بالسعر {price:.2f} | ربح: {profit:.2f} USDT"
        
        # تسجيل الصفقة
        trade_history.append({
            "symbol": symbol,
            "type": side,
            "price": price,
            "amount": amount,
            "time": get_damascus_time().strftime("%Y-%m-%d %H:%M:%S (توقيت دمشق)")
        })
        
        if len(trade_history) > 50:  # حفظ آخر 50 صفقة فقط
            trade_history.pop(0)
            
        logging.info(log_msg)
        return True
    except Exception as e:
        logging.error(f"فشل تنفيذ الصفقة: {str(e)}")
        return False

def trading_bot_loop(symbol):
    """الحلقة الرئيسية للتداول"""
    while True:
        try:
            # جلب البيانات
            ticker = exchange.fetch_ticker(symbol)
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=RSI_PERIOD+1)
            
            if not ticker or not ohlcv:
                time.sleep(60)
                continue
                
            # تحديث السعر
            price = ticker['last']
            last_price[symbol] = price
            prices[symbol].append(price)
            
            # حساب RSI
            rsi = None
            if len(prices[symbol]) >= RSI_PERIOD+1:
                closes = [x[4] for x in ohlcv]
                rsi = calculate_rsi(closes)
                last_rsi[symbol] = rsi
            
            # تحديد الإجراء
            # في داخل trading_bot_loop():
            trade_action = is_time_to_trade()

            if trade_action == 'buy' and (rsi is None or rsi < BUY_THRESHOLD_RSI):
                if execute_trade(symbol, 'buy'):
                    bot_status[symbol] = "شراء (استراتيجية زمنية)"

            elif trade_action == 'sell' and (rsi is None or rsi > SELL_THRESHOLD_RSI):
                if execute_trade(symbol, 'sell'):
                    bot_status[symbol] = "بيع (استراتيجية زمنية)"
            
            elif rsi and rsi < BUY_THRESHOLD_RSI:
                if execute_trade(symbol, 'buy'):
                    bot_status[symbol] = "شراء (إشارة RSI)"
            
            elif rsi and rsi > SELL_THRESHOLD_RSI:
                if execute_trade(symbol, 'sell'):
                    bot_status[symbol] = "بيع (إشارة RSI)"
            
            else:
                bot_status[symbol] = "انتظار"
            
            time.sleep(60)
        except Exception as e:
            logging.error(f"خطأ في البوت: {str(e)}")
            time.sleep(60)

# --- واجهة الويب المحسنة ---
@app.route('/')
def dashboard():
    damascus_time = get_damascus_time()
    current_strategy = {
        'buy_time_active': (damascus_time.weekday() in WEEKLY_BUY_DAYS and 
                          DAILY_BUY_TIME_RANGE[0] <= damascus_time.hour < DAILY_BUY_TIME_RANGE[1]),
        'sell_time_active': (damascus_time.weekday() in WEEKLY_SELL_DAYS and 
                           DAILY_SELL_TIME_RANGE[0] <= damascus_time.hour < DAILY_SELL_TIME_RANGE[1]),
        'current_time': damascus_time.strftime("%Y-%m-%d %H:%M:%S (توقيت دمشق)"),
        'current_day': ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'][damascus_time.weekday()],
        'buy_days': "الإثنين والثلاثاء",
        'sell_days': "من الإثنين إلى الجمعة",
        'buy_time': f"{DAILY_BUY_TIME_RANGE[0]}:00-{DAILY_BUY_TIME_RANGE[1]}:00",
        'sell_time': f"{DAILY_SELL_TIME_RANGE[0]}:00-{DAILY_SELL_TIME_RANGE[1]}:00"
    }
    
    symbols_data = []
    for symbol in SYMBOLS:
        symbols_data.append({
            "symbol": symbol,
            "price": last_price.get(symbol, 0),  # 0 كقيمة افتراضية
            "rsi": f"{last_rsi[symbol]:.2f}" if symbol in last_rsi and last_rsi[symbol] is not None else "غير متاح",
            "status": bot_status.get(symbol, "جاري التحميل...")
        })
    
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>بوت تداول العملات الرقمية</title>
        <meta http-equiv="refresh" content="10">
        <style>
            :root {
                --primary-color: #4361ee;
                --secondary-color: #3f37c9;
                --success-color: #4cc9f0;
                --danger-color: #f72585;
                --warning-color: #f8961e;
                --light-color: #f8f9fa;
                --dark-color: #212529;
            }
            body {
                font-family: 'Tajawal', Arial, sans-serif;
                background-color: #f5f7fa;
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            .header {
                background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
                color: white;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }
            .dashboard-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
            }
            .card {
                background-color: white;
                border-radius: 10px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            }
            .strategy-card {
                background-color: #e6f7ff;
                border-left: 4px solid var(--primary-color);
            }
            .performance-card {
                background-color: #f0fff4;
                border-left: 4px solid var(--success-color);
            }
            .symbols-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }
            .symbol-card {
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
                transition: transform 0.2s;
            }
            .symbol-card:hover {
                transform: translateY(-5px);
            }
            .symbol-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
                padding-bottom: 10px;
                border-bottom: 1px solid #eee;
            }
            .symbol-name {
                font-weight: bold;
                font-size: 1.2rem;
                color: var(--dark-color);
            }
            .symbol-price {
                font-size: 1.1rem;
                font-weight: bold;
            }
            .symbol-rsi {
                padding: 5px 10px;
                border-radius: 20px;
                font-weight: bold;
                font-size: 0.9rem;
                background-color: #f0f0f0;
            }
            .rsi-low {
                background-color: #d4edda;
                color: #155724;
            }
            .rsi-high {
                background-color: #f8d7da;
                color: #721c24;
            }
            .symbol-status {
                padding: 5px 10px;
                border-radius: 20px;
                font-weight: bold;
                font-size: 0.9rem;
            }
            .status-waiting {
                background-color: #e2e3e5;
                color: #383d41;
            }
            .status-buy {
                background-color: #d4edda;
                color: #155724;
            }
            .status-sell {
                background-color: #f8d7da;
                color: #721c24;
            }
            .trades-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
                background-color: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            }
            .trades-table th {
                background-color: var(--primary-color);
                color: white;
                padding: 12px;
                text-align: center;
            }
            .trades-table td {
                padding: 12px;
                text-align: center;
                border-bottom: 1px solid #eee;
            }
            .trades-table tr:hover {
                background-color: #f5f5f5;
            }
            .trade-buy {
                color: var(--success-color);
                font-weight: bold;
            }
            .trade-sell {
                color: var(--danger-color);
                font-weight: bold;
            }
            .active-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 5px;
            }
            .active-true {
                background-color: var(--success-color);
            }
            .active-false {
                background-color: var(--danger-color);
            }
            h1, h2, h3 {
                color: var(--dark-color);
                margin-top: 0;
            }
            .last-updated {
                text-align: left;
                font-size: 0.9rem;
                color: #6c757d;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>بوت التداول الآلي - CoinEx</h1>
                <p>توقيت السيرفر: {{ current_strategy.current_time }}</p>
            </div>
            
            <div class="dashboard-grid">
                <div class="card strategy-card">
                    <h2>إعدادات الاستراتيجية</h2>
                    <p>
                        <span class="active-indicator active-{{ current_strategy.buy_time_active|lower }}"></span>
                        <strong>أوقات الشراء:</strong> 
                        {{ current_strategy.buy_days }} من {{ current_strategy.buy_time }}
                        <span class="status-{{ 'buy' if current_strategy.buy_time_active else 'waiting' }}">
                            ({{ 'نشط الآن' if current_strategy.buy_time_active else 'غير نشط' }})
                        </span>
                    </p>
                    <p>
                        <span class="active-indicator active-{{ current_strategy.sell_time_active|lower }}"></span>
                        <strong>أوقات البيع:</strong> 
                        {{ current_strategy.sell_days }} من {{ current_strategy.sell_time }}
                        <span class="status-{{ 'sell' if current_strategy.sell_time_active else 'waiting' }}">
                            ({{ 'نشط الآن' if current_strategy.sell_time_active else 'غير نشط' }})
                        </span>
                    </p>
                    <p><strong>حجم الصفقة:</strong> {{ "%.2f"|format(trade_amount) }} USDT</p>
                </div>
                <div class="card performance-card">
                    <h2>الأداء المالي</h2>
                    <p><strong>الرصيد الحالي:</strong> {{ "%.2f"|format(total_balance_usdt) }} USDT</p>
                    <p><strong>الأرباح الإجمالية:</strong> <span style="color: {{ 'green' if profits_usdt >= 0 else 'red' }}">{{ "%.2f"|format(profits_usdt) }} USDT</span></p>
                    <p><strong>عدد الصفقات:</strong> {{ trade_history|length }}</p>
                </div>
            </div>
            
            <div class="symbols-grid">
                {% for symbol in symbols_data %}
                <div class="symbol-card">
                    <div class="symbol-header">
                        <span class="symbol-name">{{ symbol.symbol }}</span>
                        <span class="symbol-price">{{ "%.4f"|format(symbol.price) if symbol.price else 'جاري التحميل...' }}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 10px;">
                        <div>
                            <span>مؤشر RSI:</span>
                            <span class="symbol-rsi {% if symbol.rsi != 'جاري التحميل...' and symbol.rsi|float < 30 %}rsi-low{% elif symbol.rsi != 'جاري التحميل...' and symbol.rsi|float > 70 %}rsi-high{% endif %}">
                                {{ symbol.rsi }}
                            </span>
                        </div>
                        <div>
                            <span>الحالة:</span>
                            <span class="symbol-status status-{{ symbol.status.split(' ')[0]|lower if symbol.status else 'waiting' }}">
                                {{ symbol.status if symbol.status else 'جاري التحميل...' }}
                            </span>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
            
            <div class="card">
                <h2>سجل الصفقات</h2>
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>الوقت</th>
                            <th>العملة</th>
                            <th>النوع</th>
                            <th>الكمية</th>
                            <th>السعر</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for trade in trade_history|reverse %}
                        <tr>
                            <td>{{ trade.time }}</td>
                            <td>{{ trade.symbol }}</td>
                            <td class="trade-{{ trade.type }}">{{ trade.type }}</td>
                            <td>{{ "%.6f"|format(trade.amount) }}</td>
                            <td>{{ "%.4f"|format(trade.price) }}</td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="5" style="text-align: center;">لا توجد صفقات مسجلة بعد</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="last-updated">
                آخر تحديث: {{ current_strategy.current_time }}
            </div>
        </div>
    </body>
    </html>
    ''', symbols_data=symbols_data, total_balance_usdt=total_balance_usdt, 
    profits_usdt=profits_usdt, trade_amount=TRADE_AMOUNT_USD, 
    current_strategy=current_strategy, trade_history=trade_history)

if __name__ == '__main__':
    # اختبار اتصال سريع (5 ثواني بدلاً من 30)
    exchange.options['timeout'] = 5000  # 5 ثواني
    
    try:
        logging.info("جاري اختبار اتصال سريع بـ CoinEx...")
        start_time = time.time()
        exchange.fetch_balance()
        logging.info(f"تم الاتصال بنجاح خلال {time.time()-start_time:.2f} ثانية")
    except Exception as e:
        logging.error(f"فشل الاتصال: {str(e)}")
        exit(1)

    # استعادة وقت الانتظار الأصلي
    exchange.options['timeout'] = API_TIMEOUT * 1000
    
    # بدء خيوط التداول
    for symbol in SYMBOLS:
        threading.Thread(target=trading_bot_loop, args=(symbol,), daemon=True).start()
    
    # تشغيل الخادم
    try:
        logging.info("جاري تشغيل الخادم على http://localhost:5000")
        app.run(host='0.0.0.0', port=5000, use_reloader=False)
    except Exception as e:
        logging.error(f"خطأ في الخادم: {str(e)}")