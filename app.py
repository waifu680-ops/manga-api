import os
import io
import requests
import textwrap
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# Font dosyasının konumu (Aynı klasörde olmalı)
FONT_PATH = "manga-font.ttf"

def wrap_text(text, font, max_width, draw):
    """Metni balonun genişliğine göre alt alta böler."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + word + " "
        # getlength ile kelimenin pixel genişliğini ölç
        if draw.textlength(test_line, font=font) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line.strip())
            current_line = word + " "
    if current_line:
        lines.append(current_line.strip())
    return "\n".join(lines)

@app.route('/process-manga', methods=['POST'])
def process_manga():
    if 'image' not in request.files:
        return {"error": "Görsel eksik"}, 400

    image_file = request.files['image']
    ocr_key = request.form.get('ocr_key')
    deepl_key = request.form.get('deepl_key')
    source_lang = request.form.get('source_lang', 'eng')

    if not ocr_key or not deepl_key:
        return {"error": "API anahtarları eksik"}, 400

    # 1. Resmi Pillow ile Aç
    image_bytes = image_file.read()
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except:
        return {"error": "Geçersiz görsel formatı"}, 400
    
    draw = ImageDraw.Draw(img)

    # 2. OCR.Space API'ye Gönder
    ocr_payload = {'apikey': ocr_key, 'language': source_lang, 'isOverlayRequired': 'true', 'scale': 'true'}
    files = {'file': ('image.jpg', image_bytes, 'image/jpeg')}
    ocr_resp = requests.post('https://api.ocr.space/parse/image', data=ocr_payload, files=files)
    ocr_data = ocr_resp.json()

    # 3. Çeviri ve Pillow ile Çizim İşlemi
    deepl_url = "https://api-free.deepl.com/v2/translate" if ":fx" in deepl_key else "https://api.deepl.com/v2/translate"

    if 'ParsedResults' in ocr_data and ocr_data['ParsedResults'] and 'TextOverlay' in ocr_data['ParsedResults'][0]:
        lines = ocr_data['ParsedResults'][0]['TextOverlay'].get('Lines', [])
        
        for line in lines:
            original_text = line['LineText']
            
            # Koordinatları Bul
            words = line.get('Words', [])
            if not words: continue
            
            left = min([w['Left'] for w in words])
            top = min([w['Top'] for w in words])
            right = max([w['Left'] + w['Width'] for w in words])
            bottom = max([w['Top'] + w['Height'] for w in words])
            
            width = right - left
            height = bottom - top

            # Balonun içini beyaza boya (Pillow kalitesiyle)
            pad = 6 # Taşma payı
            draw.rectangle([left - pad, top - pad, right + pad, bottom + pad], fill="white")

            # DeepL Çevirisi
            deepl_payload = {'auth_key': deepl_key, 'text': original_text, 'target_lang': 'TR'}
            deepl_resp = requests.post(deepl_url, data=deepl_payload)
            deepl_data = deepl_resp.json()
            
            translated_text = original_text
            if 'translations' in deepl_data:
                translated_text = deepl_data['translations'][0]['text']

            # Metni Yazdırma (Font Büyüklüğünü Kutuya Göre Ayarla)
            font_size = max(12, int(height / 2)) if height < 40 else 16
            try:
                font = ImageFont.truetype(FONT_PATH, font_size)
            except:
                font = ImageFont.load_default()

            wrapped_text = wrap_text(translated_text, font, width + (pad*2), draw)
            
            # Yazıyı Siyah Renginde Bas
            draw.multiline_text((left, top), wrapped_text, fill="black", font=font, align="center")

    # 4. İşlenmiş Görseli Geri Döndür
    img_io = io.BytesIO()
    img.save(img_io, 'JPEG', quality=90)
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/jpeg')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
