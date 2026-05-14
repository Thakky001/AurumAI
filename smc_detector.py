"""
smc_detector.py — 3-Layer SMC Confluence  (v2 — fixed)
=======================================================
Layer 1  HTF Zone      : H4 Order Block หรือ Fair Value Gap
                         Zone width = low → 50% ของ OB candle (ไม่ใช่ full high-low)
Layer 2  ChoCh         : M15 Change of Character
                         บันทึก index แท่ง ChoCh จริงๆ เพื่อใช้ใน Layer 3
Layer 3  MSS + Wick Cleared :
          Step A — แท่ง Reversal Wick ปรากฏ (ไส้ยาว) ← บันทึกไว้เป็น pending
          Step B — แท่ง ถัดจาก Reversal Wick "เคลียร์ไส้":
                   close > high ของ Reversal Wick (BUY)
                   close < low  ของ Reversal Wick (SELL)
          + ตรวจ MSS ด้วยแท่งตั้งแต่ ChoCh จนถึงปัจจุบัน (ไม่ใช่ fixed 5 แท่ง)

สัญญาณออกเมื่อทั้ง 3 ชั้นตรงกันเท่านั้น
"""

import logging
import pandas as pd
import numpy as np

log = logging.getLogger(__name__)


class SMCDetector:
    def __init__(
        self,
        ob_lookback: int    = 20,   # จำนวน OB/FVG ย้อนหลังที่เก็บ
        fvg_threshold: float = 0.3, # ขนาด gap ขั้นต่ำ (USD) สำหรับ FVG
        wick_ratio: float   = 1.5,  # ไส้ต้องยาวกว่า body กี่เท่าถึงนับเป็น reversal
        swing_bars: int     = 5,    # lookback สองข้างสำหรับหา swing point
        rr_ratio: float     = 2.0,  # Risk:Reward ratio
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
            self.bull_active         = False
            self.bull_sl             = None   # swing low ก่อน ChoCh → invalidation
            self.bull_choch_high     = None   # high ของแท่ง ChoCh → MSS target
            self.bull_choch_idx      = None   # [FIX 3] integer index ของแท่ง ChoCh ใน df
            self.bull_htf_zone       = None   # H4 zone ที่ match
            # [FIX 1] state สำหรับ 2-step wick cleared
            self.bull_wick_high      = None   # high ของ Reversal Wick candle
            self.bull_wick_low       = None   # low  ของ Reversal Wick candle
            self.bull_wick_pending   = False  # รอแท่งถัดไปมาเคลียร์ไส้

        if side in ("bear", "both"):
            self.bear_active         = False
            self.bear_sl             = None   # swing high ก่อน ChoCh → invalidation
            self.bear_choch_low      = None   # low ของแท่ง ChoCh → MSS target
            self.bear_choch_idx      = None   # [FIX 3] integer index ของแท่ง ChoCh ใน df
            self.bear_htf_zone       = None
            # [FIX 1] state สำหรับ 2-step wick cleared
            self.bear_wick_high      = None
            self.bear_wick_low       = None
            self.bear_wick_pending   = False

    # ════════════════════════════════════════════════════════════════════
    # LAYER 1 — HTF ZONES (H4)
    # ════════════════════════════════════════════════════════════════════

    def _resample_h4(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample M15 → H4 ในโค้ด (ไม่กิน API quota)"""
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index)
        h4 = (
            data.resample("4h")
            .agg(
                open=("open",   "first"),
                high=("high",   "max"),
                low= ("low",    "min"),
                close=("close", "last"),
            )
            .dropna()
        )
        return h4

    def _find_ob_zones(self, h4: pd.DataFrame) -> list[dict]:
        """
        Order Block บน H4
        ──────────────────
        [FIX 2] Zone width แก้ใหม่:
          Demand OB  : zone = [ low ของแท่ง OB  → open ของแท่ง OB  ]
                       (50% ของ OB ฝั่งล่าง — ราคาที่ smart money เริ่มซื้อ)
          Supply OB  : zone = [ open ของแท่ง OB → high ของแท่ง OB  ]
                       (50% ของ OB ฝั่งบน — ราคาที่ smart money เริ่มขาย)

        ใช้ open เป็นขอบเขตเพราะ open ≈ กึ่งกลาง (50%) ของแท่ง bullish/bearish
        ซึ่งตรงกับนิยาม SMC ที่ว่า OB zone = บริเวณที่ order ถูก fill
        """
        zones = []
        for i in range(1, len(h4) - 1):
            candle = h4.iloc[i]
            nxt    = h4.iloc[i + 1]

            impulse_up = nxt["close"] > nxt["open"] * 1.003
            impulse_dn = nxt["close"] < nxt["open"] * 0.997

            # Demand OB: แท่ง bearish ก่อน bullish impulse
            if candle["close"] < candle["open"] and impulse_up:
                zones.append({
                    "type":  "demand",
                    "high":  candle["open"],   # ขอบบน = open ของแท่ง bearish
                    "low":   candle["low"],    # ขอบล่าง = low
                    "label": "OB Demand H4",
                })

            # Supply OB: แท่ง bullish ก่อน bearish impulse
            if candle["close"] > candle["open"] and impulse_dn:
                zones.append({
                    "type":  "supply",
                    "high":  candle["high"],   # ขอบบน = high
                    "low":   candle["open"],   # ขอบล่าง = open ของแท่ง bullish
                    "label": "OB Supply H4",
                })

        return zones[-self.ob_lookback:]

    def _find_fvg_zones(self, h4: pd.DataFrame) -> list[dict]:
        """
        Fair Value Gap บน H4
        ─────────────────────
        Bullish FVG : candle[i].low > candle[i-2].high
        Bearish FVG : candle[i].high < candle[i-2].low
        (FVG ไม่ต้องแก้ zone width เพราะ gap คือ zone อยู่แล้ว)
        """
        zones = []
        for i in range(2, len(h4)):
            c0 = h4.iloc[i - 2]
            c2 = h4.iloc[i]

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
        """หา Swing High / Swing Low บน M15"""
        n  = self.swing_bars
        sh = df["high"].rolling(n * 2 + 1, center=True).max() == df["high"]
        sl = df["low"].rolling(n * 2 + 1, center=True).min() == df["low"]
        return sh, sl

    def _choch_series(self, df: pd.DataFrame):
        """
        ChoCh (Change of Character) — M15
        ───────────────────────────────────
        Bullish ChoCh : close > swing high ล่าสุด
        Bearish ChoCh : close < swing low ล่าสุด
        คืนค่า integer index ของแท่ง ChoCh ด้วย เพื่อใช้ใน Layer 3 [FIX 3]
        """
        sh, sl     = self._swing_points(df)
        last_sh    = df["high"].where(sh).ffill()
        last_sl    = df["low"].where(sl).ffill()
        bull_choch = df["close"] > last_sh.shift(1)
        bear_choch = df["close"] < last_sl.shift(1)
        return bull_choch, bear_choch, last_sh, last_sl

    # ════════════════════════════════════════════════════════════════════
    # LAYER 3 — MSS + WICK CLEARED (M15)  [FIX 1 + FIX 3]
    # ════════════════════════════════════════════════════════════════════

    def _mss_bull(
        self,
        df_since_choch: pd.DataFrame,
        choch_high: float,
        choch_low: float,
    ) -> bool:
        """
        Bullish MSS — ตรวจด้วยแท่งตั้งแต่ ChoCh จนถึงปัจจุบัน [FIX 3]
        ────────────────────────────────────────────────────────────────
        1. structure_held : ราคาไม่เคยปิดต่ำกว่า choch_low ตลอดช่วง
        2. momentum_ok    : close ล่าสุด > high ของแท่ง ChoCh
        """
        structure_held = df_since_choch["low"].min() >= choch_low
        momentum_ok    = df_since_choch["close"].iloc[-1] > choch_high
        return structure_held and momentum_ok

    def _mss_bear(
        self,
        df_since_choch: pd.DataFrame,
        choch_low: float,
        choch_high: float,
    ) -> bool:
        """
        Bearish MSS — ตรวจด้วยแท่งตั้งแต่ ChoCh จนถึงปัจจุบัน [FIX 3]
        ────────────────────────────────────────────────────────────────
        1. structure_held : ราคาไม่เคยปิดสูงกว่า choch_high ตลอดช่วง
        2. momentum_ok    : close ล่าสุด < low ของแท่ง ChoCh
        """
        structure_held = df_since_choch["high"].max() <= choch_high
        momentum_ok    = df_since_choch["close"].iloc[-1] < choch_low
        return structure_held and momentum_ok

    def _is_wick_candle(self, row: pd.Series) -> tuple[bool, bool]:
        """
        Reversal Wick Candle (Step A)
        ──────────────────────────────
        Bullish : แท่งเขียว + ไส้ล่างยาวกว่า body × wick_ratio
        Bearish : แท่งแดง  + ไส้บนยาวกว่า body × wick_ratio
        """
        body = abs(row["close"] - row["open"])
        if body == 0:
            return False, False
        low_wick = min(row["open"], row["close"]) - row["low"]
        up_wick  = row["high"] - max(row["open"], row["close"])
        bull = row["close"] > row["open"] and low_wick >= body * self.wick_ratio
        bear = row["close"] < row["open"] and up_wick  >= body * self.wick_ratio
        return bull, bear

    def _wick_cleared_bull(self, cur: pd.Series, wick_high: float) -> bool:
        """
        [FIX 1] Wick Cleared — Step B (Bullish)
        ─────────────────────────────────────────
        แท่งปัจจุบัน close > high ของ Reversal Wick candle
        → กลืนไส้บนของแท่งก่อนหน้า ยืนยัน momentum ขาขึ้น
        """
        return cur["close"] > wick_high

    def _wick_cleared_bear(self, cur: pd.Series, wick_low: float) -> bool:
        """
        [FIX 1] Wick Cleared — Step B (Bearish)
        ─────────────────────────────────────────
        แท่งปัจจุบัน close < low ของ Reversal Wick candle
        → กลืนไส้ล่างของแท่งก่อนหน้า ยืนยัน momentum ขาลง
        """
        return cur["close"] < wick_low

    # ════════════════════════════════════════════════════════════════════
    # MAIN ANALYZE
    # ════════════════════════════════════════════════════════════════════

    def analyze(self, df: pd.DataFrame) -> dict | None:
        """
        รัน 3-Layer Confluence analysis

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV ของ M15 มี DatetimeIndex
            ต้องการอย่างน้อย ~50 ชั่วโมง (~200 แท่ง)

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
        prev = df.iloc[-2]   # แท่งก่อนหน้า (ปิดแล้ว)

        zone_cur_demand  = self._in_zone(cur["close"],  demand_zones)
        zone_cur_supply  = self._in_zone(cur["close"],  supply_zones)
        zone_prev_demand = self._in_zone(prev["close"], demand_zones)
        zone_prev_supply = self._in_zone(prev["close"], supply_zones)

        # ── Layer 2: ChoCh (M15) ───────────────────────────────────────
        bull_choch, bear_choch, last_sh, last_sl = self._choch_series(df)

        # [FIX 3] บันทึก integer index ของแท่ง ChoCh (iloc position ใน df)
        # ใช้ iloc[-2] = แท่ง prev (closed) เป็นจุด ChoCh
        choch_iloc = len(df) - 2   # integer position ของ prev ใน df

        if bull_choch.iloc[-2] and zone_prev_demand and not self.bull_active:
            self.bull_active     = True
            self.bull_sl         = float(last_sl.iloc[-2])
            self.bull_choch_high = float(prev["high"])
            self.bull_choch_idx  = choch_iloc          # [FIX 3] เก็บ index จริง
            self.bull_htf_zone   = zone_prev_demand
            # รีเซ็ต pending wick เผื่อมี state ค้างจากรอบก่อน
            self.bull_wick_pending = False
            self.bull_wick_high    = None
            self.bull_wick_low     = None
            log.info(
                f"🔵 Bullish ChoCh | price={prev['close']:.2f} "
                f"| sl={self.bull_sl:.2f} | zone={zone_prev_demand['label']}"
            )

        if bear_choch.iloc[-2] and zone_prev_supply and not self.bear_active:
            self.bear_active    = True
            self.bear_sl        = float(last_sh.iloc[-2])
            self.bear_choch_low = float(prev["low"])
            self.bear_choch_idx = choch_iloc           # [FIX 3] เก็บ index จริง
            self.bear_htf_zone  = zone_prev_supply
            self.bear_wick_pending = False
            self.bear_wick_high    = None
            self.bear_wick_low     = None
            log.info(
                f"🔴 Bearish ChoCh | price={prev['close']:.2f} "
                f"| sl={self.bear_sl:.2f} | zone={zone_prev_supply['label']}"
            )

        # Invalidation: ราคาทะลุ structure level → รีเซ็ต
        if self.bull_active and self.bull_sl and cur["close"] < self.bull_sl:
            log.info(f"❌ Bull invalidated — close {cur['close']:.2f} < sl {self.bull_sl:.2f}")
            self._reset("bull")

        if self.bear_active and self.bear_sl and cur["close"] > self.bear_sl:
            log.info(f"❌ Bear invalidated — close {cur['close']:.2f} > sl {self.bear_sl:.2f}")
            self._reset("bear")

        # ── Layer 3: MSS + Wick Cleared (2 Step) ───────────────────────

        # [FIX 1] Step A: ตรวจ Reversal Wick candle ที่แท่ง prev (closed)
        #         ถ้าพบ ให้บันทึกไว้เป็น pending รอแท่งถัดไปมาเคลียร์ไส้
        wick_bull, wick_bear = self._is_wick_candle(prev)

        if self.bull_active and wick_bull and zone_prev_demand and not self.bull_wick_pending:
            self.bull_wick_pending = True
            self.bull_wick_high    = float(prev["high"])
            self.bull_wick_low     = float(prev["low"])
            log.info(
                f"🕯️ Bull Reversal Wick detected | high={self.bull_wick_high:.2f} "
                f"→ รอแท่งถัดไปเคลียร์ไส้"
            )

        if self.bear_active and wick_bear and zone_prev_supply and not self.bear_wick_pending:
            self.bear_wick_pending = True
            self.bear_wick_high    = float(prev["high"])
            self.bear_wick_low     = float(prev["low"])
            log.info(
                f"🕯️ Bear Reversal Wick detected | low={self.bear_wick_low:.2f} "
                f"→ รอแท่งถัดไปเคลียร์ไส้"
            )

        # [FIX 1] Step B: แท่งปัจจุบัน (cur) ต้อง close เคลียร์ไส้ของ Reversal Wick
        # [FIX 3] MSS ตรวจจากแท่ง ChoCh จนถึง prev (ไม่ใช่ fixed 5 แท่ง)

        # ── Bullish Signal ──────────────────────────────────────────────
        if (
            self.bull_active
            and self.bull_wick_pending
            and zone_cur_demand
            and self._wick_cleared_bull(cur, self.bull_wick_high)
        ):
            # [FIX 3] slice df ตั้งแต่แท่ง ChoCh จนถึง prev (closed candles เท่านั้น)
            df_since_choch = df.iloc[self.bull_choch_idx: len(df) - 1]

            mss_ok = self._mss_bull(df_since_choch, self.bull_choch_high, self.bull_sl)

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
                    "pattern":   "ChoCh → Reversal Wick → Wick Cleared → MSS",
                    "htf_zone":  zone_label,
                    "structure": "Bullish MSS Confirmed",
                }

        # ── Bearish Signal ──────────────────────────────────────────────
        if (
            self.bear_active
            and self.bear_wick_pending
            and zone_cur_supply
            and self._wick_cleared_bear(cur, self.bear_wick_low)
        ):
            # [FIX 3] slice df ตั้งแต่แท่ง ChoCh จนถึง prev
            df_since_choch = df.iloc[self.bear_choch_idx: len(df) - 1]

            mss_ok = self._mss_bear(df_since_choch, self.bear_choch_low, self.bear_sl)

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
                    "pattern":   "ChoCh → Reversal Wick → Wick Cleared → MSS",
                    "htf_zone":  zone_label,
                    "structure": "Bearish MSS Confirmed",
                }

        return None