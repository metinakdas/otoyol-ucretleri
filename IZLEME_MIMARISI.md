# İzleme Mimarisi

Tarife Radarı'nın sağlığını dışarıdan izleyen yapı: loglar merkezde toplanır,
durum tek ekrandan okunur, sorun olduğunda alarm gelir. Bu belge mimarinin
tamamını, her gereksinimin nasıl karşılandığını ve bilinçli olarak
karşılanmayanları anlatır.

## Neden bu mimari?

Radar bir sunucuda **çalışmaz**. GitHub Actions üzerinde 30 dakikada bir
başlar, 1-2 dakika çalışır ve kapanır. Bu yüzden:

- Graylog, Uptime Kuma, kendi kurulan Grafana+Loki, SigNoz gibi araçlar
  **uygun değildir**: hepsi 7/24 açık bir sunucu (ya da Docker ana makinesi)
  ister; projede sunucu yok ve olmaması bir tasarım kararıdır (bakım yükü ve
  maliyet sıfır).
- "Adrese ping at" türü uptime kontrolü **anlamsızdır**: radarın sürekli açık
  bir servisi yok. Doğru soru "servis ayakta mı?" değil, **"son X dakikada
  bir tur çalıştı mı?"** sorusudur.
- İzleyen sistem, izlenen sistemin **dışında** olmalıdır. GitHub'ın kendisi
  durursa alarmı yine de birinin vermesi gerekir. Bu yüzden izleme tarafı
  Grafana Cloud'dadır (ücretsiz plan, bizim adımıza 7/24 çalışır).
- GitHub'ın kendi zamanlaması (`*/30`) **güvenilir değildir**: yoğunlukta
  seyreltilir. 9-15 Kasım 2026 kayıtlarında günde 48 yerine yalnızca 3-4
  zamanlanmış tur çalıştı (aralar 4-7,5 saat). Bu yüzden tur, dışarıdan
  **Cloudflare Workers** zamanlayıcısıyla 30 dakikada bir `workflow_dispatch`
  ile başlatılır (`tetikleyici/`, kurulum: `tetikleyici/KURULUM.md`). GitHub
  cron'u yedek olarak kalır.

## Genel görünüm

```
┌──────────────── Cloudflare Workers (ücretsiz) ───────────────────────┐
│  tetikleyici/worker.js · :05 ve :35 (UTC) · herkese açık adresi yok  │
│  GitHub API → workflow_dispatch (tetik=zamanlayici)                  │
│  anahtar: yalnızca bu depo, yalnızca Actions: Read and write         │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌─────────────────────────── GitHub Actions ───────────────────────────┐
│  radar.yml · dış zamanlayıcı + yedek cron · timeout 20 dk            │
│                                                                      │
│  python -m radar calistir                                            │
│   ├─ kaynak kontrolleri   KGM / UAB / Avrasya … (health.json)        │
│   ├─ fiyat taraması       tarife belgeleri, gişe tabloları           │
│   ├─ karar/olay akışı     sinyal → karar → yürürlük → sona erdi      │
│   ├─ bildirimler          Telegram · WhatsApp · E-posta              │
│   │                       (kanal bazında gönderim takibi, yeniden    │
│   │                        deneme, e-posta arıza uyarısı)            │
│   └─ radar/izleme.py      turun TÜM kayıtlarını yapılandırılmış      │
│                           JSON olarak Loki'ye gönderir (LOKI_* boşsa │
│                           kapalı; hata radarı asla durdurmaz; tur    │
│                           çökerse tek "coktu" kaydı gider)           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │  yalnızca HTTPS push · Basic Auth
                               │  gizli bilgiler redact() ile maskeli
                               ▼
┌─────────────────────────── Grafana Cloud (ücretsiz) ─────────────────┐
│  tek yığın · bölge: EU Germany · giriş: Google OAuth (2 Adımlı)      │
│                                                                      │
│  Loki (log deposu)         14 gün geçmiş, LogQL ile arama            │
│  Dashboard "İzleme Paneli" servis durumu · son başarılı kontrol ·    │
│                            24 saatlik hata sayısı · tur süresi ·     │
│                            kaynak tablosu · kanal başarı oranları ·  │
│                            canlı hata akışı                          │
│  Alarm kuralları           aşağıdaki tabloda                         │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
        Telegram (teknik grup)        E-posta (kişisel adres)
```

