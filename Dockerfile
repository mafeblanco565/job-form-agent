FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# playwright install-deps instala automaticamente todas las dependencias
# del sistema necesarias para Chromium (compatible con Debian Bookworm)
RUN playwright install-deps chromium
RUN playwright install chromium

COPY . .

RUN mkdir -p web/uploads

ENV BROWSER_HEADLESS=true
ENV PORT=8000

EXPOSE 8000

CMD ["python", "start.py"]
