# ─── Base Image ─────────────────────────────────
FROM python:3.11-slim

# ─── System Dependencies ─────────────────────────
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ─── Working Directory ───────────────────────────
WORKDIR /app

# ─── Install Python Dependencies ─────────────────
# Copy requirements ก่อนเพื่อใช้ Docker Cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Pre-download FinBERT Model ──────────────────
# โหลด Model ตอน Build ไม่ต้องโหลดซ้ำตอน Runtime
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='ProsusAI/finbert')"

# ─── Copy Source Code ────────────────────────────
COPY app.py .
COPY smc_detector.py .
COPY sentiment_analyzer.py .

# ─── Environment Variables (Default) ─────────────
ENV PORT=7860
ENV PYTHONUNBUFFERED=1
# HF Space requires these for Gradio to bind correctly
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860

# ─── Expose Port ─────────────────────────────────
EXPOSE 7860

# ─── Run ─────────────────────────────────────────
CMD ["python", "app.py"]