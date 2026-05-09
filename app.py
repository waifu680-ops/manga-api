import os
import io
import requests
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

FONT_PATH = "manga-font.ttf"

def wrap_text(text, font, max_width, draw):
    """Metni balonun genişliğine göre akıllıca alt alta böler."""
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + word + " "
        if draw.textlength(test_line, font=font) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line.strip())
            current_line = word + " "
    if current_line:
        lines.append(current_line.strip())
    return "\n".join(lines)

def merge_boxes(boxes, margin=45):
    """Birbirine yakın olan metin satırlarını tek bir 'Konuşma Balonu' olarak birleştirir."""
    if not boxes: return []
    
    # Yukarıdan aşağıya doğru sırala
    boxes = sorted(boxes, key=lambda x: x['top'])
    merged = []
    
    for box in boxes:
        if not merged:
            merged.append(box)
            continue
            
        last = merged[-1]
        
        # Dikey yakınlık ve yatay kesişim kontrolü
        v_close = (box['top'] - last['bottom']) < margin
        h_overlap = not (box['left'] > last['right'] or box['right'] < last['left'])
        
        if v_close and h_overlap:
            # Kutuları birleştir (Balonu büyüt)
            last['text'] += " " + box['text']
            last['left'] = min(last['left'], box['left'])
            last['top'] = min(last['top'], box['top'])
            last['right'] = max(last['right'], box['right'])
            last['bottom'] = max(last['bottom'], box['bottom'])
        else:
            merged.append(box)
            
    return merged

@app.route('/process-manga', methods=['POST'])
def process_manga():
    if 'image' not in request.files:
        return {"error": "Görsel eksik."}, 400

    image_file = request.files['image']
    ocr_key = request.form.get('ocr_key')
    deepl_key = request.form.get('deepl_key')
    source_lang = request.form.get('source_lang', 'eng')

    # 1. Pillow ile Görseli Aç
    try:
        img = Image.open(image_file).convert("RGB")
    except Exception as e:
        return {"error": f"Görsel bozuk: {str(e)}"}, 400
    
    draw = ImageDraw.Draw(img)

    # 2. OCR İçin JPEG'e Çevir
    ocr_io = io.BytesIO()
    img.save(ocr_io, format='JPEG', quality=95)
    ocr_io.seek(0)

    # 3. OCR.Space API İsteği
    ocr_payload = {'apikey': ocr_key, 'language': source_lang, 'isOverlayRequired': 'true', 'scale': 'true'}
    files = {'file': ('image.jpg', ocr_io.read(), 'image/jpeg')}
    
    try:
        ocr_resp = requests.post('https://api.ocr.space/parse/image', data=ocr_payload, files=files, timeout=40)
        ocr_data = ocr_resp.json()
    except Exception as e:
        return {"error": f"OCR Çöktü: {str(e)}"}, 500

    if ocr_data.get('IsErroredOnProcessing') or not ocr_data.get('ParsedResults'):
        return {"error": "OCR görseli okuyamadı."}, 400

    lines = ocr_data['ParsedResults'][0].get('TextOverlay', {}).get('Lines', [])
    if not lines:
        return {"error": "Görselde metin bulunamadı."}, 400

    # Satırların koordinatlarını çıkar
    raw_boxes = []
    for line in lines:
        words = line.get('Words', [])
        if not words: continue
        l = min([w['Left'] for w in words])
        t = min([w['Top'] for w in words])
        r = max([w['Left'] + w['Width'] for w in words])
        b = max([w['Top'] + w['Height'] for w in words])
        raw_boxes.append({'text': line['LineText'], 'left': l, 'top': t, 'right': r, 'bottom': b})

    # Satırları BALONLARA dönüştür (Kümele)
    bubbles = merge_boxes(raw_boxes)

    # 4. Her Bir Balonu İşle
    deepl_url = "https://api-free.deepl.com/v2/translate" if ":fx" in deepl_key else "https://api.deepl.com/v2/translate"
    deepl_headers = {"Authorization": f"DeepL-Auth-Key {deepl_key}"}
        
    for bubble in bubbles:
        width = bubble['right'] - bubble['left']
        height = bubble['bottom'] - bubble['top']

        # Zemin Temizleme (Yuvarlatılmış Dikdörtgen ile daha şık bir silgi)
        pad = 8
        draw.rounded_rectangle(
            [bubble['left'] - pad, bubble['top'] - pad, bubble['right'] + pad, bubble['bottom'] + pad], 
            radius=10, fill="white"
        )

        # DeepL ile Çeviri
        try:
            deepl_payload = {'text': bubble['text'], 'target_lang': 'TR'}
            deepl_resp = requests.post(deepl_url, headers=deepl_headers, data=deepl_payload, timeout=20)
            translated_text = deepl_resp.json()['translations'][0]['text']
        except:
            translated_text = bubble['text'] # Çeviri çökerse orijinali yaz

        # Font Boyutunu Balona Göre Dinamik Hesapla
        font_size = max(14, int(height / 4)) if height > 40 else 14
        try:
            font = ImageFont.truetype(FONT_PATH, font_size)
        except:
            font = ImageFont.load_default()

        # Metni Kırp ve Hizala
        wrapped_text = wrap_text(translated_text, font, width + pad, draw)
        
        # Tam Merkez Koordinatını Bul (Pillow mm anchor özelliği)
        center_x = bubble['left'] + (width / 2)
        center_y = bubble['top'] + (height / 2)
        
        # Yazıyı kusursuzca ortalayarak bas
        draw.multiline_text((center_x, center_y), wrapped_text, fill="black", font=font, anchor="mm", align="center")

    # 5. Sonucu Döndür
    img_io = io.BytesIO()
    img.save(img_io, 'JPEG', quality=95)
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/jpeg')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
