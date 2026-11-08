# Tarife Radarı · köprü ve otoyol geçiş ücretleri

Köprü, tünel ve otoyol geçiş ücretleri değişmeden ya da bayramlarda geçişler ücretsiz olmadan **önce**
haber verir. Amaç bilgi sahibi olmak: onay adımı yoktur, radar bulduğunu doğrudan bildirir ve panele yazar.

Tamamen ücretsiz kaynaklarla çalışır: GitHub Actions (zamanlayıcı), Git deposu (veritabanı),
GitHub Pages (panel), Telegram ve e-posta (bildirim). Yapay zekâ ya da ücretli API kullanılmaz.

## Ne yapar

- **KGM tarife PDF'leri:** Karayolları Genel Müdürlüğü'nün tarife sayfasındaki PDF'leri izler. Yeni ya da
  değişmiş bir PDF görünce indirir; 1–6. sınıf ücretleri ve "… tarihinden itibaren geçerlidir" satırındaki
  yürürlük tarihini okur. 15 Temmuz, FSM, YSS, Osmangazi ve 1915 Çanakkale için ücretler tabloya yazılır
  (okunabildiği sürece; aşağıdaki "Bilinen sınırlar"a bakın); otoyol PDF'leri için "belge değişti" bilgisi verilir.
- **Duyuru ve haberler:** KGM duyuruları, Ulaştırma ve Altyapı Bakanlığı haber/duyuru/basın açıklamaları ve
  Avrasya Tüneli duyuruları. Ücret değişikliği ve ücretsiz geçiş haberlerini ayıklar, hangi geçişleri
  kapsadığını ve hangilerinin **hariç** tutulduğunu (ör. yap-işlet-devret köprüleri) çıkarır.
- **Bayram ve yılbaşı takvimi:** Bilinen dönemlerden 14–21 gün önce "izleme başladı" kaydı açar; karar
  gelince aynı kayıt karara dönüşür.
- **Hatırlatmalar:** Karar çıktığında, yürürlükten 7 ve 1 gün önce, yürürlük günü ve ücretsiz geçiş
  bittiğinde bildirim gönderir.
- **Ücret hesabı:** Giriş ve çıkış gişesi ile araç sınıfı seçilir; KGM tarifesindeki ücret ve mesafe bir
  "geçiş fişi" olarak gösterilir, güzergâh haritada çizilir. Gişe haritadan da seçilebilir; hesap adres
  çubuğunda tutulduğu için bağlantıyla paylaşılabilir. Veri: KGM tarife PDF'lerindeki gişe-gişe tablolar
  (`data/ucret-tablosu.json`; 17 otoyol tablosu, yöne göre değişen tarifeler dahil).
- **Harita:** Sayfanın merkezindedir. Köprü, tünel ve **yalnızca KGM tarifesinde bulunan** otoyol gişeleri
  gösterilir. Gişe konumları bizim tuttuğumuz `config/giseler.yaml` kaydından gelir; radar dışarıdan
  gişe verisi almaz, harita karoları yalnızca arka plandır. Arama, il/otoyol/durum filtreleri ve 7 bölge vardır.
- **Panel:** Köprü ve tünel ücretleri (sınıf seçerek), bayramda ücretsiz geçişler, kayıtlar; kaynakların
  durumu ve KGM belgeleri en altta. Hepsi ücretsizdir, API anahtarı gerekmez.

## Nasıl çalışır

Radar her 30 dakikada bir kaynakları okur, öncekiyle karşılaştırır ve değişiklik varsa bir **kayıt** açar.
Kayıtlar şu durumlardan geçer:

| Durum | Anlamı |
| --- | --- |
| Sinyal | Tek bir haberde geçti, teyit bekleniyor. |
| Gündemde | Yaklaşan bayram/yılbaşı dönemi ya da belirsiz bir değişiklik; izleniyor. |
| Karar çıktı | Resmî kaynak (KGM, Bakanlık, işletmeci) açıkladı ya da aynı tarihi veren iki bağımsız haber var. |
| Yürürlükte | Yürürlük tarihi geldi. |
| Kapandı | 14 gün içinde teyit gelmedi. |
| İptal / ertelendi | Açıklanan karar geri çekildi. |

