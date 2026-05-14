import os
import requests
import logging
from transformers import pipeline

log = logging.getLogger(__name__)

CLOUDFLARE_RELAY = os.environ.get("CLOUDFLARE_RELAY")

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",       # ผ่าน Cloudflare ได้
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/news_14.rss",
    "https://www.fxstreet.com/rss/news",
    "https://www.kitco.com/rss/kitco-news.rss",
]

RSS_KEYWORDS = [
    "gold", "xauusd", "bullion", "fed", "inflation",
    "dollar", "rate", "gdp", "cpi", "fomc", "treasury",
    "powell", "yield", "safe haven", "precious metal",
]

class SentimentAnalyzer:
    def __init__(self):
        log.info("Loading FinBERT model...")
        self.model = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            top_k=None
        )
        log.info("FinBERT loaded ✅")

    def _fetch_gold_news(self) -> list[str]:
        """
        ดึงข่าวทองผ่าน Cloudflare Worker (ไม่มี DNS block)
        ถ้าไม่มี CLOUDFLARE_RELAY ค่อย fallback ดึงตรง
        """
        if CLOUDFLARE_RELAY:
            try:
                r = requests.post(
                    CLOUDFLARE_RELAY,
                    json={
                        "action":   "fetch_rss",
                        "feeds":    RSS_FEEDS,
                        "keywords": RSS_KEYWORDS,
                    },
                    timeout=20,
                )
                r.raise_for_status()
                headlines = r.json().get("headlines", [])
                log.info(f"Found {len(headlines)} relevant headlines (via Cloudflare)")
                return headlines
            except Exception as e:
                log.warning(f"Cloudflare RSS proxy error: {e} — falling back to direct")

        # fallback: ดึงตรง (บาง feed อาจถูกบล็อกบน HF Space)
        import xml.etree.ElementTree as ET
        headlines = []
        for url in RSS_FEEDS:
            try:
                r = requests.get(url, timeout=10,
                                 headers={"User-Agent": "Mozilla/5.0"})
                root = ET.fromstring(r.content)
                for item in root.iter("item"):
                    title = item.findtext("title", "")
                    desc  = item.findtext("description", "")
                    text  = (title + " " + desc).lower()
                    if any(kw in text for kw in RSS_KEYWORDS):
                        headlines.append(title[:512])
            except Exception as e:
                log.warning(f"RSS fetch error ({url}): {e}")

        log.info(f"Found {len(headlines)} relevant headlines (direct)")
        seen, unique = set(), []
        for h in headlines:
            if h not in seen:
                seen.add(h)
                unique.append(h)
        return unique[:15]

    def get_sentiment(self) -> dict:
        """
        คืนค่า:
          score    : -1.0 ถึง +1.0  (ลบ=bearish, บวก=bullish)
          label    : BULLISH / BEARISH / NEUTRAL
          headlines: จำนวนข่าวที่ใช้
        """
        headlines = self._fetch_gold_news()
        if not headlines:
            return {"score": 0.0, "label": "NEUTRAL", "headlines": 0}

        if len(headlines) < 3:
            log.warning(f"Too few headlines ({len(headlines)}) — defaulting to NEUTRAL")
            return {"score": 0.0, "label": "NEUTRAL", "headlines": len(headlines)}

        total = 0.0
        for h in headlines:
            try:
                results = self.model(h)[0]
                scores  = {r["label"].lower(): r["score"] for r in results}
                # positive = bullish, negative = bearish
                total += scores.get("positive", 0) - scores.get("negative", 0)
            except Exception as e:
                log.warning(f"Sentiment error: {e}")

        avg = total / len(headlines)

        if avg > 0.15:
            label = "BULLISH"
        elif avg < -0.15:
            label = "BEARISH"
        else:
            label = "NEUTRAL"

        log.info(f"Sentiment: {label} ({avg:.3f}) from {len(headlines)} headlines")
        return {"score": round(avg, 3), "label": label, "headlines": len(headlines)}

    def is_aligned(self, action: str, sentiment: dict) -> bool:
        """
        เช็คว่า SMC signal ตรงกับ Sentiment มั้ย
        BUY  → ต้องการ BULLISH หรือ NEUTRAL
        SELL → ต้องการ BEARISH หรือ NEUTRAL
        """
        if action == "BUY"  and sentiment["label"] == "BEARISH":
            return False
        if action == "SELL" and sentiment["label"] == "BULLISH":
            return False
        return True