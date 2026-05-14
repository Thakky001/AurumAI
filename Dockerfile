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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "jinja2==3.1.2" --force-reinstall

# ─── Patch gradio: remove localhost accessibility check ──────────
# Gradio 4.44 raises ValueError when HF Space proxy causes HEAD / → 500
# patch_gradio.py replaces the raise with a no-op so launch() continues
COPY patch_gradio.py /tmp/patch_gradio.py
RUN python3 /tmp/patch_gradio.py

# ─── Pre-download FinBERT Model ──────────────────
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='ProsusAI/finbert')"

# ─── Copy Source Code ────────────────────────────
COPY app.py .
COPY smc_detector.py .
COPY sentiment_analyzer.py .

# ─── Environment Variables ────────────────────────
ENV PORT=7860
ENV PYTHONUNBUFFERED=1

# ─── Expose Port ─────────────────────────────────
EXPOSE 7860

# ─── Run ─────────────────────────────────────────
CMD ["python", "app.py"]