Karar çıkınca ücretler `data/crossings.json` dosyasına tarihli olarak eklenir (eski kayıt silinmez,
bitiş tarihi doldurulur) ve süreli ücretsiz geçişler `data/rules/` altına "ücret 0" kuralı olarak yazılır.
Taksimetre sistemi ileride bu iki dosyayı doğrudan okuyabilir.

**İlk çalıştırma** sessizdir: kaynakların o anki hâli başlangıç olarak kaydedilir, yalnızca "KURULUM"
mesajı gider. Sonraki çalışmalarda yalnızca değişiklikler bildirilir.

## Klasörler

| Yol | İçerik |
| --- | --- |
| `radar/` | Programın kendisi (Python) |
| `config/sources.yaml` | İzlenen kaynaklar |
| `config/crossings.yaml` | Geçişler, diğer adları ve KGM PDF eşleşmeleri |
| `config/calendar.yaml` | Bayram ve yılbaşı dönemleri |
| `config/giseler.yaml` | Otoyol gişelerinin konumu ve ili (bizim kaydımız; haritadaki gişeler yalnızca buradan çizilir) |
| `config/settings.yaml` | Genel ayarlar (hatırlatma günleri, özet saati vb.) |
| `panel/` | Web paneli (tek sayfa). Harita için Leaflet `panel/vendor/leaflet/` içinde gelir (BSD lisanslı) |
| `data/` | Radarın kayıtları; radar yazar, elle düzenlenmez ([ayrıntı](data/README.md)) |
| `.github/workflows/` | GitHub Actions: 30 dakikalık çalışma ve testler |
| `tests/` | Otomatik testler ve örnek PDF'ler |
| `.env.example` | Telegram ve e-posta ayarlarının şablonu |

## Hızlı başlangıç (Windows)

Komutları proje klasöründe (`otoyol`) bir terminal açıp çalıştırın.

1. **Python 3.12 kurun** (yüklü değilse):

   ```
   winget install Python.Python.3.12
   ```

   ya da python.org'dan indirip kurulumda "Add python.exe to PATH" kutusunu işaretleyin.

2. **Sanal ortam ve bağımlılıklar:**

   ```
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

   PowerShell "running scripts is disabled" derse bir kez şunu çalıştırın:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

3. **Paneli örnek veriyle görün:**

   ```
   python -m radar panel --ornek
   ```

   Tarayıcıda `http://localhost:8000/panel/?ornek=1` açılır. Değerler örnektir. Durdurmak için `Ctrl+C`.

4. **Kaynakları deneyin:**

   ```
   python -m radar kaynak-testi
   ```

   Her kaynağın okunup okunmadığını ve PDF'lerden okunan ücretleri gösterir. 15 Temmuz ve FSM için
   2026 tarifesinde `geçerlilik: 1 Ocak 2026 00:00 · 1. sınıf 59.00, …` satırı görünmelidir.

5. **Bildirim ayarları:** `.env` dosyasını oluşturup Telegram ve e-posta bilgilerini girin
   (aşağıdaki Telegram ve E-posta bölümlerine bakın), sonra deneme mesajı gönderin:

   ```
   copy .env.example .env
   notepad .env
   python -m radar test-bildirim
   ```

6. **İlk tur:**

   ```
   python -m radar calistir
   python -m radar panel
   ```

   İlk tur başlangıç kaydını alır ve "KURULUM" mesajı gönderir. `python -m radar durum` özeti yazdırır.

Sanal ortamı etkinleştirmeden de çalıştırabilirsiniz: `.venv\Scripts\python -m radar calistir`

## Telegram kurulumu

