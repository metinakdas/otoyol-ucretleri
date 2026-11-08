# Tarife Radarı · Proje notları (devir dokümanı)

Bu belge, projeyi ilk kez gören bir geliştiricinin ya da başka bir yapay zekâ asistanının işi kaldığı
yerden sürdürebilmesi için yazıldı. Amaç, alınan kararlar ve nedenleri, mimari, mevcut durum ve sıradaki
adımlardır. Kullanım kılavuzu için `README.md`, veri dosyaları için `data/README.md` dosyasına bakın.

> Bu depo herkese açık yayınlanacak. Bu belgeye ve depoya kişisel bilgi (ad, e-posta, telefon, bilgisayar
> klasör yolu), Telegram anahtarı, sohbet kimliği ya da şifre yazmayın. `python -m radar yayinla` bunları
> yayın öncesi tarar ve bulursa gönderimi durdurur.

---

## 1. Sorun ve amaç

Proje sahibi bir **taksimetre hizmeti** işletiyor. Taksimetre sistemi, yolculuk sırasında oluşan ek ücretleri
(ör. Boğaz köprülerinden geçiş) otomatik hesaplıyor. Sorun şu:

- Köprü, tünel ve otoyol **geçiş ücretleri değişiyor** (genelde yılbaşında KGM tarifesiyle).
- Bayramlarda bazı geçişler **ücretsiz** oluyor (Bakanlık ya da KGM duyurusuyla, belirli saatler arasında).
- Bu değişiklikler sisteme zamanında girilmezse taksimetre yanlış ek ücret hesaplıyor.

**Amaç:** Bu değişiklikleri resmi kaynaklardan otomatik izleyip, **yürürlüğe girmeden önce** Telegram ve
e-postayla haber veren, ayrıca güncel durumu bir web panelinde gösteren bir "radar".

