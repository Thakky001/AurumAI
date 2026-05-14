import os
import time
import logging
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
import gradio as gr

from smc_detector      import SMCDetector
from sentiment_analyzer import SentimentAnalyzer

# ─── Logging ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── ENV ────────────────────────────────────────
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")

# ─── Config ─────────────────────────────────────
SYMBOL         = "XAU/USD"
INTERVAL       = "15min"   # M15 — ต้องการ HTF H4 (resample ในโค้ด)
OUTPUT_SIZE    = 200        # 200 × 15min = ~50 ชั่วโมง → ~12 แท่ง H4
POLL_SECONDS   = 60

# London + NY  →  UTC 07:00–19:00  (ไทย 14:00–02:00)
SESSION_START  = 7
SESSION_END    = 19

# Sentiment refresh ทุก 15 นาที (ประหยัด RSS call)
SENTIMENT_REFRESH_MIN = 15

# ─── Shared State ───────────────────────────────
log_lines      = []
signal_history = []
current_sentiment = {"score": 0.0, "label": "NEUTRAL", "headlines": 0}
last_sentiment_time = None
bot_status     = "⏳ Starting..."

# ─── Session Notification State ─────────────────
session_started_today = False   # ส่งแจ้งเตือน "เริ่ม" ไปแล้วมั้ย
session_ended_today   = False   # ส่งแจ้งเตือน "หยุด" ไปแล้วมั้ย
last_notify_date      = None    # วันที่ส่งล่าสุด (reset ทุกวัน)

detector  = SMCDetector(ob_lookback=20, fvg_threshold=0.3,
                        wick_ratio=1.5, swing_bars=5, rr_ratio=2.0)
analyzer  = SentimentAnalyzer()   # โหลด FinBERT ตอน startup

# ─── Helpers ────────────────────────────────────
def add_log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_lines.append(line)
    if len(log_lines) > 200:
        log_lines.pop(0)
    log.info(msg)

def is_session_active() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return SESSION_START <= now.hour < SESSION_END

def should_refresh_sentiment() -> bool:
    global last_sentiment_time
    if last_sentiment_time is None:
        return True
    diff = (datetime.now(timezone.utc) - last_sentiment_time).seconds / 60
    return diff >= SENTIMENT_REFRESH_MIN

def fetch_ohlcv() -> pd.DataFrame | None:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol":     SYMBOL,
        "interval":   INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "apikey":     TWELVE_API_KEY,
        "format":     "JSON",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            add_log(f"⚠️ API: {data.get('message')}")
            return None
        df = pd.DataFrame(data.get("values", []))
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        add_log(f"❌ Fetch error: {e}")
        return None