1. Telegram'da **@BotFather**'a `/newbot` yazın, bota ad verin. Verdiği anahtar `TELEGRAM_BOT_TOKEN` olur.
2. Bildirimlerin gideceği bir grup açın ve botu gruba ekleyin. Grupta `/start@<botun_kullanıcı_adı>` yazın.
3. Tarayıcıda `https://api.telegram.org/bot<ANAHTAR>/getUpdates` adresini açın.
   `"chat":{"id":-100…` değeri `TELEGRAM_CHAT_ID` olur (grup kimlikleri eksiyle başlar).
4. Kaynak hataları için ayrı bir teknik grup isterseniz aynı yolla `TELEGRAM_TECH_CHAT_ID` alın.
   Boş bırakırsanız bu uyarılar da ana gruba gider.

Telegram Bot API ücretsizdir. WhatsApp Business API mesaj başına ücretli olduğu için kullanılmıyor.

## E-posta kurulumu

- **Şirket e-postası:** BT ekibinizden SMTP sunucusu, port ve kullanıcı bilgisini alın.
- **Gmail:** Hesapta iki adımlı doğrulama açık olmalı. Google Hesabı → Güvenlik → **Uygulama şifreleri**
  bölümünden 16 haneli bir şifre oluşturun.

  ```
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_SSL=false
  SMTP_USER=adres@gmail.com
  SMTP_PASSWORD=<16 haneli uygulama şifresi>
  SMTP_FROM=adres@gmail.com
  EMAIL_TO=ekip1@sirket.com,ekip2@sirket.com
  ```

`.env` dosyası Git'e gönderilmez (`.gitignore`). Şifreleri hiçbir zaman depoya yazmayın.

## GitHub'da yayınlama (ücretsiz)

Radar herkese açık bir GitHub deposunda çalışır: GitHub Actions 30 dakikada bir çalıştırır, panel GitHub
Pages'te yayınlanır. Depoda yalnızca kod ve kamuya açık ücret bilgileri durur; anahtarlar ve şifreler
GitHub Secrets'ta şifreli saklanır.

Yayını tek komut yapar: `python -m radar yayinla`. Komut sizin bilgisayarınızda, sizin GitHub girişinizle
çalışır. Anahtarlar `.env`'den okunup doğrudan GitHub Secrets'a yazılır; ekrana, depoya ya da komut
satırına hiçbir zaman yazılmaz.

1. **Git ve GitHub CLI'ı kurun** (bir kez), sonra yeni bir terminal açın:

   ```
   winget install --id Git.Git -e
   winget install --id GitHub.cli -e
   ```

2. **GitHub'a giriş yapın.** Tarayıcıda açılan sayfada onaylarsınız; şifre terminale yazılmaz:

   ```
   gh auth login --hostname github.com --git-protocol https --web --scopes workflow
   ```

3. **İş akışı dosyalarını yerleştirin.** Sohbete eklenen `radar.yml` ve `testler.yml` "Claude outputs"
   klasöründedir:

   ```
   mkdir .github\workflows
   copy "Claude outputs\radar.yml" .github\workflows\
   copy "Claude outputs\testler.yml" .github\workflows\
   ```

4. **`.env` dosyasını doldurun** (Telegram ve isterseniz e-posta; aşağıdaki bölümlere bakın).

5. **Önce deneyin, sonra yayınlayın:**

   ```
   python -m radar yayinla --deneme
   python -m radar yayinla
   ```

Komutun yaptıkları:

- **Yayın öncesi güvenlik taraması:** Depoya girecek her dosyada `.env`'deki anahtar, sohbet kimliği,
  şifre ve e-posta değerleri, bilinen anahtar biçimleri (Telegram, GitHub, özel anahtar…), kişisel klasör
  yolunuz ve kişisel e-postanız aranır. Tek bulgu varsa hiçbir şey gönderilmez ve hangi satır olduğu
  (değerin kendisi değil) gösterilir.
