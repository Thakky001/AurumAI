# 🥇 AurumAI

> XAUUSD SMC + FinBERT Sentiment Signal Bot — 24/5 Mode

บอทวิเคราะห์ทองคำ (XAUUSD) แบบอัตโนมัติ โดยรวม Smart Money Concepts (SMC) เข้ากับ FinBERT Sentiment Analysis แล้วส่งสัญญาณผ่าน Telegram — ฟรีทั้งระบบ $0/เดือน

---

## สิ่งที่ต้องเตรียม

| บริการ               | ลิงก์สมัคร                                 | ค่าใช้จ่าย |
| -------------------- | ------------------------------------------ | ---------- |
| Telegram Account     | [telegram.org](https://telegram.org)       | ฟรี        |
| GitHub Account       | [github.com](https://github.com)           | ฟรี        |
| Polygon.io Account   | [polygon.io](https://polygon.io)           | ฟรี        |
| Cloudflare Account   | [cloudflare.com](https://cloudflare.com)   | ฟรี        |
| Hugging Face Account | [huggingface.co](https://huggingface.co)   | ฟรี        |
| UptimeRobot Account  | [uptimerobot.com](https://uptimerobot.com) | ฟรี        |

---

## โครงสร้างโปรเจกต์

```
aurumAI/
├── app.py
├── smc_detector.py
├── sentiment_analyzer.py
├── patch_gradio.py
├── requirements.txt
├── Dockerfile
└── .dockerignore
```

---

## การติดตั้ง

### Phase 1 — สร้าง Telegram Bot

**1.1 สร้างบอทผ่าน BotFather**

1. เปิด Telegram ค้นหา **@BotFather**
2. พิมพ์ `/newbot`
3. ตั้งชื่อบอท เช่น `AurumAI Signal`
4. ตั้ง Username ต้องลงท้ายด้วย `bot` เช่น `aurumaisignal_bot`
5. คัดลอก **HTTP API Token** เก็บไว้

```
ตัวอย่าง: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
```

**1.2 หา Chat ID**

1. กด **Start** เพื่อเริ่มแชทกับบอท
2. พิมพ์ข้อความอะไรก็ได้ เช่น `Hello`
3. เปิดเบราว์เซอร์ไปที่ URL นี้ (แทน `YOUR_TOKEN` ด้วย Token จริง):

```
https://api.telegram.org/botYOUR_TOKEN/getUpdates
```

4. มองหา `"chat":{"id":` แล้วคัดลอกตัวเลข เช่น `987654321`

---

### Phase 2 — สมัคร Polygon.io API

1. ไปที่ **polygon.io** กด **Get Started Free** (ฟรี)
2. ยืนยัน Email แล้ว Login
3. ไปที่ Dashboard → **API Keys**
4. คัดลอก **Default Key** เก็บไว้

```
ตัวอย่าง: abcd1234EfGhIjKlMnOpQrStUvWxYz01
```

> **โควต้าฟรี:** 5 calls/นาที = 300 calls/ชั่วโมง ✅  
> ระบบนี้ (scan ทุก 12 วินาที) ใช้พอดี 5 calls/นาที — ไม่เกินแน่นอน  
> **หมายเหตุ:** ข้อมูล Forex บัญชีฟรีของ Polygon.io มี delay ~15 นาที ซึ่งเหมาะสมกับ M15 Strategy ของเรา

---

### Phase 3 — สร้าง Cloudflare Worker (Telegram Relay)

HF Space บล็อก outbound connection ไปยัง api.telegram.org โดยตรง จึงต้องใช้ Cloudflare Worker เป็นตัวกลางส่งข้อความ ฟรี 100,000 requests/วัน ไม่มีวันหมดอายุ

**3.1 สมัครและสร้าง Worker**

1. ไปที่ **cloudflare.com** → สมัครฟรี → ยืนยัน Email
2. ใน Dashboard ไปที่ **Workers & Pages** → กด **Create**
3. เลือก **Start with Hello World!**
4. ตั้งชื่อ Worker เช่น `telegram-relay` → กด **Deploy**
5. หลัง Deploy เสร็จ กด **Edit code**

**3.2 วางโค้ด Worker**

ลบโค้ดเดิมทั้งหมดออก แล้ววางโค้ดนี้แทน:

```javascript
export default {
  async fetch(request) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const body = await request.json();
    const { token, chat_id, text } = body;

    if (!token || !chat_id || !text) {
      return new Response("Missing fields", { status: 400 });
    }

    const tgRes = await fetch(
      `https://api.telegram.org/bot${token}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id, text, parse_mode: "HTML" }),
      },
    );

    const result = await tgRes.json();
    return new Response(JSON.stringify(result), {
      status: tgRes.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};
```

6. กด **Deploy** อีกครั้ง
7. คัดลอก **Worker URL** ที่แสดงด้านบน รูปแบบจะเป็น:

```
https://telegram-relay.ชื่อuser.workers.dev
```

---

### Phase 4 — อัปโหลดโค้ดขึ้น GitHub

1. ไปที่ **github.com** → กด **New repository**
2. ตั้งชื่อ `aurumAI`
3. เลือก **Private** (แนะนำ ป้องกันคนอื่นเห็น Token)
4. กด **Create repository**
5. อัปโหลดไฟล์ทั้งหมด: กด **Add file** → **Upload files** → ลากไฟล์ใส่ → **Commit changes**

---

### Phase 5 — Deploy บน Hugging Face

**5.1 สร้าง Space**

ไปที่ **huggingface.co** → **New Space** แล้วตั้งค่าดังนี้:

| หัวข้อ     | ค่าที่ต้องเลือก     |
| ---------- | ------------------- |
| Space name | `aurumAI`           |
| License    | MIT                 |
| SDK        | **Docker**          |
| Hardware   | **CPU Basic (ฟรี)** |
| Visibility | Private             |

**5.2 เชื่อมต่อ GitHub**

ใน Space → แท็บ **Files** → **Connect to GitHub repository** → เลือก `aurumAI`

**5.3 ตั้ง Environment Variables**

ไปที่ **Settings** → **Variables and Secrets** → **New secret**:

| Key                | Value                    |
| ------------------ | ------------------------ |
| `POLYGON_API_KEY`  | API Key จาก Phase 2      |
| `TELEGRAM_TOKEN`   | Token จาก Phase 1.1      |
| `CHAT_ID`          | Chat ID จาก Phase 1.2    |
| `CLOUDFLARE_RELAY` | Worker URL จาก Phase 3.2 |

> ⚠️ ใช้ **Secret** ไม่ใช่ Variable เพื่อความปลอดภัย  
> ถ้ามี `TIINGO_API_KEY` เดิมอยู่ ลบทิ้งได้เลย

**5.4 รอ Build**

ไปที่แท็บ **App** รอประมาณ 5–10 นาที (โหลด FinBERT ~400MB)  
เมื่อขึ้นสถานะ **Running** แสดงว่าพร้อมแล้ว ✅

---

### Phase 6 — ตั้ง UptimeRobot (กัน Space หลับ)

1. ไปที่ **uptimerobot.com** → สมัครฟรี → **Add New Monitor**
2. ตั้งค่า:

| หัวข้อ              | ค่าที่ต้องใส่                       |
| ------------------- | ----------------------------------- |
| Monitor Type        | HTTP(s)                             |
| Friendly Name       | AurumAI Bot                         |
| URL                 | `https://ชื่อuser-aurumAI.hf.space` |
| Monitoring Interval | **Every 15 minutes**                |

> **วิธีหา URL ที่ถูกต้อง:** เข้า Space → กด ⋮ (สามจุด) มุมขวาบน → **Embed this Space** → คัดลอก URL รูปแบบ `*.hf.space`

---

## ทดสอบระบบ

**เช็ค Live Log**

เปิดแท็บ **App** ดู Live Log ควรเห็น:

```
[HH:MM:SS] 🚀 Gold Market AI Analyzer started (24/5 Mode)
[HH:MM:SS] 🤖 FinBERT model ready
[HH:MM:SS] ☁️ Telegram relay: Cloudflare Worker
[HH:MM:SS] 🟢 Market Opened — Starting Scan
[HH:MM:SS] 🔍 Scanning... price=XXXX.XX | Sentiment=NEUTRAL
```

> ถ้าขึ้น `📡 Telegram relay: Direct` แทน แสดงว่ายังไม่ได้ตั้ง `CLOUDFLARE_RELAY`

**ทดสอบ Sentiment Analyzer**

ไปที่แท็บ **AI Sentiment Analyzer** พิมพ์:

```
Gold prices surge as Fed signals rate cuts
```

กด **Analyze Sentiment** ควรได้ผล % Positive/Negative/Neutral

**เช็ค Telegram**

บอทจะส่งข้อความเมื่อตลาดเปิด (วันจันทร์ 05:00 น. ไทย):

```
🟢 ตลาดเปิดแล้ว — เริ่มสัปดาห์ใหม่
```

---

## ตารางทำงานของบอท

| ช่วงเวลา (UTC)        | ช่วงเวลา (ไทย)  | สถานะ                      |
| --------------------- | --------------- | -------------------------- |
| อาทิตย์ 22:00 UTC     | จันทร์ 05:00 น. | 🟢 ตลาดเปิด ส่งแจ้งเตือน   |
| จันทร์ – ศุกร์ตลอดวัน | ตลอดสัปดาห์     | ⚡ สแกนสัญญาณทุก 12 วินาที |
| ศุกร์ 22:00 UTC       | เสาร์ 05:00 น.  | 🔴 ตลาดปิด ส่งสรุปสัญญาณ   |
| เสาร์ – อาทิตย์       | เสาร์ – อาทิตย์ | ⏸ พัก ตลาดปิด (Weekend)    |

> Sentiment จะ Refresh ทุก **60 นาที** เพื่อประหยัดทรัพยากร

---

## แก้ปัญหาเบื้องต้น

**บอทไม่ส่งข้อความ Telegram**

- เช็ค `TELEGRAM_TOKEN` และ `CHAT_ID` ว่าใส่ถูกต้อง
- เช็ค `CLOUDFLARE_RELAY` ว่า URL ถูกต้องและ Worker Deploy แล้ว
- ลองพิมพ์ข้อความหาบอทใน Telegram ก่อน 1 ครั้ง

**Space Build ไม่ผ่าน**

- เช็ค `requirements.txt` ว่าครบถ้วน
- ดู Build Log ใน HF ว่า Error อะไร

**ขึ้น `⚠️ ขาด POLYGON_API_KEY` ใน Log**

- เช็คว่าตั้ง Secret ชื่อ `POLYGON_API_KEY` ถูกต้องใน HF Settings
- Rebuild Space หลังจากเพิ่ม Secret

**ขึ้น `429 Too Many Requests` ใน Log**

- Polygon free tier จำกัด 5 calls/นาที — ตรวจสอบว่า `POLL_SECONDS = 12` ยังอยู่ครบ
- ถ้ายังเกิด ให้เช็คว่าไม่ได้รัน Space หลายอันพร้อมกันด้วย API Key เดียวกัน

**ไม่มีสัญญาณเลย**

- SMC + Sentiment ต้องตรงกันทั้งคู่ สัญญาณจึงจะส่ง — ถือว่าปกติ
- เช็ค Live Log ว่าขึ้น `🔍 Scanning...` ทุก 30 วินาที

**Space หลับทั้งที่ตั้ง UptimeRobot แล้ว**

- เช็ค URL ที่ใส่ใน UptimeRobot ว่าเป็น `*.hf.space` ไม่ใช่ `huggingface.co/spaces/...`
- ลองเปลี่ยน Ping interval เป็น 15 นาที

---

## ค่าใช้จ่าย

| บริการ             | แผน                 | ราคา         |
| ------------------ | ------------------- | ------------ |
| Telegram Bot       | Free                | $0           |
| Polygon.io API     | Free (5 req/min)    | $0           |
| Cloudflare Workers | Free (100k req/วัน) | $0           |
| Hugging Face Space | Free (CPU Basic)    | $0           |
| UptimeRobot        | Free                | $0           |
| GitHub             | Free                | $0           |
| **รวม**            |                     | **$0/เดือน** |

---

## License

MIT
