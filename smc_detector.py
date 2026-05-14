"""
smc_detector.py — 3-Layer SMC Confluence
=========================================
Layer 1  HTF Zone   : H4 Order Block หรือ Fair Value Gap
                      (Resample จาก M15 → ไม่กิน API quota เพิ่ม)
Layer 2  ChoCh      : M15 Change of Character
                      (close break swing high/low ครั้งแรกสวนทาง structure)
Layer 3  MSS + Wick : M15 Market Structure Shift + Reversal Candle
                      (momentum confirm ก่อน entry จริง)

สัญญาณออกเมื่อทั้ง 3 ชั้นตรงกันเท่านั้น
"""

import logging
import pandas as pd
import numpy as np

log = logging.getLogger(__name__)


class SMCDetector:
    def __init__(
        self,
        ob_lookback: int   = 20,    # จำนวน OB/FVG ย้อนหลังที่เก็บ
        fvg_threshold: float = 0.3, # ขนาด gap ขั้นต่ำ (USD) สำหรับ FVG
        wick_ratio: float  = 1.5,   # ไส้ต้องยาวกว่า body กี่เท่าถึงนับเป็น reversal
        swing_bars: int    = 5,     # lookback สองข้างสำหรับหา swing point
        rr_ratio: float    = 2.0,   # Risk:Reward ratio
    ):
        self.ob_lookback   = ob_lookback
        self.fvg_threshold = fvg_threshold
        self.wick_ratio    = wick_ratio
        self.swing_bars    = swing_bars
        self.rr_ratio      = rr_ratio

        self._reset()

    # ─── State Reset ────────────────────────────────────────────────────

    def _reset(self, side: str = "both") -> None:
        """รีเซ็ต state ฝั่งที่ระบุ หรือทั้งคู่"""
        if side in ("bull", "both"):
            self.bull_active      = False
            self.bull_sl          = None   # swing low ก่อน ChoCh → invalidation level
            self.bull_choch_high  = None   # high ของแท่ง ChoCh → MSS target
            self.bull_htf_zone    = None   # dict ของ H4 zone ที่ match
        if side in ("bear", "both"):
            self.bear_active      = False
            self.bear_sl          = None   # swing high ก่อน ChoCh → invalidation level
            self.bear_choch_low   = None   # low ของแท่ง ChoCh → MSS target
            self.bear_htf_zone    = None

    # ════════════════════════════════════════════════════════════════════
    # LAYER 1 — HTF ZONES (H4)
    # ════════════════════════════════════════════════════════════════════

    def _resample_h4(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Resample M15 → H4 ในโค้ด
        ไม่เปลือง API call แม้แต่ครั้งเดียว
        """
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index)
        h4 = (
            data.resample("4h")
            .agg(
                open=("open",  "first"),
                high=("high",  "max"),
                low= ("low",   "min"),
                close=("close","last"),
            )
            .dropna()
        )
        return h4

    def _find_ob_zones(self, h4: pd.DataFrame) -> list[dict]:
        """
        Order Block บน H4
        ─────────────────
        Demand OB : แท่ง bearish ที่อยู่ก่อน bullish impulse (>0.3%)
                    → ราคามักกลับมา retest zone นี้ก่อนขึ้นต่อ
        Supply OB : แท่ง bullish ที่อยู่ก่อน bearish impulse (>0.3%)
                    → ราคามักกลับมา retest zone นี้ก่อนลงต่อ
        """
        zones = []
        for i in range(1, len(h4) - 1):
            prev = h4.iloc[i]
            nxt  = h4.iloc[i + 1]

            impulse_up = nxt["close"] > nxt["open"] * 1.003
            impulse_dn = nxt["close"] < nxt["open"] * 0.997

            if prev["close"] < prev["open"] and impulse_up:
                zones.append({
                    "type":  "demand",
                    "high":  prev["high"],
                    "low":   prev["low"],
                    "label": "OB Demand H4",
                })
            if prev["close"] > prev["open"] and impulse_dn:
                zones.append({
                    "type":  "supply",
                    "high":  prev["high"],
                    "low":   prev["low"],
                    "label": "OB Supply H4",
                })

        return zones[-self.ob_lookback:]

    def _find_fvg_zones(self, h4: pd.DataFrame) -> list[dict]:
        """
        Fair Value Gap บน H4
        ─────────────────────
        Bullish FVG : candle[i].low > candle[i-2].high  (gap ระหว่างแท่ง)
        Bearish FVG : candle[i].high < candle[i-2].low
        """
        zones = []
        for i in range(2, len(h4)):
            c0 = h4.iloc[i - 2]   # แท่งซ้าย
            c2 = h4.iloc[i]        # แท่งขวา

            if c2["low"] > c0["high"]:
                gap = c2["low"] - c0["high"]
                if gap >= self.fvg_threshold:
                    zones.append({
                        "type":  "demand",
                        "high":  c2["low"],
                        "low":   c0["high"],
                        "label": "FVG Demand H4",
                    })

            if c2["high"] < c0["low"]:
                gap = c0["low"] - c2["high"]
                if gap >= self.fvg_threshold:
                    zones.append({
                        "type":  "supply",
                        "high":  c0["low"],
                        "low":   c2["high"],
                        "label": "FVG Supply H4",
                    })

        return zones[-self.ob_lookback:]

    def _get_htf_zones(self, df: pd.DataFrame) -> tuple[list, list]:
        """รวม OB + FVG จาก H4 แยกเป็น demand / supply"""
        h4 = self._resample_h4(df)
        if len(h4) < 5:
            log.warning("⚠️ H4 data too short for zone detection")
            return [], []

        all_zones = self._find_ob_zones(h4) + self._find_fvg_zones(h4)
        demand = [z for z in all_zones if z["type"] == "demand"]
        supply = [z for z in all_zones if z["type"] == "supply"]

        log.debug(f"HTF Zones — demand: {len(demand)}, supply: {len(supply)}")
        return demand, supply

    @staticmethod
    def _in_zone(price: float, zones: list) -> dict | None:
        """เช็คว่าราคาอยู่ใน zone ไหน (เอา zone ล่าสุดก่อน)"""
        for z in reversed(zones):
            if z["low"] <= price <= z["high"]:
                return z
        return None

    # ════════════════════════════════════════════════════════════════════
    # LAYER 2 — CHOCH (M15)
    # ════════════════════════════════════════════════════════════════════

    def _swing_points(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """
        หา Swing High / Swing Low บน M15
        ใช้ rolling window ขนาด swing_bars ทั้งสองข้าง
        """
        n  = self.swing_bars
        sh = df["high"].rolling(n * 2 + 1, center=True).max() == df["high"]
        sl = df["low"].rolling(n * 2 + 1, center=True).min() == df["low"]
        return sh, sl

    def _choch_series(self, df: pd.DataFrame):
        """
        ChoCh (Change of Character) — M15
        ───────────────────────────────────
        Bullish ChoCh : close > swing high ล่าสุด
                        → โครงสร้างขาลงถูก break ครั้งแรก
        Bearish ChoCh : close < swing low ล่าสุด
                        → โครงสร้างขาขึ้นถูก break ครั้งแรก

        ต่างจาก MSS ตรงที่ ChoCh = สัญญาณเตือน (ยังไม่ entry)
        MSS = ยืนยันและ entry จริง
        """
        sh, sl        = self._swing_points(df)
        last_sh       = df["high"].where(sh).ffill()
        last_sl       = df["low"].where(sl).ffill()
        bull_choch    = df["close"] > last_sh.shift(1)
        bear_choch    = df["close"] < last_sl.shift(1)
        return bull_choch, bear_choch, last_sh, last_sl

    # ════════════════════════════════════════════════════════════════════
    # LAYER 3 — MSS + WICK CLEARED (M15)
    # ════════════════════════════════════════════════════════════════════

    def _mss_bull(
        self,
        df: pd.DataFrame,
        choch_high: float,
        choch_low: float,
    ) -> bool:
        """
        Bullish MSS (Market Structure Shift)
        ──────────────────────────────────────
        เงื่อนไข:
          1. ราคาไม่ทะลุ low ของแท่ง ChoCh (structure ยังรักษาไว้)
          2. close ปัจจุบัน > high ของแท่ง ChoCh (momentum ยืนยัน = wick cleared)

        ถ้าทั้งสองข้อผ่าน → momentum แข็งแกร่ง พร้อม entry
        """
        structure_held = df["low"].min() >= choch_low
        momentum_ok    = df["close"].iloc[-1] > choch_high
        return structure_held and momentum_ok

    def _mss_bear(
        self,
        df: pd.DataFrame,
        choch_low: float,
        choch_high: float,
    ) -> bool:
        """
        Bearish MSS (Market Structure Shift)
        ──────────────────────────────────────
        เงื่อนไข:
          1. ราคาไม่ทะลุ high ของแท่ง ChoCh
          2. close ปัจจุบัน < low ของแท่ง ChoCh
        """
        structure_held = df["high"].max() <= choch_high
        momentum_ok    = df["close"].iloc[-1] < choch_low
        return structure_held and momentum_ok

    def _is_wick_candle(self, row: pd.Series) -> tuple[bool, bool]:
        """
        Reversal Wick Candle
        ─────────────────────
        Bullish : แท่งเขียว + ไส้ล่างยาวกว่า body × wick_ratio
        Bearish : แท่งแดง  + ไส้บนยาวกว่า body × wick_ratio
        """
        body     = abs(row["close"] - row["open"])
        if body == 0:
            return False, False
        low_wick = min(row["open"], row["close"]) - row["low"]
        up_wick  = row["high"] - max(row["open"], row["close"])
        bull = row["close"] > row["open"] and low_wick >= body * self.wick_ratio
        bear = row["close"] < row["open"] and up_wick  >= body * self.wick_ratio
        return bull, bear

    # ════════════════════════════════════════════════════════════════════
    # MAIN ANALYZE
    # ════════════════════════════════════════════════════════════════════

    def analyze(self, df: pd.DataFrame) -> dict | None:
        """
        รัน 3-Layer Confluence analysis

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV ของ M15 (ต้องการอย่างน้อย ~50 ชั่วโมง = 200 แท่ง
            เพื่อให้ H4 resample ได้ ~12 แท่ง)

        Returns
        -------
        dict | None
            คืน signal dict เมื่อทั้ง 3 ชั้นตรงกัน หรือ None ถ้ายังไม่มีสัญญาณ
        """
        min_bars = max(self.ob_lookback, self.swing_bars * 2 + 2) + 10
        if len(df) < min_bars:
            log.warning(f"⚠️ Not enough bars: {len(df)} < {min_bars}")
            return None

        # ── Layer 1: HTF Zones ──────────────────────────────────────────
        demand_zones, supply_zones = self._get_htf_zones(df)

        cur  = df.iloc[-1]   # แท่งปัจจุบัน (ยังไม่ปิด)
        prev = df.iloc[-2]   # แท่งก่อนหน้า (ปิดแล้ว → ใช้ยืนยัน ChoCh)

        zone_cur_demand  = self._in_zone(cur["close"],  demand_zones)
        zone_cur_supply  = self._in_zone(cur["close"],  supply_zones)
        zone_prev_demand = self._in_zone(prev["close"], demand_zones)
        zone_prev_supply = self._in_zone(prev["close"], supply_zones)

        # ── Layer 2: ChoCh (M15) ───────────────────────────────────────
        bull_choch, bear_choch, last_sh, last_sl = self._choch_series(df)

        # ตรวจ ChoCh ที่แท่ง prev (closed candle ที่ยืนยันแล้ว)
        # + ต้องอยู่ใน HTF Zone พร้อมกัน
        if bull_choch.iloc[-2] and zone_prev_demand and not self.bull_active:
            self.bull_active     = True
            self.bull_sl         = float(last_sl.iloc[-2])   # swing low ก่อน ChoCh
            self.bull_choch_high = float(prev["high"])        # high ของแท่ง ChoCh
            self.bull_htf_zone   = zone_prev_demand
            log.info(
                f"🔵 Bullish ChoCh | price={prev['close']:.2f} "
                f"| sl={self.bull_sl:.2f} | zone={zone_prev_demand['label']}"
            )

        if bear_choch.iloc[-2] and zone_prev_supply and not self.bear_active:
            self.bear_active    = True
            self.bear_sl        = float(last_sh.iloc[-2])    # swing high ก่อน ChoCh
            self.bear_choch_low = float(prev["low"])          # low ของแท่ง ChoCh
            self.bear_htf_zone  = zone_prev_supply
            log.info(
                f"🔴 Bearish ChoCh | price={prev['close']:.2f} "
                f"| sl={self.bear_sl:.2f} | zone={zone_prev_supply['label']}"
            )

        # Invalidation: ราคาทะลุ structure level ออกไป → รีเซ็ต
        if self.bull_active and self.bull_sl and cur["close"] < self.bull_sl:
            log.info(f"❌ Bullish ChoCh invalidated — close {cur['close']:.2f} < sl {self.bull_sl:.2f}")
            self._reset("bull")

        if self.bear_active and self.bear_sl and cur["close"] > self.bear_sl:
            log.info(f"❌ Bearish ChoCh invalidated — close {cur['close']:.2f} > sl {self.bear_sl:.2f}")
            self._reset("bear")

        # ── Layer 3: MSS + Wick Cleared ────────────────────────────────
        wick_bull, wick_bear = self._is_wick_candle(prev)

        # ── Bullish Signal ──
        if self.bull_active and wick_bull and zone_cur_demand:
            # ดูแท่งล่าสุด 5 แท่งหลัง ChoCh (ไม่ต้องหา index แน่นอน)
            recent = df.iloc[-6:-1]   # 5 แท่งหลัง ChoCh (ไม่รวมแท่งปัจจุบันที่ยังไม่ปิด)
            mss_ok = self._mss_bull(recent, self.bull_choch_high, self.bull_sl)

            if mss_ok:
                entry      = float(cur["close"])
                sl         = self.bull_sl
                tp         = entry + (entry - sl) * self.rr_ratio
                zone_label = self.bull_htf_zone["label"]
                self._reset("bull")

                log.info(
                    f"✅ BUY SIGNAL | entry={entry:.2f} sl={sl:.2f} "
                    f"tp={tp:.2f} | {zone_label}"
                )
                return {
                    "action":    "BUY",
                    "zone":      round(entry, 2),
                    "sl":        round(sl, 2),
                    "tp":        round(tp, 2),
                    "rr":        f"1:{self.rr_ratio}",
                    "pattern":   "ChoCh → MSS → Wick Cleared",
                    "htf_zone":  zone_label,
                    "structure": "Bullish MSS Confirmed",
                }

        # ── Bearish Signal ──
        if self.bear_active and wick_bear and zone_cur_supply:
            recent = df.iloc[-6:-1]   # 5 แท่ง closed เท่านั้น (ไม่รวมแท่งที่ยังไม่ปิด)
            mss_ok = self._mss_bear(recent, self.bear_choch_low, self.bear_sl)

            if mss_ok:
                entry      = float(cur["close"])
                sl         = self.bear_sl
                tp         = entry - (sl - entry) * self.rr_ratio
                zone_label = self.bear_htf_zone["label"]
                self._reset("bear")

                log.info(
                    f"✅ SELL SIGNAL | entry={entry:.2f} sl={sl:.2f} "
                    f"tp={tp:.2f} | {zone_label}"
                )
                return {
                    "action":    "SELL",
                    "zone":      round(entry, 2),
                    "sl":        round(sl, 2),
                    "tp":        round(tp, 2),
                    "rr":        f"1:{self.rr_ratio}",
                    "pattern":   "ChoCh → MSS → Wick Cleared",
                    "htf_zone":  zone_label,
                    "structure": "Bearish MSS Confirmed",
                }

        return None