import requests
import logging
from transformers import pipeline

log = logging.getLogger(__name__)

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
        ดึงข่าวทองจาก RSS Feed ฟรี (ไม่ต้อง API Key)
        ใช้ Reuters + MarketWatch
        """
        import xml.etree.ElementTree as ET
        feeds = [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.marketwatch.com/marketwatch/marketpulse/",
        ]
        keywords = ["gold", "xauusd", "bullion", "fed", "inflation",
                    "dollar", "rate", "gdp", "cpi", "fomc"]
        headlines = []

        for url in feeds:
            try:
                r = requests.get(url, timeout=10,
                                 headers={"User-Agent": "Mozilla/5.0"})
                root = ET.fromstring(r.content)
                for item in root.iter("item"):
                    title = item.findtext("title", "")
                    desc  = item.findtext("description", "")
                    text  = (title + " " + desc).lower()
                    if any(kw in text for kw in keywords):
                        headlines.append(title[:512])
            except Exception as e:
                log.warning(f"RSS fetch error ({url}): {e}")

        log.info(f"Found {len(headlines)} relevant headlines")
        return headlines[:10]   # เอาแค่ 10 อันล่าสุด

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