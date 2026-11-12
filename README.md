# Liman İzleme: Türkiye → İsrail

Türk limanlarından (İskenderun Körfezi/Ceyhan, Aliağa, Mersin, İstanbul-Ambarlı, İzmit) çıkıp İsrail limanlarına
doğrudan veya dolaylı yoldan (Mısır, Kıbrıs, Yunanistan, Bulgaristan üzerinden; denizde gemiden gemiye aktarmayla;
AIS kapatılarak) giden gemilerin açık, otomatik ve doğrulanabilir kaydı. Ayarlar `config.yaml` dosyasında.

- İzlenen limanlara giren her gemiyi kaydeder ve sonraki hareketlerini takip eder.
- Her gün her liman için ziyaret listesi (CSV/JSON) ve harita görseli üretir.
- Açık denizde AIS kapatma, uzun durma, gemiden gemiye buluşma ve limansız su çekimi değişimini işaretler.
- Resmî açıklamaları test eder: Türkiye ↔ İsrail gemi hareketlerini sınıflandırır (doğrudan, ara duraklı, karanlık bacak, denizde buluşma, dolaylı, İsrail kıyısında AIS kapatma, varış limanı kayıtsız karanlık sefer) ve muhtemel yükü dayanaklarıyla verir.
- İsrail kıyısında yaygın olan GPS karıştırma / sahte konumları ayıklar ve işaretler.
- Şüpheli kayıtlar için İsrail limanlarının o tarihlerdeki Sentinel-1/2 uydu görüntülerine bağlantı verir.
- Global Fishing Watch verisiyle Mayıs 2024'ten bugüne geçmişe dönük tarama yapar.
- Her günün dosyalarını SHA-256 ile hash'leyip birbirine zincirler ve Bitcoin blok zincirine damgalar (OpenTimestamps).
- Sonuçları statik bir web sitesi olarak üretir ve GitHub Pages'te yayımlar.

Veri kaynağı: [aisstream.io](https://aisstream.io) (ücretsiz canlı AIS). MarineTraffic kullanılmaz.

## Nasıl çalışır (GitHub ile ücretsiz)

```
aisstream.io ──► GitHub Actions (her saat ~48 dk toplar) ──► GitHub Pages (web sitesi)
                     │
                     ├─ site/arsiv, site/kanit  → bu depoya commit (kalıcı arşiv ve kanıt zinciri)
                     ├─ ham AIS verisi          → GitHub Releases (her gün bir sürüm: arsiv-GÜN)
                     └─ veritabanı              → Actions önbelleği (bir sonraki çalıştırma kaldığı yerden devam eder)
Global Fishing Watch ──► geçmiş tarama (her çalıştırmada birkaç dakika ilerler, bitene kadar)
```

Kart veya telefon gerekmez. Bedeli: her saat birkaç dakikalık veri boşluğu olur (GitHub'ın zamanlayıcısı bazen
daha da gecikir). Bu boşluklar arşive ve siteye "kesinti" olarak yazılır, gizlenmez. İleride kesintisiz kayıt için
aynı kod bir sunucuya taşınabilir (aşağıda "Sunucu kurulumu").

## Kurulum (adım adım, yalnızca tarayıcıdan)

1. **aisstream.io anahtarı:** aisstream.io'ya GitHub hesabınla gir → *API Keys* → yeni anahtar oluştur ve kopyala.
2. **Anahtarı GitHub'a gizli olarak ekle:** bu depoda *Settings → Secrets and variables → Actions → New repository secret*.
   Name: `AISSTREAM_API_KEY`, Secret: kopyaladığın anahtar → *Add secret*. (Anahtarı başka hiçbir yere yazma.)
3. **Siteyi aç:** *Settings → Pages → Build and deployment → Source:* **GitHub Actions** seç.
4. **(Geçmiş tarama için) Global Fishing Watch anahtarı:** globalfishingwatch.org/our-apis adresinden ücretsiz kaydol
   (kullanım amacı: ticari olmayan, kamuya açık deniz trafiği araştırması), API token oluştur. GitHub'a 2. adımdaki gibi
   `GFW_API_TOKEN` adıyla ekle.
5. **İlk çalıştırma:** *Actions* sekmesi → (istenirse *I understand… enable*) → solda **Liman izleme** → *Run workflow*.
   Geçmiş taramayı başlatmak için *gecmis_baslangic* kutusuna `2024-05-02` yaz. Tarama sonraki saatlik çalıştırmalarda
   kendiliğinden devam eder; ilerlemesi sitedeki *Geçmiş tarama* sayfasında görünür.
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
- AIS'i tamamen kapalı olan gemiler görülmez; açık denizde alıcı kapsaması zayıf olabilir. İsrail'e giden gemilerin
  önemli bir kısmının kıyıya yaklaşırken AIS'i kapattığı bildiriliyor; bu yüzden "kıyıda AIS kapandı" ve "karanlık sefer"
  sınıfları var. Bu sınıflar bir varışı kanıtlamaz; uydu bağlantılarıyla elle doğrulanmalıdır.
- İsrail kıyısında GPS karıştırma yaygın; imkânsız konum sıçramaları analize alınmaz ama kayıt altında tutulur.
- Denizde buluşma ancak iki gemi de dinleniyorsa görülür (takipteki gemiler ve `izleme_alanlari`).
- Canlı takip kapasitesi aynı anda 100 gemidir; aşılırsa tankerler ve şüpheli varış beyanı olanlar önceliklidir.
- Liman ve terminal koordinatları yaklaşık ve geniş çizildi; ilk haftanın verisine göre daraltılabilir.
- Konteyner gemilerinde yükün aktarma limanında başka gemiye geçmesi AIS ile izlenemez.
- Geçmiş tarama GFW'nin hesapladığı olaylara dayanır ve bu sitenin kanıt zincirinde ham verisi yoktur.
  GFW API'si buradan canlı olarak denenmedi; ilk çalıştırmada hata çıkarsa Actions kayıtlarında görünür.
- Sitedeki işaretler tespittir, hüküm değildir. Kayıtlar gemi hareketini gösterir; yükün sahibini veya hukuki
  durumunu göstermez.