def send_telegram_notify(text: str) -> bool:
    """ส่งข้อความ System Notification ไป Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url,
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                          timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        add_log(f"❌ Notify error: {e}")
        return False

def notify_session_start():
    now = datetime.now(timezone.utc)
    thai = now.hour + 7
    if thai >= 24:
        thai -= 24
    text = (
        f"🟢 <b>Bot เริ่มทำงานแล้ว</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>เวลา:</b> {thai:02d}:{now.minute:02d} น. (ไทย)\n"
        f"📡 <b>Session:</b> London + New York\n"
        f"⏱ <b>Scan:</b> ทุก 1 นาที (M15 Entry / H4 Zone)\n"
        f"🧠 <b>Sentiment:</b> {current_sentiment['label']} "
        f"({current_sentiment['score']:+.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Bot จะส่งสัญญาณเมื่อ SMC + Sentiment ตรงกัน</i>"
    )
    send_telegram_notify(text)
    add_log("📨 Session START notification sent")

def notify_session_end():
    now = datetime.now(timezone.utc)
    thai = now.hour + 7
    if thai >= 24:
        thai -= 24
    total = len(signal_history)
    today_signals = [s for s in signal_history
                     if s.get("time", "") != ""]
    text = (
        f"🔴 <b>Bot หยุดทำงานแล้ว</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>เวลา:</b> {thai:02d}:{now.minute:02d} น. (ไทย)\n"
        f"📊 <b>สัญญาณวันนี้:</b> {total} สัญญาณ\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Bot จะเริ่มใหม่พรุ่งนี้ 14:00 น. (London Open)</i>"
    )
    send_telegram_notify(text)
    add_log("📨 Session END notification sent")

def send_telegram(signal: dict, sentiment: dict) -> bool:
    action = signal["action"]
    emoji  = "🟢" if action == "BUY" else "🔴"
    s_emoji = "📈" if sentiment["label"] == "BULLISH" else \
              "📉" if sentiment["label"] == "BEARISH" else "➡️"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    text = (
        f"{emoji} <b>XAUUSD — {action}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Zone:</b>      {signal['zone']}\n"
        f"🛡 <b>SL:</b>        {signal['sl']}\n"
        f"🎯 <b>TP:</b>        {signal['tp']}\n"
        f"📊 <b>RR:</b>        {signal['rr']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>Pattern:</b>   {signal['pattern']}\n"
        f"🏛 <b>HTF Zone:</b>  {signal['htf_zone']}\n"
        f"📐 <b>Structure:</b> {signal['structure']}\n"
        f"⏱ <b>TF:</b>        M15 Entry / H4 Zone\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{s_emoji} <b>Sentiment:</b> {sentiment['label']} "
        f"({sentiment['score']:+.2f})\n"
        f"📰 <b>News:</b>      {sentiment['headlines']} headlines\n"
        f"🕐 <i>{now}</i>"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url,
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                          timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        add_log(f"❌ Telegram: {e}")
        return False

# ─── Main Bot Loop ───────────────────────────────
def run_bot():
    global bot_status, current_sentiment, last_sentiment_time
    global session_started_today, session_ended_today, last_notify_date

    add_log("🚀 Gold Market AI Analyzer started (M15 Entry / H4 Zone)")
    add_log("🤖 FinBERT model ready")
    bot_status = "🟢 Running"

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            today   = now_utc.date()

            # ── Reset flags ทุกวัน ──
            if last_notify_date != today:
                session_started_today = False
                session_ended_today   = False
                last_notify_date      = today
                add_log("🔄 Daily flags reset")

            # ── นอก Session ──
            if not is_session_active():
                bot_status = "⏸ Outside London/NY Session"

                # ส่งแจ้งเตือน "หยุด" ครั้งเดียวต่อวัน
                if session_started_today and not session_ended_today:
                    notify_session_end()
                    session_ended_today = True

                add_log("⏸ Outside session — waiting 5 min...")
                time.sleep(300)
                continue

            # ── ใน Session ──
            # ส่งแจ้งเตือน "เริ่ม" ครั้งเดียวต่อวัน
            if not session_started_today:
                # Refresh sentiment ก่อนแจ้งเตือน
                current_sentiment   = analyzer.get_sentiment()
                last_sentiment_time = now_utc
                notify_session_start()
                session_started_today = True

            bot_status = "🟢 Scanning (London/NY Session)"

            # ── Refresh Sentiment ──
            if should_refresh_sentiment():
                add_log("🧠 Refreshing sentiment...")
                current_sentiment   = analyzer.get_sentiment()
                last_sentiment_time = datetime.now(timezone.utc)
                add_log(
                    f"🧠 Sentiment: {current_sentiment['label']} "
                    f"({current_sentiment['score']:+.3f}) "
                    f"from {current_sentiment['headlines']} headlines"
                )

            # ── Fetch Price ──
            df = fetch_ohlcv()
            if df is None or df.empty:
                add_log("⚠️ No price data")
                time.sleep(POLL_SECONDS)
                continue

            last_price = df["close"].iloc[-1]

            # ── SMC Analysis ──
            signal = detector.analyze(df)

            if signal:
                # ── Sentiment Alignment Check ──
                aligned = analyzer.is_aligned(signal["action"], current_sentiment)
                add_log(
                    f"🎯 Signal: {signal['action']} @ {signal['zone']} | "
                    f"Sentiment: {current_sentiment['label']} | "
                    f"Aligned: {'✅' if aligned else '❌'}"
                )

                if aligned:
                    ok = send_telegram(signal, current_sentiment)
                    status = "✅ Sent" if ok else "❌ Failed"
                    add_log(f"📨 Telegram {status}")

                    signal_history.append({
                        "time":      datetime.now(timezone.utc).strftime("%H:%M"),
                        "action":    signal["action"],
                        "zone":      signal["zone"],
                        "sl":        signal["sl"],
                        "tp":        signal["tp"],
                        "sentiment": current_sentiment["label"],
                        "sent":      ok,
                    })
                    if len(signal_history) > 50:
                        signal_history.pop(0)
                else:
                    add_log(
                        f"🚫 Signal blocked — SMC={signal['action']} "
                        f"vs Sentiment={current_sentiment['label']}"
                    )
            else:
                add_log(
                    f"🔍 Scanning... price={last_price:.2f} | "
                    f"Sentiment={current_sentiment['label']}"
                )

        except Exception as e:
            add_log(f"❌ Loop error: {e}")
            bot_status = f"⚠️ Error: {e}"

        time.sleep(POLL_SECONDS)

# ─── Gradio UI ───────────────────────────────────
def get_logs():
    return "\n".join(reversed(log_lines[-50:])) if log_lines else "Starting..."

def get_status():
    s = current_sentiment
    return (
        f"**Bot:** {bot_status}\n\n"
        f"**Sentiment:** {s['label']}  |  "
        f"Score: {s['score']:+.3f}  |  "
        f"News: {s['headlines']} headlines\n\n"
        f"**Signals Today:** {len(signal_history)}"
    )

def get_signal_table():
    if not signal_history:
        return pd.DataFrame(columns=["Time","Action","Zone","SL","TP","Sentiment","Sent"])
    return pd.DataFrame(list(reversed(signal_history[-20:])))

def manual_sentiment(news_text: str) -> str:
    """ให้ User วิเคราะห์ข่าวเองได้ผ่าน UI — ทำให้ดูเป็น AI Demo"""
    if not news_text.strip():
        return "กรุณาใส่ข้อความข่าว"
    try:
        results = analyzer.model(news_text[:512])[0]
        scores  = {r["label"]: round(r["score"]*100, 1) for r in results}
        out = "📊 **ผลวิเคราะห์ Sentiment (FinBERT)**\n\n"
        for label, pct in scores.items():
            bar = "█" * int(pct / 5)
            out += f"{label:10s}: {bar} {pct}%\n"
        return out
    except Exception as e:
        return f"Error: {e}"

with gr.Blocks(title="Gold Market AI Analyzer", theme=gr.themes.Soft()) as demo:

    gr.Markdown("""
    # 🥇 Gold Market AI Analyzer
    **FinBERT NLP + SMC Technical Analysis** for XAUUSD Signal Detection
    > Combines market sentiment analysis with Smart Money Concepts structure
    """)

    with gr.Tabs():

        # ── Tab 1: Dashboard ──
        with gr.Tab("📊 Dashboard"):
            status_md = gr.Markdown(get_status)
            with gr.Row():
                refresh_btn = gr.Button("🔄 Refresh", variant="primary")
            signal_tbl = gr.DataFrame(
                value=get_signal_table,
                label="Recent Signals",
                interactive=False
            )
            refresh_btn.click(
                fn=lambda: (get_status(), get_signal_table()),
                outputs=[status_md, signal_tbl]
            )

        # ── Tab 2: Live Log ──
        with gr.Tab("📋 Live Log"):
            log_box = gr.Textbox(
                label="System Log",
                lines=25,
                interactive=False,
                value=get_logs
            )
            log_btn = gr.Button("🔄 Refresh Log")
            log_btn.click(fn=get_logs, outputs=log_box)

        # ── Tab 3: AI Sentiment Demo (ทำให้ดูเป็น AI Demo) ──
        with gr.Tab("🧠 AI Sentiment Analyzer"):
            gr.Markdown("### วิเคราะห์ Sentiment ข่าวทองด้วย FinBERT")
            news_input = gr.Textbox(
                label="ใส่ข่าวหรือประโยคที่ต้องการวิเคราะห์ (ภาษาอังกฤษ)",
                placeholder="e.g. Gold prices surge as Fed signals rate cuts...",
                lines=3
            )
            analyze_btn = gr.Button("🔍 Analyze Sentiment", variant="primary")
            result_box  = gr.Markdown()
            analyze_btn.click(
                fn=manual_sentiment,
                inputs=news_input,
                outputs=result_box
            )
            gr.Examples(
                examples=[
                    ["Gold prices surge as Fed signals rate cuts amid inflation concerns"],
                    ["Dollar strengthens, gold falls as US jobs data beats expectations"],
                    ["Central banks continue buying gold at record pace this quarter"],
                ],
                inputs=news_input
            )

# ─── Start ───────────────────────────────────────
if __name__ == "__main__":
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    demo.launch(server_name="0.0.0.0", server_port=7860)