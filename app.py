import os
import io
import time
import requests
from flask import Flask, request, send_file
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

FONT_PATH = "manga-font.ttf"

def get_optimal_font_and_wrap(text, font_path, max_width, max_height, draw):
    """
    Dinamik font boyutu ve metin kırma (word-wrap) hesaplayıcısı.
    Balonun genişliğine ve yüksekliğine en uygun font boyutunu bulur.
    """
    min_font_size = 11  # Okunabilirlik için alt sınır
    max_font_size = 40  # Çok devasa olmaması için üst sınır
    optimal_font_size = min_font_size
    optimal_wrapped_text = text

    # Büyük fonttan küçüğe doğru dene
    for size in range(max_font_size, min_font_size - 1, -1):
        try:
            font = ImageFont.truetype(font_path, size)
        except:
            font = ImageFont.load_default()

        # Metni bu font boyutuyla kırp
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + word + " "
            if draw.textlength(test_line, font=font) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
        
        wrapped_text = "\n".join(lines)
        
        # Kırpılmış metnin toplam sınırlarını hesapla
        left, top, right, bottom = draw.multiline_textbbox((0, 0), wrapped_text, font=font)
        text_w = right - left
        text_h = bottom - top
        
        # Eğer hesaplanan boyutlar balonun içine sığıyorsa, en iyi boyutu bulduk!
        if text_w <= max_width and text_h <= max_height:
            optimal_font_size = size
            optimal_wrapped_text = wrapped_text
            break
    
    # En iyi fontu yükle ve döndür
    try:
        final_font = ImageFont.truetype(font_path, optimal_font_size)
    except:
        final_font = ImageFont.load_default()
        
    return final_font, optimal_wrapped_text

def merge_boxes(boxes, margin=45):
    """Birbirine yakın olan Azure satırlarını tek bir 'Konuşma Balonu' olarak birleştirir."""
    if not boxes: return []
    boxes = sorted(boxes, key=lambda x: x['top'])
    merged = []
    for box in boxes:
        if not merged:
            merged.append(box)
            continue
        last = merged[-1]
        v_close = (box['top'] - last['bottom']) < margin
        h_overlap = not (box['left'] > last['right'] or box['right'] < last['left'])
        if v_close and h_overlap:
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
    azure_endpoint = request.form.get('azure_endpoint')
    azure_key = request.form.get('azure_key')
    deepl_key = request.form.get('deepl_key')

    if not azure_endpoint or not azure_key or not deepl_key:
        return {"error": "Azure veya DeepL API anahtarları eksik!"}, 400

    try:
        img = Image.open(image_file).convert("RGB")
    except Exception as e:
        return {"error": f"Görsel bozuk: {str(e)}"}, 400
    
    draw = ImageDraw.Draw(img)

    img_io = io.BytesIO()
    img.save(img_io, format='JPEG', quality=95)
    img_bytes = img_io.getvalue()

    endpoint_url = azure_endpoint.rstrip('/') + "/vision/v3.2/read/analyze"
    headers = {'Ocp-Apim-Subscription-Key': azure_key, 'Content-Type': 'application/octet-stream'}
    
    try:
        analyze_resp = requests.post(endpoint_url, headers=headers, data=img_bytes, timeout=30)
        analyze_resp.raise_for_status()
        operation_url = analyze_resp.headers["Operation-Location"]
        
        poll_headers = {'Ocp-Apim-Subscription-Key': azure_key}
        status = ""
        while status not in ["succeeded", "failed"]:
            time.sleep(1)
            poll_resp = requests.get(operation_url, headers=poll_headers)
            poll_data = poll_resp.json()
            status = poll_data.get("status")
        
        if status == "failed":
            return {"error": "Azure OCR işlemi başarısız oldu."}, 400

    except Exception as e:
        return {"error": f"Azure API Hatası: {str(e)}"}, 500

    analyze_result = poll_data.get("analyzeResult", {}).get("readResults", [])
    if not analyze_result:
        return {"error": "Azure sonuç döndürmedi."}, 400

    lines = analyze_result[0].get("lines", [])
    if not lines:
        return {"error": "Görselde metin bulunamadı."}, 400

    raw_boxes = []
    for line in lines:
        text = line.get("text", "")
        box = line.get("boundingBox", []) 
        if not text or len(box) != 8: continue
            
        l = min(box[0], box[2], box[4], box[6])
        t = min(box[1], box[3], box[5], box[7])
        r = max(box[0], box[2], box[4], box[6])
        b = max(box[1], box[3], box[5], box[7])
        raw_boxes.append({'text': text, 'left': l, 'top': t, 'right': r, 'bottom': b})

    bubbles = merge_boxes(raw_boxes)

    deepl_url = "https://api-free.deepl.com/v2/translate" if ":fx" in deepl_key else "https://api.deepl.com/v2/translate"
    deepl_headers = {"Authorization": f"DeepL-Auth-Key {deepl_key}"}
        
    for bubble in bubbles:
        width = bubble['right'] - bubble['left']
        height = bubble['bottom'] - bubble['top']

        pad = 8
        # Beyaz silgi kutusunu çiz
        draw.rounded_rectangle(
            [bubble['left'] - pad, bubble['top'] - pad, bubble['right'] + pad, bubble['bottom'] + pad], 
            radius=12, fill="white"
        )

        try:
            deepl_payload = {'text': bubble['text'], 'target_lang': 'TR'}
            deepl_resp = requests.post(deepl_url, headers=deepl_headers, data=deepl_payload, timeout=20)
            translated_text = deepl_resp.json()['translations'][0]['text']
        except:
            translated_text = bubble['text']

        # Dinamik Font ve Metin Kırma İşlemi (Pad değerlerini çıkararak tam iç kutuyu hedef alıyoruz)
        inner_max_width = width + (pad * 1.5)
        inner_max_height = height + (pad * 1.5)
        
        font, wrapped_text = get_optimal_font_and_wrap(translated_text, FONT_PATH, inner_max_width, inner_max_height, draw)
        
        center_x = bubble['left'] + (width / 2)
        center_y = bubble['top'] + (height / 2)
        
        draw.multiline_text((center_x, center_y), wrapped_text, fill="black", font=font, anchor="mm", align="center")

    final_io = io.BytesIO()
    img.save(final_io, 'JPEG', quality=95)
    final_io.seek(0)
    
    return send_file(final_io, mimetype='image/jpeg')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
