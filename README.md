# 🥇 AurumAI
> XAUUSD SMC + FinBERT Sentiment Signal Bot

บอทวิเคราะห์ทองคำ (XAUUSD) แบบอัตโนมัติ โดยรวม Smart Money Concepts (SMC) เข้ากับ FinBERT Sentiment Analysis แล้วส่งสัญญาณผ่าน Telegram — ฟรีทั้งระบบ $0/เดือน

---

## สิ่งที่ต้องเตรียม

| บริการ | ลิงก์สมัคร | ค่าใช้จ่าย |
|---|---|---|
| Telegram Account | [telegram.org](https://telegram.org) | ฟรี |
| GitHub Account | [github.com](https://github.com) | ฟรี |
| Twelve Data Account | [twelvedata.com](https://twelvedata.com) | ฟรี |
| Hugging Face Account | [huggingface.co](https://huggingface.co) | ฟรี |
| UptimeRobot Account | [uptimerobot.com](https://uptimerobot.com) | ฟรี |

---

## โครงสร้างโปรเจกต์

```
aurumAI/
├── app.py
├── smc_detector.py
├── sentiment_analyzer.py
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

### Phase 2 — สมัคร Twelve Data

1. ไปที่ **twelvedata.com** กด Sign Up ฟรี
2. ยืนยัน Email
3. ไปที่ Dashboard → **API Keys**
4. คัดลอก **API Key** เก็บไว้

```
ตัวอย่าง: a1b2c3d4e5f6789012345678
```

> **โควต้าฟรี:** 800 calls/วัน รีเซ็ตทุกวัน 07:00 น. (เวลาไทย)  
> ระบบนี้ใช้ ~720 calls/วัน ✅ พอดี

---

### Phase 3 — อัปโหลดโค้ดขึ้น GitHub

1. ไปที่ **github.com** → กด **New repository**
2. ตั้งชื่อ `aurumAI`
3. เลือก **Private** (แนะนำ ป้องกันคนอื่นเห็น Token)
4. กด **Create repository**
5. อัปโหลดไฟล์ทั้งหมด: กด **Add file** → **Upload files** → ลากไฟล์ใส่ → **Commit changes**

---

### Phase 4 — Deploy บน Hugging Face

**4.1 สร้าง Space**

ไปที่ **huggingface.co** → **New Space** แล้วตั้งค่าดังนี้:

| หัวข้อ | ค่าที่ต้องเลือก |
|---|---|
| Space name | `aurumAI` |
| License | MIT |
| SDK | **Docker** |
| Hardware | **CPU Basic (ฟรี)** |
| Visibility | Private |

**4.2 เชื่อมต่อ GitHub**

ใน Space → แท็บ **Files** → **Connect to GitHub repository** → เลือก `aurumAI`

**4.3 ตั้ง Environment Variables**

ไปที่ **Settings** → **Variables and Secrets** → **New secret**:

| Key | Value |
|---|---|
| `TWELVE_API_KEY` | API Key จาก Phase 2 |
| `TELEGRAM_TOKEN` | Token จาก Phase 1.1 |
| `CHAT_ID` | Chat ID จาก Phase 1.2 |

> ⚠️ ใช้ **Secret** ไม่ใช่ Variable เพื่อความปลอดภัย

**4.4 รอ Build**

ไปที่แท็บ **App** รอประมาณ 5–10 นาที (โหลด FinBERT ~400MB)  
เมื่อขึ้นสถานะ **Running** แสดงว่าพร้อมแล้ว ✅

---

### Phase 5 — ตั้ง UptimeRobot (กัน Space หลับ)

1. ไปที่ **uptimerobot.com** → สมัครฟรี → **Add New Monitor**
2. ตั้งค่า:

| หัวข้อ | ค่าที่ต้องใส่ |
|---|---|
| Monitor Type | HTTP(s) |
| Friendly Name | AurumAI Bot |
| URL | URL ของ HF Space คุณ |
| Monitoring Interval | **Every 30 minutes** |

> UptimeRobot จะ Ping Space ทุก 30 นาที ป้องกัน HF Pause Space

---

## ทดสอบระบบ

**เช็ค Live Log**

เปิดแท็บ **App** ดู Live Log ควรเห็น:

```
[HH:MM:SS] 🚀 Gold Market AI Analyzer started
[HH:MM:SS] 🤖 FinBERT model ready
```

**ทดสอบ Sentiment Analyzer**

ไปที่แท็บ **AI Sentiment Analyzer** พิมพ์:

```
Gold prices surge as Fed signals rate cuts
```

กด **Analyze Sentiment** ควรได้ผล % Positive/Negative/Neutral

**เช็ค Telegram**

รอถึง 14:00 น. (เวลาไทย) บอทจะส่งข้อความ:

```
🟢 Bot เริ่มทำงานแล้ว
```

---

## ตารางทำงานของบอท

| ช่วงเวลา (เวลาไทย) | สถานะ |
|---|---|
| 14:00 น. | 🟢 เริ่มทำงาน ส่งแจ้งเตือน |
| 14:00 – 02:00 น. | 🔍 สแกนสัญญาณทุก 1 นาที |
| 02:00 น. | 🔴 หยุดทำงาน ส่งสรุปสัญญาณ |
| 02:00 – 14:00 น. | ⏸ พัก รอ Session ถัดไป |
| เสาร์ – อาทิตย์ | ⏸ หยุดทั้งวัน ตลาดปิด |

---

## แก้ปัญหาเบื้องต้น

**บอทไม่ส่งข้อความ Telegram**
- เช็ค `TELEGRAM_TOKEN` และ `CHAT_ID` ว่าใส่ถูกต้อง
- ลองพิมพ์ข้อความหาบอทใน Telegram ก่อน 1 ครั้ง

**Space Build ไม่ผ่าน**
- เช็ค `requirements.txt` ว่าครบถ้วน
- ดู Build Log ใน HF ว่า Error อะไร

**ไม่มีสัญญาณเลย**
- SMC + Sentiment ต้องตรงกันทั้งคู่ สัญญาณจึงจะไม่ถี่ — ถือว่าปกติ
- เช็ค Live Log ว่า Scanning ทำงานปกติ

**Space หลับทั้งที่ตั้ง UptimeRobot แล้ว**
- เช็ค URL ที่ใส่ใน UptimeRobot ว่าถูกต้อง
- ลองเปลี่ยน Ping interval เป็น 15 นาที

---

## ค่าใช้จ่าย

| บริการ | แผน | ราคา |
|---|---|---|
| Telegram Bot | Free | $0 |
| Twelve Data | Free | $0 |
| Hugging Face Space | Free (CPU Basic) | $0 |
| UptimeRobot | Free | $0 |
| GitHub | Free | $0 |
| **รวม** | | **$0/เดือน** |

---

## License

MIT