- **Gizli kimlik:** Commit kişisel e-postanızla değil, GitHub'ın `noreply` adresiyle yapılır.
- **Depo ve anahtarlar:** Herkese açık depo oluşturulur, dosyalar gönderilir, `.env`'deki değerler
  GitHub Secrets'a yazılır, `PANEL_URL` tanımlanır ve GitHub Pages açılır.
- **Sıkılaştırma:** Ayrıntısı aşağıdaki Güvenlik bölümünde.
- **İlk tur:** Radar hemen bir kez çalıştırılır; Telegram'a "KURULUM" mesajı gelir, panel birkaç dakika
  içinde `https://<kullanıcı-adınız>.github.io/otoyol-ucretleri/` adresinde açılır.

`.env`'yi değiştirdiğinizde (ör. yeni Telegram anahtarı) GitHub'daki anahtarları
`python -m radar yayinla --yalnizca-ayarlar` ile güncelleyin. Kod değişikliklerini de yine
`python -m radar yayinla` gönderir (her seferinde önce tarama yapılır).

Bundan sonra radar 30 dakikada bir kendiliğinden çalışır ve her değişikliği `data/` klasörüne commit olarak
kaydeder; geçmişin tamamı Git'te durur. Değişiklik yokken de en fazla 3 saatte bir panel kaydı yazılır.
Bu kayıtlar deponun "etkin" kalmasını sağlar (GitHub 60 gün hareketsiz kalan depolarda zamanlayıcıyı durdurur).
Bildirim kanalı (Telegram ya da e-posta) tanımlanmadıysa radar çalışmaz ve Actions'ta uyarı verir; böylece
hiçbir bildirim "gönderildi" sayılıp kaybolmaz.

### Özel (private) depo

`python -m radar yayinla --gizli` gizli depo oluşturur. Bu durumda:

- Actions ayda 2.000 dakika ücretsizdir. 30 dakikalık çalışma ayda yaklaşık 1.450 dakika tutar; rahat etmek
  için `.github/workflows/radar.yml` içinde zamanlamayı saatlik yapın: `cron: "0 * * * *"`.
- GitHub Pages özel depolarda ücretsiz değildir. `radar.yml` içindeki `panel` işini silin ve paneli
  Cloudflare Pages (ücretsiz) + Cloudflare Access (50 kullanıcıya kadar ücretsiz giriş koruması) ile ya da
  kendi sunucunuzda yayınlayın. Panel için gereken dosyalar: `panel/` klasörünün tamamı ve yanında
  `data/panel.json` ve `data/ucret-tablosu.json`.

### Kendi bilgisayarınız ya da sunucunuz

Kamu siteleri yurt dışı IP'lerini zaman zaman engelleyebilir. `kaynak-testi` yerelde çalıştığı hâlde
GitHub'da "KAYNAK HATASI" uyarıları gelirse radarı Türkiye'deki bir makinede çalıştırın. Ayarlar `.env`
dosyasından okunur.

- **Windows (Görev Zamanlayıcı):**

  ```
  schtasks /create /sc minute /mo 30 /tn "Tarife Radari" /tr "cmd /c cd /d %USERPROFILE%\Desktop\otoyol && .venv\Scripts\python.exe -m radar calistir >> radar.log 2>&1"
  ```

- **Linux (cron):**

  ```
  */30 * * * * cd /opt/otoyol && .venv/bin/python -m radar calistir >> radar.log 2>&1
  ```

Panel için `python -m radar panel` ya da klasörü herhangi bir web sunucusuyla yayınlamak yeterlidir.

## Güvenlik

Proje herkese açık bir depoda güvenle çalışacak şekilde hazırlandı (son denetim: Kasım 2026; `bandit`,
`detect-secrets` ve `pip-audit` ile tarandı, bilinen açık yok).

