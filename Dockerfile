FROM python:3.9-slim

WORKDIR /app

# Gerekli paketleri kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tüm dosyaları kopyala
COPY . .

# Hugging Face 7860 portunu sever
ENV PORT=7860
EXPOSE 7860

# Gunicorn ile Flask'ı başlat (Zaman aşımını 120 saniyeye çıkardık!)
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:app", "--timeout", "120", "--workers", "2"]