İkinci bir güvenlik ağı radarın **kendi içinde** zaten vardır ve Grafana'dan
bağımsız çalışır: kaynak 24 saattir okunamıyorsa Telegram teknik uyarısı,
e-posta kanalı arızalanınca Telegram'a tek seferlik uyarı (24 saatte bir
hatırlatma, 3 gün sonra o mesaj için vazgeçme), günlük/haftalık özetlerde
"Sorunlar" bölümü.

## Loki'ye giden kayıtlar

Her satır tek bir JSON olaydır. Etiketler: `app="tarife-radari"`,
`ortam="github"|"yerel"`, `level="info"|"error"`. `--deneme` turları
Loki'ye yazılmaz.

| olay       | alanlar                                                        | örnek soru                       |
| ---------- | -------------------------------------------------------------- | -------------------------------- |
| `tur`      | durum (tamam/kismi/hata/coktu), tetik (zamanlayici/elle/schedule/yerel), sure_sn, cpu_sn, bellek_mb, kaynak, kaynak_hata, bildirim_hata, yeni_kayit, aday, yazilan; çökmede hata | "Son tur ne zaman, kaç sn sürdü, neyle başladı?" |
| `kaynak`   | kaynak (id), durum (tamam/HATA), bilgi                         | "KGM en son ne zaman okundu?"    |
| `bildirim` | kanal (telegram/whatsapp/email; satırın girişinden okunur, teknik grup = telegram), durum, mesaj | "E-posta gönderimleri başarılı mı?" |
| `not`      | mesaj (ücret tablosu, saat dilimi vb. yan işler)               | "Gişe tablosu güncellenmiş mi?"  |
| `durum`    | mesaj (olay yaşam döngüsü geçişleri)                           | "Bu hafta hangi kararlar ilerledi?" |

Kod: `radar/izleme.py`. Her alan JSON'a çevrilmeden **önce** `guvenlik.redact()`
süzgecinden geçer: ayarlardaki şifre, anahtar, alıcı telefon numaraları ve
bilinen anahtar biçimleri maskelenir; bunlara ek olarak metindeki **her**
e-posta adresi maskelenir. Ayarlarda olmayan rastgele bir telefon numarası
için genel bir desen yoktur (radar satırlarında böyle bir veri geçmez).

## Alarm kuralları (Grafana)

Tur sayan kurallar **yalnızca `ortam="github"`** satırlarına bakar: yerel
çalıştırmalar GitHub'ın durduğunu gizlememeli.

| Alarm                   | Sorgu (LogQL) ve koşul                                                                                         | Anlamı                                   |
| ----------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Radar turu yok          | `sum(count_over_time({app="tarife-radari", ortam="github"} \| json \| olay="tur" [90m]))` < 1; **No data → Alerting** | Zamanlayıcı durdu / iş akışı bozuldu / GitHub kesintisi |
| Tur çöktü               | `sum(count_over_time({app="tarife-radari", ortam="github"} \| json \| olay="tur" \| durum="coktu" [30m]))` > 0 | Radar istisnayla yarıda kesildi |
| Kaynak okunamıyor       | `olay="kaynak" durum="HATA"`, aynı kaynak için art arda                                                         | KGM/UAB sitesi değişti ya da erişilemiyor |
| Bildirim gönderilemiyor | `olay="bildirim" durum="hata"` görüldü                                                                          | Telegram/WhatsApp/e-posta anahtarı bozuldu |
| Hata yoğunluğu          | Son 24 saatte `level="error"` sayısı eşiği aştı                                                                 | Genel sağlık bozuluyor                   |
| Tur anormal yavaş       | `olay="tur"` satırlarında `sure_sn` eşiği aştı                                                                  | Kaynak siteler yavaş / askıda            |