**Herkese açık depoda görünenler:** kod, ayar dosyaları (izlenen siteler, geçişler), `data/` kayıtları
(kamuya açık ücret bilgileri) ve Actions günlükleri. **Görünmeyenler:** Telegram anahtarı ve sohbet
kimlikleri, e-posta adresleri ve şifreler. Bunlar yalnızca bilgisayarınızdaki `.env` dosyasında (`.gitignore`
ile depo dışında) ve GitHub Secrets'ta şifreli durur. GitHub, Actions günlüklerinde bu değerleri `***` ile
gizler; radar ayrıca hata mesajlarındaki anahtarları kendisi de maskeler.

**Telegram'dan size kimse ulaşamaz:**

- Radar Telegram'a yalnızca mesaj gönderir, gelen mesajları hiç okumaz. Bota yazan biri hiçbir şeyi
  tetikleyemez; o mesajlar size iletilmez. Bot yalnızca Secrets'taki sohbet kimliklerine yazar.
- Botun kullanıcı adı ve sohbet kimliği depoda ve panelde yer almaz; hiçbir yerde paylaşmayın.
- **BotFather ayarları** (botu kendi grubunuza ekledikten sonra):
  - `/setjoingroups` → botunuz → **Disable**: bot artık başka hiçbir gruba eklenemez.
  - `/setprivacy` → **Enable** (varsayılan): bot gruptaki sıradan mesajları görmez.
- **Bildirim grubu:** Özel grup olsun; herkese açık bağlantı ya da kullanıcı adı vermeyin, davet
  bağlantılarını iptal edin, üye eklemeyi yalnızca yöneticilere bırakın.
- **Kişisel hesabınız:** Telegram'da Ayarlar → Gizlilik ve Güvenlik bölümünde telefon numaranızı
  "Kimse" yapın ve sizi gruplara ekleyebilecek kişileri "Kişilerim" ile sınırlayın.

**Anahtar sızarsa:** BotFather'da `/revoke` ile yeni anahtar alın (eskisi anında geçersiz olur), `.env`'yi
güncelleyip `python -m radar yayinla --yalnizca-ayarlar` çalıştırın. E-posta için uygulama şifresini silip
yenisini oluşturun.

**Depo ayarları** (`python -m radar yayinla` uygular):

- Issue, wiki, proje ve tartışma bölümleri kapalı; yabancıların yorum ve PR açması 6 ay kapalı (süre
  dolunca `--yalnizca-ayarlar` ile yenileyin).
- Actions yalnızca GitHub'ın kendi eylemlerini çalıştırır; varsayılan yetki yalnızca okuma, her iş yalnızca
  ihtiyacı olan yetkiyi alır. Testler hiçbir gizli bilgiye erişmez.
- GitHub'ın gizli bilgi taraması ve gönderim koruması açık: GitHub'ın tanıdığı türde bir anahtar
  gönderilmeye kalkılırsa gönderim durdurulur (Telegram anahtarlarını radarın kendi yayın taraması yakalar).
- Ana dal silinemez ve geçmişi değiştirilemez; bağımlılık güvenlik uyarıları açık.

**Panel ve yerel sunucu:** Panel, içerik güvenlik politikası (CSP) ile yalnızca kendi dosyalarını ve
OpenStreetMap harita karolarını yükler. Kaynak sitelerden gelen bağlantılar yalnızca `http(s)` ise
tıklanabilir. `python -m radar panel` yalnızca bu bilgisayardan erişilebilir ve yalnızca panel dosyalarını
verir; `.env` ve diğer kayıtlar sunulmaz.

**E-posta:** Sunucu sertifikası her zaman doğrulanır; şifreli bağlantı kurulamazsa gönderim yapılmaz.

**Bağımlılıklar:** Sürümler `requirements.txt` içinde sabittir; yalnızca test edilmiş sürümler kurulur.

**GitHub hesabınız için öneriler:** İki adımlı doğrulamayı açın. Settings → Emails bölümünde
"Keep my email addresses private" ve "Block command line pushes that expose my email" seçeneklerini
işaretleyin.

## Bildirimler

