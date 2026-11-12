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
5. **WhatsApp yalnızca test numarasıyla:** WhatsApp Cloud API'nin gerçek işletme numarasında şablon mesajları
   ücretli. Kasım 2026'da Meta'nın ücretsiz test numarası eklendi (en fazla 5 doğrulanmış alıcı: sahibi ve
   arkadaşları). Telegram'a giden ana bildirimlerin kopyası tek değişkenli `otoyol_bildirim` şablonuyla gider;
   her alıcı `<anahtar>#wa1`, `#wa2`… ile ayrı işaretlenir (numara data/ klasörüne yazılmaz). WhatsApp hatası
   bildirimi "gönderilemedi" saymaz; Telegram yinelenmez, hata günlüğe yazılır.
6. Arayüz istendi → web paneli. Sonra panele **ücretsiz harita**, isimli işaretler, arama, filtre ve
   **bölgelere ayırma** eklendi.
7. Son olarak **GitHub'da herkese açık depo** olarak yayınlama istendi; güvenlik en üst düzeyde olmalı:
   anahtarlar gizli kalmalı, kimse Telegram üzerinden sahibine ulaşamamalı.
8. **Saat dilimi izleme** (Kasım 2026): Bir ülkenin saat farkı değişince bildirim istendi. Windows'un kendi
   verisi GitHub'ın Linux sunucusundan okunamadığı için tüm işletim sistemlerinin kaynağı olan IANA tz veritabanı
   (`tzdata` paketi) izleniyor. Paket her turda yükseltiliyor (sürüm sabitleme kuralının tek istisnası; yalnızca
   veri). Sürüm yükselince aynı 400 günlük pencere yeni kurallarla hesaplanıp eski görüntüyle karşılaştırılıyor;
   paket eskiyse (yerel bilgisayar) hiçbir şey yapılmıyor. Ülke adları IANA'nın İngilizce listesinden.

---

## 2. Genel mimari (sıfır maliyet)

