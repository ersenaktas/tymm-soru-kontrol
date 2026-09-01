# Türkiye Yüzyılı Maarif Modeli (TYMM) Soru Kontrol Merkezi

Ortaöğretim Genel Müdürlüğü (OGM) Bağlam Temelli Çoktan Seçmeli Soru Kontrol ve Değerlendirme Modülü.

## 🚀 Özellikler

- **V7 Kural Motoru:** Güncel TYMM ölçütlerine göre otomatik soru analizi.
- **Çok Kullanıcılı Mimari (Multi-User):** Her öğretmen için izole oturum ve bağımsız rapor çıktısı.
- **Reverse Proxy & Subpath Uyumlu:** `ogmmateryal.eba.gov.tr/soru-inceleme/` veya bağımsız domainlerde tam uyumlu çalışma.
- **Word (.docx) ve PDF:** Kurumsal OGM rapor şablonuyla anında indirme.
- **Headless Xvfb / Playwright:** Ekran gerektirmeyen bulut ve sunucu mimarisi.

## 🛠️ Kurulum & Dağıtım (Deployment)

### Render.com ile Tek Tıkla Canlıya Alma
1. Bu depoyu GitHub hesabınıza push edin.
2. Render.com dashboard'unda **New +** -> **Web Service** seçin.
3. Reponuzu seçin -> Environment olarak **Docker** seçin.
4. Otomatik olarak `render.yaml` ve `Dockerfile` kullanılarak yayına alınacaktır.

### Manuel Docker Çalıştırma
```bash
docker build -t tymm-soru-kontrol .
docker run -d -p 8765:8765 --name soru-kontrol --restart always tymm-soru-kontrol
```

### Yerel Geliştirme (Python)
```bash
pip install -e ".[notebooklm,web]"
python -m playwright install chromium
python -m pilot.web
```