| Ne zaman | Kanal | Başlık |
| --- | --- | --- |
| Karar çıktığında | Telegram + e-posta | `[KARAR ÇIKTI]` |
| Karar yürürlükten sonra fark edildiyse | Telegram + e-posta | `[ACİL · KAÇIRILDI]` |
| Yürürlükten 7 ve 1 gün önce | Telegram + e-posta | `[HATIRLATMA]` |
| Yürürlük günü | Telegram + e-posta | `[BUGÜN YÜRÜRLÜKTE]` |
| Ücretsiz geçiş bittiğinde | Telegram + e-posta | `[SONA ERDİ]` |
| Açıklanan tarih değiştiğinde | Telegram + e-posta | `[TARİH DEĞİŞTİ]` |
| Karar geri çekildiğinde | Telegram + e-posta | `[İPTAL / ERTELENDİ]` |
| Bayram/yılbaşı izleme penceresi açıldığında | Telegram | `[İZLEME BAŞLADI]` |
| Bir kaynak 24 saatten uzun okunamadığında | Teknik grup | `[KAYNAK HATASI]` |
| Her sabah 08:00'den sonra (anlatacak bir şey varsa) | E-posta | Günlük özet |
| Pazartesi | E-posta | Haftalık özet |

Aynı bildirim iki kez gönderilmez (`data/notifications.json`). Gönderilemeyen bildirim bir sonraki turda
yeniden denenir. Okunan bilgide belirsizlik varsa mesaja ve panele etiket eklenir (ör. "Kapsamı kontrol et":
duyuru "köprü ve otoyollar" gibi genel bir ifade kullanmış; "Saatleri kontrol et": saat yazmıyor,
bayram günleri varsayıldı; "Olağan dışı değişim": düşüş ya da %100'ün üzerinde artış).

## Ayarlar

- **Bayram tarihleri:** `config/calendar.yaml` içindeki 2027 bayram tarihleri yaklaşıktır. Diyanet'in dini
  günler takviminden doğrulayın ve her yıl yeni yılın dönemlerini ekleyin.
- **Yeni geçiş:** `config/crossings.yaml` dosyasına `id`, `name`, `aliases` ekleyin. KGM listesinde PDF'i
  varsa `tariff_match` alanına dosya adındaki ifadeyi yazın (ör. `YSSKoprusu`).
- **Yeni kaynak:** `config/sources.yaml`. Haber akışları (Google News RSS) kapalı gelir; kullanım koşullarını
  kontrol ettikten sonra `enabled: true` yapabilirsiniz. Haberler tek başına karar sayılmaz, aynı tarihi
  veren iki bağımsız haber gerekir.
- **Hatırlatma günleri, özet saati, uyarı eşikleri:** `config/settings.yaml`.
- **Harita:** Köprü ve tünel konumları `config/crossings.yaml` içindeki `konum` ve `il` alanlarındadır
  (yaklaşık; gerekirse düzeltin). Otoyol gişeleri `config/giseler.yaml` kaydındadır: otoyol kimliği altında,
  tarifedeki adıyla `ad`, `konum: [enlem, boylam]` (bilinmiyorsa `null`), `il` ve isteğe bağlı `not`.
  Değişiklik bir sonraki radar turunda `data/ucret-tablosu.json`'a yansır. Tarifeye kayıtta olmayan bir
  gişe girerse teknik gruba bir kez "GİŞE KAYDI EKSİK" uyarısı gelir; gişe hesapta seçilebilir ama
  kayda eklenene kadar haritada görünmez.

## Komutlar

| Komut | Ne yapar |
| --- | --- |
| `python -m radar calistir` | Bir radar turu. `--bildirim-yok`: göndermeden; `--deneme`: hiçbir şey yazmadan ve göndermeden; `--zaman 2026-12-31T23:00`: zamanı taklit eder |
| `python -m radar kaynak-testi` | Kaynakları dener. `--kaynak kgm-tarifeler`: tek kaynak; `--hepsi`: kapalılar dahil; `--hizli`: PDF indirmeden |
| `python -m radar test-bildirim` | Telegram ve e-postaya deneme mesajı |
| `python -m radar panel` | Paneli yerelde açar. `--ornek`: örnek veri; `--port 8080` |
| `python -m radar ucret-tablosu` | KGM tarife PDF'lerindeki gişe-gişe ücret tablolarını hemen okur, konumları gişe kaydından ekler; otoyol, gişe ve konum sayılarını ve kayıtta olmayan gişeleri yazdırır |
| `python -m radar durum` | Güncel ücretler, açık kayıtlar ve kaynak durumu |
| `python -m radar yayinla` | Güvenlik taramasından geçirip GitHub'da yayınlar. `--deneme`: yalnızca tarama; `--yalnizca-ayarlar`: anahtarları ve güvenlik ayarlarını yeniler; `--gizli`: gizli depo; `--depo ad`: depo adı |

Ayrıntılı günlük için komuttan önce `--ayrinti` ekleyin: `python -m radar --ayrinti calistir`

## Testler

```
pip install -r requirements-dev.txt
python -m pytest
```

Testler internete çıkmaz; sahte sayfalar ve `tests/fixtures/` altındaki PDF'lerle tam bir yılı canlandırır
(yılbaşı zammı, hatırlatmalar, bayram ücretsiz geçişi, kaynak hatası, iki haber kuralı).
GitHub'a her gönderimde de otomatik çalışır.

## Bilinen sınırlar

- **Avrasya Tüneli** ücretleri sayfaya JavaScript ile yüklendiği için okunamıyor; değişiklikler tünelin
  duyurularından yakalanır, ücretleri panelde elle doğrulamak gerekebilir.
- **Otoyol gişe tabloları** ücret hesabı için okunur, ancak otoyol ücret değişikliği bildirimi yine
  "belge değişti" düzeyindedir. Tablolardaki tuhaflıklar (ör. sütunu olmayan gişe) `uyarilar` alanına yazılır.
- Gerçek dosyada doğrulanan PDF biçimi **15 Temmuz ve FSM** tarifesidir. YSS, Osmangazi ve 1915 Çanakkale
  PDF'lerinin okunup okunmadığını `kaynak-testi` gösterir; okunamazsa değişiklik yine bildirilir ama kayıt
  "Değerler okunamadı" etiketi alır ve ücretler tabloya yazılmaz.
- KGM PDF'lerindeki ikinci ücret sütununun anlamı belirsiz; yalnızca ilk sütun (KDV dahil geçiş ücreti) alınır.
- Sitelerin tasarımı değişirse okuma bozulabilir. Bu durumda teknik gruba "KAYNAK HATASI" gelir;
  `python -m radar kaynak-testi` sorunu gösterir.
- Bayram tarihleri yaklaşık girilmiştir (yukarıdaki Ayarlar bölümüne bakın).
- **Haritadaki gişeler** KGM tarifesinden, konumları `config/giseler.yaml` kaydından gelir. Kayıt Kasım
  2026'da tarifedeki sıra ve km'lerle tek tek denetlenerek hazırlandı (201 gişeden 198'i konumlu). Konumu
  belirlenemeyen 3 gişe (Liman, Küçükılıçlı, Ağaçlı) haritada görünmez ama hesapta seçilebilir; yanlış yere
  işaret koymaktansa hiç konmaz.
- **Harita altlığı** OpenStreetMap'in ücretsiz karo sunucusundan gelir. Birkaç kişilik bir ekip paneli için
  uygundur; paneli çok sayıda kullanıcıya açarsanız OpenStreetMap'in kullanım koşulları gereği başka bir
  karo sağlayıcısına geçmek gerekir.

## Sonraki faz

Şehir taksi tarifeleri (ör. Kocaeli açılış/km ücreti) bu yapının üzerine eklenecek: belediye ve UKOME
karar sayfaları yeni kaynak olarak tanımlanacak, ücretler aynı tarihli kayıt yapısında tutulacak.