Önemli: Sistem **yalnızca bilgi verir**. Onay adımı yoktur (sahibin açık isteği: "telegramda onay
olmayacak, amacımız bilgimizin olması"). Taksimetre güncellemesini insan yapar.

### Kapsam kararları (sırasıyla)

1. İlk istek iki şeyi kapsıyordu: geçiş ücretleri **ve** şehir taksi tarifeleri (ör. Kocaeli açılış ücreti
   değişimi). Önce bir tasarım dokümanı istendi; kapsam Türkiye geneli, tüm geçişler (15 Temmuz, FSM, YSS,
   Avrasya Tüneli, otoyollar, diğer köprüler), bildirim Telegram + e-posta.
2. Ardından **taksi tarifeleri sonraki faza bırakıldı**; önce köprü/otoyol ücretleri.
3. **Tüm süreç ücretsiz olmalı:** ücretli API, sunucu ya da yapay zekâ servisi kullanılmaz.
4. **TollGuru API değerlendirildi, reddedildi:** Türkiye/TL desteği yok, yalnızca güzergâh ücreti hesaplar,
   gelecekteki değişiklikleri ve ücretsiz dönemleri bilmez, deneme sürümü sınırlı.
5. **WhatsApp kullanılmıyor:** WhatsApp Cloud API, 24 saatlik pencere dışındaki bildirim şablonları için
   mesaj başına ücretli. Telegram Bot API ücretsiz.
6. Arayüz istendi → web paneli. Sonra panele **ücretsiz harita**, isimli işaretler, arama, filtre ve
   **bölgelere ayırma** eklendi.
7. Son olarak **GitHub'da herkese açık depo** olarak yayınlama istendi; güvenlik en üst düzeyde olmalı:
   anahtarlar gizli kalmalı, kimse Telegram üzerinden sahibine ulaşamamalı.

---

## 2. Genel mimari (sıfır maliyet)

```
GitHub Actions (30 dk'da bir, cron)
   └─ python -m radar calistir
        ├─ kaynakları oku (KGM PDF tarifeleri, KGM/Bakanlık/Avrasya duyuruları)
        ├─ adayları kayıtlara dönüştür (yaşam döngüsü)
        ├─ takvim (bayram/yılbaşı izleme pencereleri)
        ├─ bildirim planla ve gönder (Telegram, e-posta)
        ├─ ayda bir OpenStreetMap'ten gişe konumlarını al (harita)
        └─ data/*.json yaz  → commit + push (Git = veritabanı)
   └─ panel işi: panel/ + data/panel.json + data/harita.json → GitHub Pages
```

- **Veritabanı yok:** Tüm durum `data/` altındaki JSON dosyalarında; her değişiklik bir commit. Geçmiş Git'te.
- **Yapay zekâ yok:** Ayıklama tamamen kural tabanlı (düzenli ifadeler, Türkçe tarih ayrıştırma, PDF tablo okuma).
- **Gizli bilgiler:** Yerelde `.env` (depo dışında), GitHub'da Secrets.
- Yerel çalıştırma da mümkün (Windows Görev Zamanlayıcı / Linux cron). Kamu siteleri yurt dışı IP'lerini
  engellerse radarın Türkiye'deki bir makinede çalıştırılması önerilir.

### Kaynaklar (`config/sources.yaml`)

| Kimlik | Tür | Ne izler |
| --- | --- | --- |
| `kgm-tarifeler` | `tarife_listesi` | KGM "UcretlerYeni.aspx" sayfasındaki yıllık PDF tarifeleri (yıl klasörü: `2026Gecis_Ucret/`) |
| `kgm-duyurular` | `liste` | KGM duyuruları |
| `uab-haberler`, `uab-duyurular`, `uab-basin` | `liste` | Ulaştırma ve Altyapı Bakanlığı |
| `avrasya-haberler` | `liste` | Avrasya Tüneli haber/duyuru sayfası |
| `avrasya-ucretler` | `sayfa` (kapalı) | Ücretler JavaScript ile yükleniyor, düz okunamıyor |
| `haber-*` | `rss` (kapalı) | Google News RSS; kullanım koşulları kontrol edilince açılabilir |

`tier: resmi` kaynak tek başına "karar" sayılır; `tier: haber` için aynı tarihi veren iki bağımsız yayın gerekir.

Doğrulanmış gerçek veri: 2026 KGM PDF'i (15 Temmuz & FSM) "01/01/2026 Saat 00:00'dan itibaren geçerlidir"
satırı ve sınıf ücretleri içerir (1. sınıf 59,00 TL; 6. sınıf motosiklet 25,00 TL). İkinci sütunun anlamı
belirsiz; yalnızca ilk sütun alınır. Diğer köprülerin PDF biçimi gerçek dosyada doğrulanmadı.

---

## 3. Kayıt yaşam döngüsü

Durumlar: `sinyal → gundemde → karar_cikti → yururlukte`; çıkışlar `kapandi` (14 gün teyitsiz) ve
`iptal_ertelendi`. Durum yalnızca ileri gider.

- **Karar kuralı:** resmi kaynak ya da aynı yürürlük tarihini veren iki bağımsız haber.
- **Ücret kararı** uygulanınca `data/crossings.json` defterine tarihli kayıt eklenir (eski kayıt silinmez,
  bitiş tarihi doldurulur). Bu defter ileride taksimetre sistemince okunabilir.
- **Ücretsiz geçiş kararı** `data/rules/` altına "ücret 0" kuralı olarak yazılır (başlangıç-bitiş saatiyle).
- **Etiketler** (belirsizlik bildirir): `kapsam_kontrol` (genel ifade, ör. "köprü ve otoyollar"),
  `saat_kontrol`, `tarih_belirsiz`, `degerler_okunamadi`, `olagan_disi` (düşüş ya da %100+ artış),
  `kacirildi` (yürürlükten sonra fark edildi) vb.
- **Genel ifadeli duyurular** varsayılan olarak yalnızca KGM geçişlerine uygulanır (YİD köprüleri genelde
  bayram ücretsizliğine dahil değildir); "yap-işlet-devret hariç" gibi ifadeler ayrıca yakalanır.
- **Takvim:** `config/calendar.yaml` içindeki dönemlerden (yılbaşı 21 gün, bayramlar 14 gün önce) izleme
  kaydı açılır. Bayram tarihleri yaklaşıktır, her yıl Diyanet takviminden güncellenmelidir.
- **İlk çalıştırma sessizdir:** mevcut durum başlangıç olarak kaydedilir, yalnızca "KURULUM" mesajı gider.

### Bildirimler

Karar (Telegram + e-posta), yürürlükten 7 ve 1 gün önce hatırlatma, yürürlük günü, ücretsiz geçiş bitişi,
tarih değişikliği, iptal, izleme penceresi açılışı (yalnız Telegram), 24 saatten uzun kaynak hatası (teknik
grup), günlük ve haftalık e-posta özeti. Aynı bildirim iki kez gitmez (`data/notifications.json`).

---

## 4. Kod haritası

| Dosya | Görev |
| --- | --- |
| `radar/cli.py` | Komutlar: `calistir`, `kaynak-testi`, `test-bildirim`, `panel`, `harita-guncelle`, `durum`, `yayinla` |
| `radar/pipeline.py` | Bir radar turu (`run_once`): oku → kayıtlar → bildirim → kaydet |
| `radar/collectors.py` | Kaynak türlerine göre okuyucular, KGM PDF değişiklik tespiti |
| `radar/extract.py` | Türkçe tarih/saat, TL tutarları, PDF sınıf tablosu, bağlantı ve metin çıkarma |
| `radar/matching.py` | Geçiş adlarını, ücret/ücretsiz/iptal ifadelerini ve hariç tutmaları tanıma |
| `radar/lifecycle.py` | Kayıt oluşturma, birleştirme, durum ilerletme, karar uygulama |
| `radar/prices.py` | Tarihli ücret defteri (`crossings.json`) |
| `radar/calendar.py` | Bayram/yılbaşı izleme pencereleri |
| `radar/notify.py`, `radar/messages.py` | Bildirim planı, Telegram/e-posta gönderimi, mesaj metinleri |
| `radar/panel.py` | `panel.json` üretimi ve kısıtlı yerel önizleme sunucusu |
| `radar/harita.py` | OpenStreetMap (Overpass) gişe verisi: sorgu, ayrıştırma, gruplama, aylık yenileme |
| `radar/bolgeler.py` | 81 il (plaka kodu) ve 7 coğrafi bölge |
| `radar/guvenlik.py` | Anahtar maskeleme, yalnızca http(s) bağlantı, gizli bilgi desenleri |
| `radar/yayin.py` | `python -m radar yayinla`: güvenlik taraması + GitHub'a yayın + depo sıkılaştırma |
| `radar/config.py` | `config/*.yaml` ve `.env` okuma, doğrulama |
| `radar/demo.py` | Panel için açıkça "örnek" etiketli veri |
| `panel/` | Tek sayfalık panel (vanilla JS), `harita.js` (Leaflet), `vendor/leaflet/` (1.9.4, BSD) |
| `.github/workflows/radar.yml` | 30 dakikalık çalışma + Pages yayını |
| `.github/workflows/testler.yml` | Her gönderimde testler (yalnız okuma yetkisi) |

---

## 5. Panel ve harita

- Bölümler: durum çubuğu, öne çıkan (aktif ücretsiz geçiş / yaklaşan değişiklik geri sayımı), güncel ücretler
  tablosu (1–6. sınıf seçici, satır ayrıntısında tüm sınıflar ve ücret geçmişi grafiği), bayram kartı, kaynak
  sağlığı, **ücretli geçiş haritası**, son kayıtlar, KGM belgeleri.
- **Harita:** Leaflet + OpenStreetMap karoları (ücretsiz, anahtarsız). Köprü/tünel işaretleri
  `config/crossings.yaml` içindeki yaklaşık `konum` alanından; otoyol gişeleri OpenStreetMap'teki
  `barrier=toll_booth` ve `highway=toll_gantry` noktalarından (il bazında Overpass sorgusu, bağlı yolun
  numarası ve adıyla). Aynı gişenin şeritleri tek noktada birleştirilir. Veri `data/harita.json`, ayda bir
  yenilenir; başarısız olursa eski veri korunur.
- Özellikler: çakışmasız isim etiketleri, uzaklaşınca İstanbul'daki köprülerin tek işarette toplanması,
  arama (diğer adlarla, ör. "Boğaz köprüsü" → 15 Temmuz), filtreler (il, otoyol, tür, durum), 7 bölge çipi
  ve bölgelere göre gruplanmış liste, tablo ile harita arasında karşılıklı bağlantı.
- Renkler: 3 kategori (köprü/tünel mavi, gişe turuncu, serbest geçiş yeşil), renk körlüğü denetiminden geçti;
  ayrıca şekille (kare/daire/karo) ayrılır. Açık/koyu tema, mobil uyumlu.

---

## 6. Güvenlik (yapılan denetim ve önlemler)

Araçlar: `detect-secrets`, `bandit`, `pip-audit` (temiz) ve elle inceleme. Düzeltilen sorunlar:

1. E-postada TLS sertifikası doğrulanmıyordu → `ssl.create_default_context()` ile doğrulanıyor.
2. Yerel panel sunucusu tüm klasörü (`.env` dahil) sunuyordu → yalnızca `panel/`, `data/panel.json`,
   `data/harita.json`; yalnızca localhost Host başlığı; klasör listesi kapalı.
3. Kaynak sitelerden gelen `javascript:` gibi bağlantılar → yalnızca http(s); panele CSP eklendi.
4. Actions yetkileri geniş → `permissions: {}` + iş bazında en az yetki; testler gizli bilgiye erişmez.
5. Bildirim kanalı tanımlı değilse radar çalışmaz (bildirimler "gönderildi" sayılıp kaybolmasın diye).
6. README'de kişisel klasör yolu vardı → kaldırıldı; yayın taraması bu tür yolları yakalar.
7. Hata mesajlarında anahtarlar maskelenir (`data/health.json` herkese açık depoda görünür).
8. Kaynak kodda görünmez/yön karakterleri kaçış dizilerine çevrildi; bağımlılık sürümleri sabitlendi.

Telegram tarafı: radar bota gelen mesajları hiç okumaz (getUpdates/webhook yok); yalnızca Secrets'taki
sohbet kimliklerine yazar. Önerilen BotFather ayarları: `/setjoingroups` Disable, `/setprivacy` Enable;
grup özel olmalı.

`python -m radar yayinla` depoyu şu ayarlarla açar: issue/wiki/proje/tartışma kapalı, yabancıların
etkileşimi 6 ay kapalı, Actions yalnızca GitHub eylemleri ve varsayılan okuma yetkisi, gizli bilgi taraması
ve gönderim koruması açık, ana dal silinemez/geçmişi değiştirilemez, Dependabot uyarıları açık. Commit,
kişisel e-posta yerine GitHub'ın `noreply` adresiyle yapılır; anahtarlar `gh secret set` ile standart
girdiden verilir.

---

## 7. Mevcut durum (Kasım 2026)

- Kod tamam; **45 test** var (internete çıkmadan, sahte sitelerle; yayın betiği sahte `gh` ve yerel
  git deposuyla uçtan uca test edildi). Yayın testlerinden 4'ü yalnızca Linux/macOS'ta çalışır.
- **GitHub'da yayında.** Depo adı `otoyol-ucretleri` (herkese açık); panel GitHub Pages'te
  `https://<kullanıcı-adı>.github.io/otoyol-ucretleri/` adresinde. Radar 30 dakikada bir Actions'ta çalışıyor;
  Telegram bildirimi doğrulandı (`python -m radar test-bildirim`). Yerelde Python 3.12 `.venv` içinde kurulu.
- **İlk gerçek turda bulunan ve düzeltilen sorunlar:**
  - Overpass ana sunucusu tarayıcı gibi görünen istemcileri `HTTP 406` ile reddediyordu; harita boş kaldı.
    Artık kendi adıyla (`TarifeRadari/0.2 …`) istek atılıyor, iki yedek sunucu eklendi, sorgu hafifletildi.
    Gerçek veriyle denendi: 370 gişe noktası (59'u serbest geçiş) alındı.
  - KGM tarife sayfasındaki tarife dışı PDF'ler (strateji planı vb.) belge olarak izleniyordu; artık
    yalnızca adında/adresinde "ücret" ya da "tarife" geçen PDF'ler izleniyor.
- Telegram bot anahtarı bir sohbet kaydında açıkça geçti; sahibi şimdilik yenilememeyi seçti. Yenilenirse:
  BotFather'da `/revoke`, yeni anahtarı `.env`'ye yaz, `python -m radar yayinla --yalnizca-ayarlar`.
- Dışarıdan erişim kısıtı (yabancıların issue/yorum/PR açamaması) altı ay sürer; aynı komutla yenilenir.

---

## 8. Bilinen sınırlar

- Avrasya Tüneli ücretleri okunamıyor (JavaScript); yalnızca duyurular izleniyor.
- Otoyol PDF'lerindeki gişe-gişe ücret matrisleri okunmuyor; yalnızca "belge değişti" bildiriliyor.
- YSS, Osmangazi ve 1915 Çanakkale PDF biçimleri doğrulanmadı.
- Bayram tarihleri yaklaşık; köprü konumları yaklaşık.
- OpenStreetMap gişe verisi eksik/adsız olabilir; OSM karo sunucusu küçük ekip kullanımı için uygun.
- GitHub sunucuları yurt dışında; kamu siteleri erişimi engellerse yerel çalıştırma gerekir.

---

## 9. Sıradaki adımlar

1. Actions günlüklerini birkaç gün izlemek (kaynak hataları teknik bildirim olarak Telegram'a da gelir).
2. `kaynak-testi` ile tüm kaynakları ve PDF ayrıştırmayı gerçek veride doğrulamak; gerekirse ayrıştırıcıyı uyarlamak.
3. `config/calendar.yaml`'a doğrulanmış 2027 bayram tarihlerini girmek.
4. **Sonraki faz – şehir taksi tarifeleri:** belediye ve UKOME karar sayfalarını yeni kaynak olarak eklemek;
   tarifeleri aynı tarihli defter yapısında (il bazında açılış, km, bekleme ücreti) tutmak; ilk iller cihaz
   sayısına göre seçilecek.
5. İsteğe bağlı: taksimetre sisteminin `data/crossings.json` ve `data/rules/` dosyalarını doğrudan okuması.

---

## 10. Çalışma kuralları (bu projede uyulan)

- Arayüz, mesajlar, yorumlar ve belgeler **Türkçe**.
- Ücretsiz kaynaklar dışında bir şey eklenmez.
- Testler internete çıkmaz (`httpx.MockTransport`); yeni özellik test olmadan eklenmez: `python -m pytest`.
- Dosyalar UTF-8 ve LF satır sonuyla yazılır (`.gitattributes`).
- `data/` dosyaları elle düzenlenmez; radar yazar.
- Hiçbir anahtar, kişisel bilgi ya da yerel yol depoya girmez; yayından önce `python -m radar yayinla --deneme`.
