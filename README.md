# Liman İzleme

Seçilen limanlara uğrayan gemilerin açık, otomatik ve doğrulanabilir arşivi.

- İzlenen limanlara giren her gemiyi kaydeder ve sonraki hareketlerini takip eder.
- Her gün her liman için ziyaret listesi (CSV/JSON) ve harita görseli üretir.
- Açık denizde AIS kapatma, uzun durma, gemiden gemiye buluşma ve limansız su çekimi değişimini işaretler.
- Bir hükümet beyanını test eder: A ülkesi limanlarından B ülkesi limanlarına doğrudan ve dolaylı gemi hareketlerini sınıflandırır, muhtemel yükü dayanaklarıyla verir.
- Her günün dosyalarını SHA-256 ile hash'leyip birbirine zincirler ve Bitcoin blok zincirine damgalar (OpenTimestamps).
- Sonuçları statik bir web sitesi olarak üretir ve GitHub Pages'te yayımlar.

Veri kaynağı: [aisstream.io](https://aisstream.io) (ücretsiz canlı AIS). MarineTraffic kullanılmaz.

## Nasıl çalışır (GitHub ile ücretsiz)

```
aisstream.io ──► GitHub Actions (her saat ~52 dk toplar) ──► GitHub Pages (web sitesi)
                     │
                     ├─ site/arsiv, site/kanit  → bu depoya commit (kalıcı arşiv ve kanıt zinciri)
                     ├─ ham AIS verisi          → GitHub Releases (her gün bir sürüm: arsiv-GÜN)
                     └─ veritabanı              → 'durum' dalı (bir sonraki çalıştırma kaldığı yerden devam eder)
```

Kart veya telefon gerekmez. Bedeli: her saat birkaç dakikalık veri boşluğu olur (GitHub'ın zamanlayıcısı bazen
daha da gecikir). Bu boşluklar arşive ve siteye "kesinti" olarak yazılır, gizlenmez. İleride kesintisiz kayıt için
aynı kod bir sunucuya taşınabilir (aşağıda "Sunucu kurulumu").

## Kurulum (adım adım, yalnızca tarayıcıdan)

1. **aisstream.io anahtarı:** aisstream.io'ya GitHub hesabınla gir → *API Keys* → yeni anahtar oluştur ve kopyala.
2. **Anahtarı GitHub'a gizli olarak ekle:** bu depoda *Settings → Secrets and variables → Actions → New repository secret*.
   Name: `AISSTREAM_API_KEY`, Secret: kopyaladığın anahtar → *Add secret*. (Anahtarı başka hiçbir yere yazma.)
3. **Siteyi aç:** *Settings → Pages → Build and deployment → Source:* **GitHub Actions** seç.
4. **Limanları gir:** `config.yaml` dosyasını aç, kalem simgesiyle düzenle, limanları / ülkeleri / beyanı yaz, *Commit changes*.
5. **İlk çalıştırma:** *Actions* sekmesi → (istenirse *I understand… enable*) → solda **Liman izleme** → *Run workflow*.
   Yaklaşık bir saat sonra site `https://KULLANICI.github.io/liman-izleme/` adresinde açılır. Sonrası her saat kendiliğinden çalışır.

`config.yaml` sonradan ne zaman değişirse bir sonraki saatlik çalıştırma yeni ayarı kullanır.

## Sunucu kurulumu (isteğe bağlı, kesintisiz kayıt için)

Google Cloud'da ücretsiz bir `e2-micro` sunucu açıp (bölge `us-central1`, Standard disk 30 GB, Ubuntu 24.04)
SSH penceresine şunu yapıştır:

```bash
curl -fsSL https://raw.githubusercontent.com/hakanul-barreyn/liman-izleme/main/kurulum/kur.sh | bash
```

Sunucu modunda arşiv ve kanıt zinciri GitHub'a gönderilir; sitenin yayımı o aşamada ayrıca ayarlanır. Sunucuya geçersen Actions iş akışını kapat (*Actions → Liman izleme → ⋯ → Disable workflow*), ikisi aynı anda çalışmasın.

## Komutlar (bilgisayarda veya sunucuda)

| Komut | Ne yapar |
| --- | --- |
| `sudo systemctl status liman` | Servis çalışıyor mu |
| `journalctl -u liman -f` | Canlı kayıtlar |
| `.venv/bin/python -m liman kontrol` | Ayarları ve anahtarı kontrol eder |
| `.venv/bin/python -m liman dogrula 2026-11-12` | Bir günün arşivini kanıt zincirine göre doğrular |
| `.venv/bin/python -m liman demo` | Kurgusal verilerle uçtan uca deneme (`demo/` klasörüne) |

## Bir günü bağımsız doğrulama
`site/arsiv/GÜN/` klasörünü ve Releases'taki `arsiv-GÜN` sürümünden `ham.jsonl.gz` dosyasını aynı klasöre indir, içinde `sha256sum -c MANIFEST.sha256` çalıştır. `sha256sum MANIFEST.sha256` çıktısı sitedeki *Kanıt zinciri* sayfasında yazan gün hash'iyle aynı olmalı. Bitcoin damgası için `ots verify MANIFEST.sha256.ots`.

## Sınırlar
- AIS'i tamamen kapalı olan gemiler görülmez; açık denizde alıcı kapsaması zayıf olabilir.
- Denizde buluşma ancak iki gemi de takipteyse görülür.
- Takip kapasitesi aynı anda 100 gemidir (aisstream bağlantı sınırları); aşılırsa en yeni takipler önceliklidir.
- Uydu doğrulaması (Sentinel-1 / Global Fishing Watch) henüz eklenmedi; ikinci aşamadadır.
- Sitedeki işaretler tespittir, hüküm değildir.
