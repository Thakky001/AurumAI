import os
import time
import logging
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
import gradio as gr

from smc_detector       import SMCDetector
from sentiment_analyzer import SentimentAnalyzer

# ─── Logging ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ─── ENV ────────────────────────────────────────
TIINGO_API_KEY   = os.environ.get("TIINGO_API_KEY")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID          = os.environ.get("CHAT_ID")
CLOUDFLARE_RELAY = os.environ.get("CLOUDFLARE_RELAY")  # Cloudflare Worker URL

# ─── Config ─────────────────────────────────────
SYMBOL        = "xauusd"   # Tiingo ใช้ตัวพิมพ์เล็กและไม่มีทับ
INTERVAL      = "15min"
OUTPUT_SIZE   = 200        # 200 × 15min = ~50 ชั่วโมง → ~12 แท่ง H4
POLL_SECONDS  = 30         # Tiingo free tier limit ~1 req/30s

# Sentiment refresh ทุก 60 นาที (ประหยัดโควต้า FinBERT)
SENTIMENT_REFRESH_MIN = 60

# ─── Shared State ───────────────────────────────
log_lines           = []
signal_history      = []
current_sentiment   = {"score": 0.0, "label": "NEUTRAL", "headlines": 0}
last_sentiment_time = None
bot_status          = "⏳ Starting..."

detector = SMCDetector(ob_lookback=20, fvg_threshold=0.3,
                       wick_ratio=1.5, swing_bars=5, rr_ratio=2.0)
analyzer = SentimentAnalyzer()   # โหลด FinBERT ตอน startup

# ─── Helpers ────────────────────────────────────
def add_log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    log_lines.append(line)
    if len(log_lines) > 200:
        log_lines.pop(0)
    log.info(msg)

def is_market_open() -> bool:
    """เช็คว่าตลาด Forex/Gold เปิดอยู่หรือไม่ 24/5 (อิงเวลา UTC)"""
    now = datetime.now(timezone.utc)
    wd  = now.weekday()  # 0=จันทร์, 4=ศุกร์, 5=เสาร์, 6=อาทิตย์
    hr  = now.hour

    if wd == 5:               # วันเสาร์ปิดทั้งวัน
        return False
    if wd == 6 and hr < 22:   # วันอาทิตย์เปิดตอน 22:00 UTC (ตี 5 วันจันทร์ไทย)
        return False
    if wd == 4 and hr >= 22:  # วันศุกร์ปิดตอน 22:00 UTC (ตี 5 วันเสาร์ไทย)
        return False
    return True

def should_refresh_sentiment() -> bool:
    global last_sentiment_time
    if last_sentiment_time is None:
        return True
    diff = (datetime.now(timezone.utc) - last_sentiment_time).seconds / 60
    return diff >= SENTIMENT_REFRESH_MIN

def fetch_ohlcv() -> pd.DataFrame | None:
    """ดึงข้อมูลราคาจาก Tiingo API"""
    if not TIINGO_API_KEY:
        add_log("⚠️ ขาด TIINGO_API_KEY")
        return None

    url     = f"https://api.tiingo.com/tiingo/fx/{SYMBOL}/prices"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {TIINGO_API_KEY}"
    }
    params  = {"resampleFreq": INTERVAL, "format": "json"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if not data:
            return None

        df = pd.DataFrame(data)
        df["datetime"] = pd.to_datetime(df["date"])
        df = df.set_index("datetime").sort_index()

        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float)

        return df
    except Exception as e:
        add_log(f"❌ Fetch error (Tiingo): {e}")
        return None

