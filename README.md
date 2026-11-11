# Liman İzleme

Seçilen limanlara uğrayan gemilerin açık, otomatik ve doğrulanabilir arşivi.

- İzlenen limanlara giren her gemiyi kaydeder ve sonraki hareketlerini takip eder.
- Her gün her liman için ziyaret listesi (CSV/JSON) ve harita görseli üretir.
- Açık denizde AIS kapatma, uzun durma, gemiden gemiye buluşma ve limansız su çekimi değişimini işaretler.
- Bir hükümet beyanını test eder: A ülkesi limanlarından B ülkesi limanlarına doğrudan ve dolaylı gemi hareketlerini sınıflandırır, muhtemel yükü dayanaklarıyla verir.
- Her günün dosyalarını SHA-256 ile hash'leyip birbirine zincirler ve Bitcoin blok zincirine damgalar (OpenTimestamps).
- Sonuçları statik bir web sitesi olarak `site/` klasörüne yazar; Netlify bu klasörü yayımlar.

Veri kaynağı: [aisstream.io](https://aisstream.io) (ücretsiz canlı AIS). MarineTraffic kullanılmaz.

## Nasıl çalışır

```
aisstream.io ──► sunucu (Google Cloud, 7/24) ──► GitHub (bu depo, site/ klasörü) ──► Netlify (web sitesi)
                   │                                 ▲
                   └── her saat site güncellenir ────┘  her gece bir gün arşivlenip mühürlenir
```

Gizli anahtarlar yalnızca sunucudaki `.env` dosyasında durur, GitHub'a gitmez.

## Kurulum (adım adım)

### 1. Hesaplar
1. **aisstream.io**: GitHub hesabınla giriş yap → *API Keys* → yeni anahtar oluştur. Anahtarı bir yere not et (bu sohbete veya GitHub'a yazma).
2. **Google Cloud** (cloud.google.com): kaydol, kartını ekle. Hemen *Billing → Budgets & alerts* bölümünden **1 dolarlık bütçe uyarısı** kur.
3. **Netlify** (netlify.com): *Sign up with GitHub*.

### 2. Sunucuyu aç (Google Cloud)
*Compute Engine → VM instances → Create instance* ve **yalnızca** şunları değiştir:

| Ayar | Değer |
| --- | --- |
| Region | `us-central1` (veya `us-west1` / `us-east1`) |
| Machine type | `e2-micro` |
| Boot disk | Ubuntu 24.04 LTS, **Standard persistent disk**, 30 GB |

Başka bölge, makine veya disk tipi seçersen ücretlendirilirsin. *Create*'e bas.

### 3. Kurulum komutu
Sunucunun yanındaki **SSH** düğmesine bas; açılan siyah pencereye şunu yapıştır:

```bash
curl -fsSL https://raw.githubusercontent.com/hakanul-barreyn/liman-izleme/main/kurulum/kur.sh | bash
```

Komut senden iki şey isteyecek:
- Ekranda yazan anahtarı GitHub'da *Settings → Deploy keys → Add deploy key* ile eklemen (**Allow write access** işaretli olmalı).
- aisstream.io anahtarını yapıştırman.

Gerisini kendisi kurar ve 7/24 çalışan bir servis başlatır.

### 4. Limanları ve beyanı gir
GitHub'da `config.yaml` dosyasını aç, kalem simgesiyle düzenle: limanları, ülkeleri ve beyan metnini yaz, *Commit changes*. Sunucu en geç 5 dakika içinde değişikliği görür ve başlar. Sonraki değişiklikler her gece otomatik alınır.

### 5. Siteyi yayınla
Netlify'de *Add new site → Import an existing project → GitHub → liman-izleme* → *Deploy*. Ayar gerekmez; `netlify.toml` hazır.

## Komutlar (sunucuda)

| Komut | Ne yapar |
| --- | --- |
| `sudo systemctl status liman` | Servis çalışıyor mu |
| `journalctl -u liman -f` | Canlı kayıtlar |
| `.venv/bin/python -m liman kontrol` | Ayarları ve anahtarı kontrol eder |
| `.venv/bin/python -m liman dogrula 2026-11-12` | Bir günün arşivini kanıt zincirine göre doğrular |
| `.venv/bin/python -m liman demo` | Kurgusal verilerle uçtan uca deneme (`demo/` klasörüne) |

## Bir günü bağımsız doğrulama
`site/arsiv/GÜN/` klasörünü indir, içinde `sha256sum -c MANIFEST.sha256` çalıştır. `sha256sum MANIFEST.sha256` çıktısı sitedeki *Kanıt zinciri* sayfasında yazan gün hash'iyle aynı olmalı. Bitcoin damgası için `ots verify MANIFEST.sha256.ots`.

## Sınırlar
- AIS'i tamamen kapalı olan gemiler görülmez; açık denizde alıcı kapsaması zayıf olabilir.
- Denizde buluşma ancak iki gemi de takipteyse görülür.
- Takip kapasitesi aynı anda 100 gemidir (aisstream bağlantı sınırları); aşılırsa en yeni takipler önceliklidir.
- Uydu doğrulaması (Sentinel-1 / Global Fishing Watch) henüz eklenmedi; ikinci aşamadadır.
- Sitedeki işaretler tespittir, hüküm değildir.
