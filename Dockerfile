FROM python:3.11-slim

# Dependencias del sistema para Playwright + Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpangocairo-1.0-0 libpango-1.0-0 libcairo2 \
    libatspi2.0-0 libx11-6 libxcb1 libxext6 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium de Playwright
RUN playwright install chromium --with-deps

COPY . .

# Crear directorio de uploads
RUN mkdir -p web/uploads

ENV BROWSER_HEADLESS=true
ENV PORT=8000

EXPOSE 8000

CMD uvicorn web.app:app --host 0.0.0.0 --port ${PORT}