```
GitHub Actions (30 dk'da bir, cron)
   └─ python -m radar calistir
        ├─ kaynakları oku (KGM PDF tarifeleri, KGM/Bakanlık/Avrasya duyuruları)
        ├─ adayları kayıtlara dönüştür (yaşam döngüsü)
        ├─ takvim (bayram/yılbaşı izleme pencereleri)
        ├─ bildirim planla ve gönder (Telegram, e-posta)
        ├─ otoyol ücret tabloları (KGM PDF) + gişe konumları (config/giseler.yaml, bizim kaydımız)
        └─ data/*.json yaz  → commit + push (Git = veritabanı)
   └─ panel işi: panel/ + data/panel.json + data/ucret-tablosu.json → GitHub Pages
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
| `avrasya-ucretler` | `avrasya_ucret` | Sitenin ücret sayfasının kullandığı JSON (`/api/toll/priceHtml`); `radar/avrasya.py` |
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
| `radar/cli.py` | Komutlar: `calistir`, `kaynak-testi`, `test-bildirim`, `panel`, `ucret-tablosu`, `durum`, `yayinla` |
| `radar/pipeline.py` | Bir radar turu (`run_once`): oku → kayıtlar → bildirim → kaydet |
| `radar/collectors.py` | Kaynak türlerine göre okuyucular, KGM PDF değişiklik tespiti |
| `radar/extract.py` | Türkçe tarih/saat, TL tutarları, PDF sınıf tablosu, bağlantı ve metin çıkarma |
| `radar/matching.py` | Geçiş adlarını, ücret/ücretsiz/iptal ifadelerini ve hariç tutmaları tanıma |
| `radar/lifecycle.py` | Kayıt oluşturma, birleştirme, durum ilerletme, karar uygulama |
| `radar/prices.py` | Tarihli ücret defteri (`crossings.json`) |
| `radar/calendar.py` | Bayram/yılbaşı izleme pencereleri |
| `radar/notify.py`, `radar/messages.py` | Bildirim planı, Telegram/e-posta gönderimi, mesaj metinleri |
| `radar/panel.py` | `panel.json` üretimi ve kısıtlı yerel önizleme sunucusu |
| `radar/bolgeler.py` | 81 il (plaka kodu) ve 7 coğrafi bölge |
| `radar/guvenlik.py` | Anahtar maskeleme, yalnızca http(s) bağlantı, gizli bilgi desenleri |
| `radar/yayin.py` | `python -m radar yayinla`: güvenlik taraması + GitHub'a yayın + depo sıkılaştırma |
| `radar/config.py` | `config/*.yaml` ve `.env` okuma, doğrulama |
| `radar/demo.py` | Panel için açıkça "örnek" etiketli veri |
| `radar/ucret_tablosu.py` | KGM tarife PDF'lerindeki gişe-gişe ücret matrisleri → `data/ucret-tablosu.json` (günde bir ve tarife değişince; bozuk PDF'te eski veri korunur). Gişe konumu/il/bölge `config/giseler.yaml`'dan, her turda yansıtılır |
| `config/giseler.yaml` | Otoyol gişe kaydı (bizim verimiz): otoyol kimliği → tarifedeki ad, konum (ya da `null`), il, not |
| `panel/` | Tek sayfalık panel (vanilla JS): `app.js`, `harita.js` (Leaflet), `hesap.js` (ücret hesabı), `vendor/leaflet/` (1.9.4, BSD), `vendor/fonts/` (OFL) |
| `.github/workflows/radar.yml` | 30 dakikalık çalışma + Pages yayını |
| `.github/workflows/testler.yml` | Her gönderimde testler (yalnız okuma yetkisi) |

---

## 5. Panel ve harita

- **Tasarım "Tabela dili" (Kasım 2026):** Türkiye otoyol tabelasının dili — koyu yeşil plaka (`--sign`
  `#0d5546`), beyaz iç çerçeve, iri ve dar rakamlar. Tabela yeşili yalnızca **toplam plakası**, geri sayım
  plakası ve otoyol kalkanında (O-4, O-7); arayüz vurgusu sedir (`--brand` `#14735f`, koyu `#178066`/`#6fd4b4`).
  Serbest geçiş her yerde **mor karo** (`--free`), geçemez kırmızı, zam amber, ücretsiz yeşil. Yazı tipleri:
  **Overpass** (rakam ve başlık) + **Inter** (arayüz); ikisi de `panel/vendor/fonts/` altında (OFL), CSP gereği
  kendi sunucudan. Tüm renk/ölçü değişkenleri `panel/style.css` başında (açık ve koyu). Tasarım kaynağı:
  "Otoyol Ücretleri — Tabela dili" tasarım dosyası (depoya girmez).
- **Yerleşim — masaüstü:** üst çubukta logo plakası, "Yeni tarife dönemi 1 Ocak · N gün" hapı ve durum. Harita
  tam ekran; üstte arama (`/` kısayolu), katman düğmeleri (koyu = açık) ve Filtreler (katmanlar, bölge, durum,
  il, otoyol); rota çizilince katman çipleri tek "Katmanlar" düğmesine iner. Sağ altta lejant ve yakınlaştırma;
  ilk açılışta kapatılabilir ipucu balonu. Varsayılan **açık tema**; üst çubuktaki (telefonda arama çubuğundaki)
  güneş/ay düğmesiyle koyu tema (`radar.tema`, `panel/theme.js` sayfa çizilmeden uygular). Solda içeriği kadar
  uzayan panel, bölümlü sekme (Rota / Köprüler / Duyurular).
- **Yerleşim — telefon (≤ 900 px):** harita tam ekran, hesap alt sayfada (tutamakla büyür), altta sekme
  çubuğu. Gişe seçimi tam ekran arama sayfası (bölge çipleri, son rotalar, otoyola göre gruplu liste). Rota
  çizilince haritada geri ve katmanlar düğmesi; alt sayfada "A → B" başlığı ve araç çipi.
- **Rota sekmesi:** boşken A/B alanları, 6'lı araç seçimi (bu cihazda hatırlanır), "Köprü ve tünel ekle" ve
  **Hızlı başla** (doğrulanmış örnekler) ya da **Son rotalar** (localStorage `radar.rotalar`). Sonuçta alanlar
  tek kutuda özetlenir; araç ve köprü/tünel çiplere iner; **Doğrudan / En ucuz** bölümlü seçici (aktarma
  sayısıyla); **toplam plakası** (fark: "152,50 ₺ daha ucuz · +1 aktarma · +1 serbest geçiş"); **güzergâh
  şeridi** (A, otoyol kalkanlı bölümler, mor serbest geçiş satırı, "Aktarma", B); eklenen geçişler; eylemler
  Ters yön / **Aylık** / Bağlantı / **Kart** (tarayıcıda PNG paylaşım kartı); Diğer sınıflar, Tarife belgeleri.
  Seçili sınıf eklenen bir geçişi kullanamıyorsa (Avrasya 3–5) engelleyici uyarı + kesik çizgili boş plaka.
- **Gidiş-dönüş ve aylık maliyet:** iki yön ayrı hesaplanır (ters yön tarifesiyle); Boğaz köprüleri dönüşte
  0 ₺; haftada 1–7 gün seçimi (`radar.gun`); aylık = haftalık × 52 ÷ 12; "Rotalarıma kaydet" yalnızca cihazda.
- **Köprüler sekmesi:** "Kaça geçerim?" + sınıf çipi; her geçiş en pahalıya göre ölçeklenmiş çubukla; açılınca
  sınıf tablosu (Avrasya: Gündüz · şu an / Gece, 3–5 "Geçemez"), Rotaya ekle / Haritada göster / Tarife.
- **Duyurular sekmesi:** yılbaşı geri sayım plakası, tarih kutucuklu takvim (bayramlar, karar durumu), resmî
  duyurular (yoksa boş durum), katlanır Son kayıtlar / Kaynaklar / KGM tarife belgeleri.
- **Harita yoğunluğu:** yakınlık ≤ 9 gişeler ızgara kümesi (sayılı hap); rota varken 10–11'de yalnızca rotadaki
  otoyolların gişeleri, diğerleri soluk; ≥ 12 hepsi. Rota: 6 px sedir + beyaz kenar; serbest geçişli bağlantı mor
  kesik; diğer seçenek soluk noktalı ve tıklanabilir etiketli ("Doğrudan · 415,00 ₺"). Giriş/çıkış A/B işaretli.
- **Ücret hesabı (`panel/hesap.js`):** giriş/çıkış gişesi (aranabilir liste; çıkış listesi her gişenin
  ücretini gösterir), 1–6. sınıf, sonuç "geçiş fişi"; güzergâh haritada çizilir (tablo sırası yol boyunca,
  kola sapan gişeler çizgiden atlanır). Haritadaki gişenin açılır penceresinden Giriş/Çıkış seçilebilir.
  Seçim adres çubuğunda: `#hesap=<otoyol-id>/<giriş>/<çıkış>/<sınıf>`. Yöne bağlı tarifelerde
  `ucret_geri` kullanılır.
- **Köprü ve tünel ekle:** KGM gişe tablolarına dahil olmayan geçişler (Avrasya Tüneli, 15 Temmuz, FSM)
  hesaplayıcıda işaretlenip toplama eklenir; gişe seçmeden yalnızca bunlar da hesaplanabilir. Tabloya dahil
  olanlar (`dahil_gecisler`: YSS, Osmangazi, 1915) listelenmez, iki kez sayılmaz. Avrasya'da 3–5. sınıf
  "Geçemez", gece tarifesi alt satırda; Boğaz köprülerinde "yalnızca Avrupa → Asya yönünde ücretli" notu.
  Adres: `#hesap=<A>/<i>/<B>/<j>/<sınıf>/<geçiş-id,…>` (gişesiz: `#hesap=////1/avrasya-tuneli`).
- **Resmî bağlantılar:** Rota sekmesinin altında KGM ücret sorgulama (vatandas.kgm.gov.tr/Toll) ve İhlalli
  geçiş sorgulama/ödeme. İhlal sorgusu plaka ister (kişisel veri) — yalnızca bağlantı verilir, radar okumaz.
- **Doğrulama (11.11.2026):** PDF'ten okunan tablolar KGM'nin resmî ücret sorgulamasıyla elle karşılaştırıldı:
  Adapazarı→Akyazı 1. sınıf 40 TL / 15,8 km; Kurtköy→Gerede 5. sınıf 744 TL / 273,58 km — birebir aynı.
  Resmî sorgulama yalnızca 7 KGM otoyolunu kapsar; PDF'ler 17 tabloyu (köprülü otoyollar dahil) kapsadığı
  için kaynak olarak PDF'ler kullanılır. `ucretlerana.aspx` yalnızca bağlantı sayfasıdır, veri `UcretlerYeni.aspx`'tedir.
- **Haritadaki gişeler yalnızca KGM tarifesinden, konumları yalnızca bizim kaydımızdan gelir.** Sahibin
  isteği: "bize haritadan veri gelmemeli, bizde gişeler verisi zaten olmalı, biz haritaya çizmeliyiz".
  OpenStreetMap'te kapanmış/tarifede olmayan gişeler var (ör. Derince, İzmit merkezdeki adsız nokta, eski
  D-100 gişeleri) — bilgi kirliliği. Bu yüzden Overpass adımı, `radar/harita.py`, `harita-guncelle` komutu
  ve `data/harita.json` kaldırıldı. Konumlar `config/giseler.yaml`'da (sürüm kontrollü); radar bunları
  `data/ucret-tablosu.json` istasyonlarına `lat`, `lon`, `il`, `bolge` olarak yazar. Panel gişeleri yalnızca
  bu dosyadan çizer; harita karoları yalnızca arka plandır.
- **Kayıt Kasım 2026'da bir kez hazırlandı:** eski OSM eşleşmeleri ve eksik gişeler tarifedeki sıra ve
  km'lerle tek tek denetlendi (kuş uçuşu uzaklık yol km'sini aşmamalı). Düzeltilenler: Düzce (Gölyaka)
  (Düzce gişesine bağlanmıştı), KMO Çatalca (Avrupa Otoyolu'nun Çatalca gişesine bağlanmıştı), Aydın Alın
  (İzmir–Aydın'ın Aydın gişesine bağlanmıştı). 201 gişeden 198'i konumlu; Liman, Küçükılıçlı ve Ağaçlı
  `konum: null`. Kayıtta olmayan bir gişe tarifeye girerse tabloda konumsuz kalır, `state.json`'a
  (`_ucret_tablosu.kayitsiz`) yazılır ve teknik gruba her gişe için bir kez "GİŞE KAYDI EKSİK" gider.
  Testler kaydın biçimini, tarifedeki her gişenin kayıtta olduğunu ve km tutarlılığını denetler.
- Köprü/tünel işaretleri `config/crossings.yaml` içindeki yaklaşık `konum` alanından. Çakışmasız isim
  etiketleri, İstanbul köprülerinin uzaklaşınca kümelenmesi, eski adlarla arama, tablo↔harita bağlantısı.

---

## 6. Güvenlik (yapılan denetim ve önlemler)

Araçlar: `detect-secrets`, `bandit`, `pip-audit` (temiz) ve elle inceleme. Düzeltilen sorunlar:

1. E-postada TLS sertifikası doğrulanmıyordu → `ssl.create_default_context()` ile doğrulanıyor.
2. Yerel panel sunucusu tüm klasörü (`.env` dahil) sunuyordu → yalnızca `panel/`, `data/panel.json`,
   `data/ucret-tablosu.json`; yalnızca localhost Host başlığı; klasör listesi kapalı.
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

- Kod tamam; **63 test** var (internete çıkmadan, sahte sitelerle; yayın betiği sahte `gh` ve yerel
  git deposuyla uçtan uca test edildi). Yayın testlerinden 4'ü yalnızca Linux/macOS'ta çalışır.
- **GitHub'da yayında.** Depo adı `otoyol-ucretleri` (herkese açık); panel GitHub Pages'te
  `https://<kullanıcı-adı>.github.io/otoyol-ucretleri/` adresinde. Radar 30 dakikada bir Actions'ta çalışıyor;
  Telegram bildirimi doğrulandı (`python -m radar test-bildirim`). Yerelde Python 3.12 `.venv` içinde kurulu.
- **İlk gerçek turda bulunan ve düzeltilen sorunlar:**
  - (Geçmiş) OpenStreetMap/Overpass gişe adımı sorun çıkarıyordu ve bilgi kirliliği getiriyordu; Kasım
    2026'da tamamen kaldırıldı, yerine `config/giseler.yaml` kaydı geldi.
  - KGM tarife sayfasındaki tarife dışı PDF'ler (strateji planı vb.) belge olarak izleniyordu; artık
    yalnızca adında/adresinde "ücret" ya da "tarife" geçen PDF'ler izleniyor.
- Telegram bot anahtarı bir sohbet kaydında açıkça geçti; sahibi şimdilik yenilememeyi seçti. Yenilenirse:
  BotFather'da `/revoke`, yeni anahtarı `.env`'ye yaz, `python -m radar yayinla --yalnizca-ayarlar`.
- Dışarıdan erişim kısıtı (yabancıların issue/yorum/PR açamaması) altı ay sürer; aynı komutla yenilenir.

---

## 8. Bilinen sınırlar

- Avrasya Tüneli ücretleri artık sitenin JSON adresinden okunuyor; sitede yürürlük tarihi yok (görüldüğü an esas).
- Tarifeler arası hesap `config/giseler.yaml` → `baglantilar` (15 doğrulanmış bağlantı, tek yönlüler ve aradaki
  serbest geçişler dahil) ile yapılır; toplam, bölümlerin ayrı tarifelerinin toplamıdır. İki yol varsa panel
  "Doğrudan" (en az kalem) ve "En ucuz" seçeneklerini gösterir; aynı otoyoldan çıkıp yeniden girme yol sayılmaz.
- Serbest geçiş (SGS) noktalarının konumları da kayıtta (`serbest_gecis`); 41 satır, 23 nokta.
- Otoyol gişe-gişe matrisleri hesap için okunuyor (16 PDF, 17 tablo, 201 gişe); otoyol zam bildirimi hâlâ "belge değişti" düzeyinde.
- 3 gişenin (Liman, Küçükılıçlı, Ağaçlı) konumu belirlenemedi; haritada görünmezler. Bazı gişeler (ör. Kartepe,
  Topağaç, Muallimköy, SGS noktaları) gişe binası yerine kavşak konumuyla kayıtlı (`not` alanında yazar).
- Tablodaki bazı değerler şaşırtıcı ama belgede öyle: ör. Adapazarı→Topağaç 1. sınıf 250 TL (Topağaç, KMO bağlantısı).
- TollGuru yeniden soruldu (Kasım 2026); yine reddedildi: ücretli, Türkiye/TL zayıf, zam ve bayram bilgisi yok. KGM tabloları daha doğru.
- YSS, Osmangazi ve 1915 Çanakkale PDF biçimleri doğrulanmadı.
- Bayram tarihleri yaklaşık; köprü konumları yaklaşık.
- OSM karo sunucusu (yalnızca harita altlığı) küçük ekip kullanımı için uygun.
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