# ─── Telegram (ผ่าน Cloudflare relay หรือ direct) ──
def _send_via_relay(text: str, retries: int = 3) -> bool:
    """ส่ง Telegram ผ่าน Cloudflare Worker relay ถ้ามี ไม่งั้นยิงตรง"""
    if CLOUDFLARE_RELAY:
        url     = CLOUDFLARE_RELAY
        payload = {"token": TELEGRAM_TOKEN, "chat_id": CHAT_ID, "text": text}
    else:
        url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}

    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, timeout=(5, 30), stream=False)
            r.raise_for_status()
            return True
        except Exception as e:
            add_log(f"❌ Telegram error (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return False

def send_telegram_notify(text: str) -> bool:
    return _send_via_relay(text)

def notify_session_start():
    now  = datetime.now(timezone.utc)
    thai = (now.hour + 7) % 24
    text = (
        f"🟢 <b>ตลาดเปิดแล้ว — เริ่มสัปดาห์ใหม่</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>เวลา:</b> {thai:02d}:{now.minute:02d} น. (ไทย)\n"
        f"📡 <b>Mode:</b> 24/5 (Forex Market Hours)\n"
        f"⚡ <b>Scan:</b> ทุก 30 วินาที (M15 Entry / H4 Zone)\n"
        f"🧠 <b>Sentiment:</b> {current_sentiment['label']} "
        f"({current_sentiment['score']:+.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Bot จะส่งสัญญาณเมื่อ SMC + Sentiment ตรงกัน</i>"
    )
    send_telegram_notify(text)
    add_log("📨 Market OPEN notification sent")

def notify_session_end():
    now   = datetime.now(timezone.utc)
    thai  = (now.hour + 7) % 24
    total = len(signal_history)
    text  = (
        f"🔴 <b>ตลาดปิดแล้ว — พักผ่อนช่วงสุดสัปดาห์</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>เวลา:</b> {thai:02d}:{now.minute:02d} น. (ไทย)\n"
        f"📊 <b>สัญญาณสัปดาห์นี้:</b> {total} สัญญาณ\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Bot จะกลับมา Monday 05:00 น. (ไทย) / Sunday 22:00 UTC</i>"
    )
    send_telegram_notify(text)
    add_log("📨 Market CLOSE notification sent")

def send_telegram(signal: dict, sentiment: dict) -> bool:
    action  = signal["action"]
    emoji   = "🟢" if action == "BUY" else "🔴"
    s_emoji = "📈" if sentiment["label"] == "BULLISH" else \
              "📉" if sentiment["label"] == "BEARISH" else "➡️"
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
    return _send_via_relay(text)

# ─── Main Bot Loop ───────────────────────────────
def run_bot():
    global bot_status, current_sentiment, last_sentiment_time

    add_log("🚀 Gold Market AI Analyzer started (24/5 Mode)")
    add_log("🤖 FinBERT model ready")
    if CLOUDFLARE_RELAY:
        add_log("☁️ Telegram relay: Cloudflare Worker")
    else:
        add_log("📡 Telegram relay: Direct")

    market_was_open = False

    while True:
        try:
            now_utc        = datetime.now(timezone.utc)
            market_is_open = is_market_open()

            # ── ตลาดเพิ่งเปิด ──
            if market_is_open and not market_was_open:
                current_sentiment   = analyzer.get_sentiment()
                last_sentiment_time = now_utc
                notify_session_start()
                market_was_open = True
                add_log("🟢 Market Opened — Starting Scan")

            # ── ตลาดเพิ่งปิด ──
            if not market_is_open and market_was_open:
                notify_session_end()
                market_was_open = False
                add_log("🔴 Market Closed — Pausing Scan")

            # ── นอกเวลาตลาด ──
            if not market_is_open:
                bot_status = "⏸ Market Closed (Weekend)"
                time.sleep(300)
                continue

            # ── ในเวลาตลาด ──
            bot_status = "🟢 Scanning 24/5"

            # ── Refresh Sentiment (ทุก 60 นาที) ──
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
                aligned = analyzer.is_aligned(signal["action"], current_sentiment)
                add_log(
                    f"🎯 Signal: {signal['action']} @ {signal['zone']} | "
                    f"Sentiment: {current_sentiment['label']} | "
                    f"Aligned: {'✅' if aligned else '❌'}"
                )

                if aligned:
                    ok     = send_telegram(signal, current_sentiment)
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
        f"**Signals Total:** {len(signal_history)}"
    )

def get_signal_table():
    if not signal_history:
        return pd.DataFrame(columns=["Time","Action","Zone","SL","TP","Sentiment","Sent"])
    return pd.DataFrame(list(reversed(signal_history[-20:])))

def manual_sentiment(news_text: str) -> str:
    if not news_text.strip():
        return "กรุณาใส่ข้อความข่าว"
    try:
        results = analyzer.model(news_text[:512])[0]
        scores  = {r["label"]: round(r["score"] * 100, 1) for r in results}
        out = "📊 **ผลวิเคราะห์ Sentiment (FinBERT)**\n\n"
        for label, pct in scores.items():
            bar = "█" * int(pct / 5)
            out += f"{label:10s}: {bar} {pct}%\n"
        return out
    except Exception as e:
        return f"Error: {e}"

with gr.Blocks(title="Gold Market AI Analyzer") as demo:

    gr.Markdown("""
    # 🥇 Gold Market AI Analyzer
    **FinBERT NLP + SMC Technical Analysis** for XAUUSD Signal Detection
    > Combines market sentiment analysis with Smart Money Concepts structure
    """)

    with gr.Tabs():

        with gr.Tab("📊 Dashboard"):
            status_md = gr.Markdown(get_status())
            with gr.Row():
                refresh_btn = gr.Button("🔄 Refresh", variant="primary")
            signal_tbl = gr.DataFrame(
                value=get_signal_table(),
                label="Recent Signals",
                interactive=False
            )
            refresh_btn.click(
                fn=lambda: (get_status(), get_signal_table()),
                outputs=[status_md, signal_tbl]
            )

        with gr.Tab("📋 Live Log"):
            log_box = gr.Textbox(
                label="System Log",
                lines=25,
                interactive=False,
                value=get_logs()
            )
            log_btn = gr.Button("🔄 Refresh Log")
            log_btn.click(fn=get_logs, outputs=log_box)

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
    demo.launch(server_name="0.0.0.0", server_port=7860, prevent_thread_lock=True)
    threading.Event().wait()