"Radar turu yok" kuralında **No data → Alerting** zaten ayarlıdır. Eşik
(90 dk) dış zamanlayıcı kurulduktan sonra bir gün izlenip doğrulanır:
30 dakikalık düzende iki tur kaçırılırsa alarm verir.

Alarm bildirimi: Telegram teknik grubu + e-posta. (Grafana'nın kendisi
ulaşamazsa bile radarın iç uyarıları çalışmaya devam eder.)

## Gereksinim karşılama tablosu

| Gereksinim                                   | Durum | Nasıl                                                   |
| -------------------------------------------- | ----- | ------------------------------------------------------- |
| Uygulamanın çalışma durumu (uptime)          | ✔     | `tur` olayının varlığı = canlılık; 90 dk yokluk alarmı; çökme ayrı alarm |
| Hata ve işlem loglarını merkezde toplamak    | ✔     | Tüm tur kayıtları Loki'de, LogQL ile aranabilir          |
| Fiyat kontrolü başarılı/başarısız takibi     | ✔     | `kaynak` ve `not` olayları; `tur.durum` = tamam/kismi/hata |
| Son başarılı kontrol zamanı                  | ✔     | Dashboard'da "son başarılı tur" paneli (`durum="tamam"`); ayrıca panel sitesinde `health.json` |
| Bildirim kanallarının gönderim durumu        | ✔     | `bildirim` olayları, kanal etiketiyle                    |
| Hata / durma / uzun süre işlem yok alarmı    | ✔     | Yukarıdaki alarm tablosu                                 |
| Dashboard'dan geçmiş kayıtlar                | ✔     | Ücretsiz planda 14 gün log geçmişi                       |
| CPU, RAM, performans metrikleri              | ✔     | Her tur kendi ölçüsünü yazar: `sure_sn` (süre), `cpu_sn` (işlemci süresi), `bellek_mb` (en yüksek bellek; Linux'ta). Sanal makinenin geneli izlenmez: makine tek kullanımlıktır ve 2 dk sonra yok olur. |
| SMS gönderim takibi                          | ✖     | Sistemde SMS kanalı yok (kanallar: Telegram, WhatsApp, e-posta). SMS eklenirse `bildirim` olayına `kanal="sms"` olarak kendiliğinden girer. |
| Docker ile kurulum                           | ✖     | Gerek kalmadı: izleme tarafı Grafana Cloud'da hazır çalışır, kurulup bakılacak sunucu yok. |

## Güvenlik

- `LOKI_URL`, `LOKI_USER`, `LOKI_TOKEN` yalnızca `.env` (git dışı) ve GitHub
  Secrets'ta durur; `yayinla --yalnizca-ayarlar` ile yüklenir. Kalıcı anahtar
  yalnızca `logs:write` yetkilidir: log okuyamaz, kural ya da pano değiştiremez.
- `LOKI_URL` `https://` ile başlamıyorsa izleme gönderim yapmaz (Basic Auth
  açık metin gitmesin).
- Loki'ye giden her alan JSON'a çevrilmeden önce maskelenir (yukarıda).
- Grafana'ya giriş **Google OAuth** iledir; Google hesabında **2 Adımlı
  Doğrulama** açıktır. Kuruluşta yönetici hesabı ve alarm e-postası için
  eklenen bir **Viewer** üye vardır; dashboard dışarıya açık değildir.
- Grafana'da kural/pano değişikliği için kalıcı yönetici anahtarı **tutulmaz**:
  gerektiğinde kısa süreli bir servis hesabı açılır, iş bitince silinir.
- Dış zamanlayıcı anahtarı (`GH_TOKEN`) yalnızca Cloudflare'de şifreli durur;
  yalnızca bu depoda iş akışı başlatabilir (kod, veri, secret okuyamaz).
- `guvenlik.SECRET_PATTERNS` Grafana anahtar biçimlerini (`glc_`, `glsa_`) de
  tanır; yayın taraması bunları depoda yakalar.
- İzleme tamamen isteğe bağlıdır: anahtarlar silinirse radar hiçbir şey
  kaybetmeden çalışmaya devam eder.

### Anahtar yenileme notları

| Anahtar | Nerede | Yenilerken |
| --- | --- | --- |
| GitHub fine-grained anahtar (`GH_TOKEN`) | Cloudflare secret | Süresi 1 yıl; dolmadan yenile, `wrangler secret put GH_TOKEN` |
| Telegram bot anahtarı | GitHub Secrets **ve** Grafana alarm kanalı (`otoyol-alarm`) | İki yerde birden değiştir |
| `LOKI_TOKEN` | `.env` ve GitHub Secrets | Grafana'da yenile, `.env`'ye yaz, `yayinla --yalnizca-ayarlar` |

## Maliyet

Her bileşen ücretsiz katmanda: GitHub Actions (herkese açık depo),
Grafana Cloud Free (14 gün log, 10k seri metrik, alarmlar dahil),
Cloudflare Workers Free (cron tetikleyici; günde 48 çağrı),
Telegram/WhatsApp/Gmail mevcut kurulum.

## Kurulum durumu

- [x] Radar tarafı: `radar/izleme.py`, iş akışı değişkenleri, testler (`79405eb`)
- [x] Grafana Cloud hesabı (EU Germany; `LOKI_URL` ile aynı yığın)
- [x] Loki bağlantı bilgileri `.env`'de (`LOKI_URL`, `LOKI_USER`, `LOKI_TOKEN`; token yalnızca `logs:write` yetkili)
- [x] Anahtarlar GitHub Secrets'ta (`python -m radar yayinla --yalnizca-ayarlar`)
- [x] İlk kayıtlar Loki'de (yerelden ve GitHub turundan)
- [x] "İzleme Paneli" dashboard'u: `/d/otoyol-izleme-paneli` (klasör: Otoyol İzleme)
- [x] Alarm kuralları (grup `otoyol`, 10 dk'da bir) + Telegram teknik grubu bağlantısı
- [x] E-posta alarm kanalı: alıcı adres Grafana'ya **Viewer** olarak eklendi (Grafana yalnızca kuruluş
      üyesi adreslere alarm e-postası gönderir); `otoyol-alarm` artık Telegram + e-posta
- [x] Alarm tatbikatı: sahte bir bildirim hatası kaydı gönderildi, "Bildirim gönderilemedi" alarmı tetiklendi (15 Kasım 2026)
- [x] Kurulum için açılan geçici Admin servis hesabı (`otoyol-kurulum`) silindi; kalıcı anahtar yalnızca `logs:write`
- [x] İzleme düzeltmeleri: çökme kaydı, kanal ayrıştırma, tur durumu, CPU/bellek, deneme turlarının dışlanması, https zorunluluğu
- [ ] Dış zamanlayıcı: `tetikleyici/KURULUM.md` adımları (GitHub anahtarı + Cloudflare)
- [ ] Grafana kuralları: "Radar turu yok" sorgusuna `ortam="github"` süzgeci; "Tur çöktü" kuralı; kural listesinin bu belgeyle eşitlenmesi
- [ ] Zamanlayıcı kurulduktan 24 saat sonra: ~48 tur/gün ve 90 dk eşiğinin doğrulanması

## Grafana tarafındaki nesneler

| Nesne              | Ad / kimlik                         | Not                                        |
| ------------------ | ----------------------------------- | ------------------------------------------ |
| Klasör             | Otoyol İzleme (`otoyol-izleme`)     | pano ve alarm kuralları burada             |
| Pano               | İzleme Paneli (`otoyol-izleme-paneli`) | 24 saat görünüm, 5 dk'da bir yenilenir  |
| Kural grubu        | `otoyol` (10 dk aralık)             | kurulumda 4 kural; "Tur çöktü" eklenecek ve liste alarm tablosuyla eşitlenecek; hepsi `app=tarife-radari` etiketli |
| Alarm kanalı       | `otoyol-alarm`                      | Telegram teknik grubu + e-posta            |
| Bildirim yönlendirme | `app=tarife-radari` → `otoyol-alarm` | 4 saatte bir tekrar hatırlatır            |
| Erişim ilkesi      | `otoyol-radar-yaz` (yalnızca logs:write) | radarın kalıcı log gönderim anahtarı   |
