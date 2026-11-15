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

## Genel görünüm

```
┌─────────────────────────── GitHub Actions ───────────────────────────┐
│  radar.yml · 30 dakikada bir (cron) · timeout 20 dk                  │
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
│                           kapalı; hata radarı asla durdurmaz)        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │  HTTPS push · Basic Auth
                               │  gizli bilgiler redact() ile maskeli
                               ▼
┌─────────────────────────── Grafana Cloud (ücretsiz) ─────────────────┐
│  valiantpea937.grafana.net · bölge: EU Germany                       │
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
`ortam="github"|"yerel"`, `level="info"|"error"`.

| olay       | alanlar                                                        | örnek soru                       |
| ---------- | -------------------------------------------------------------- | -------------------------------- |
| `tur`      | sure_sn, kaynak, kaynak_hata, bildirim_hata, yeni_kayit, aday, yazilan | "Son tur ne zaman, kaç sn sürdü?" |
| `kaynak`   | kaynak (id), durum (tamam/HATA), bilgi                         | "KGM en son ne zaman okundu?"    |
| `bildirim` | kanal (telegram/whatsapp/email), durum, mesaj                  | "E-posta gönderimleri başarılı mı?" |
| `not`      | mesaj (ücret tablosu, saat dilimi vb. yan işler)               | "Gişe tablosu güncellenmiş mi?"  |
| `durum`    | mesaj (olay yaşam döngüsü geçişleri)                           | "Bu hafta hangi kararlar ilerledi?" |

Kod: `radar/izleme.py`. Her satır gönderilmeden önce `guvenlik.redact()`
süzgecinden geçer: şifre, anahtar, telefon numarası, e-posta adresi Loki'ye
**gitmez**.

## Alarm kuralları (Grafana tarafında kurulacak)

| Alarm                      | Koşul                                               | Anlamı                                   |
| -------------------------- | --------------------------------------------------- | ---------------------------------------- |
| Tur çalışmıyor             | 90 dk boyunca hiç `olay="tur"` kaydı yok            | GitHub durdu / iş akışı bozuldu / cron gecikti |
| Kaynak okunamıyor          | Aynı kaynak için art arda `durum="HATA"`            | KGM/UAB sitesi değişti ya da erişilemiyor |
| Bildirim gönderilemiyor    | `olay="bildirim" durum="hata"` görüldü              | Telegram/WhatsApp/e-posta anahtarı bozuldu |
| Hata yoğunluğu             | Son 24 saatte `level="error"` sayısı eşiği aştı     | Genel sağlık bozuluyor                   |
| Tur anormal yavaş          | `sure_sn` eşiği aştı                                | Kaynak siteler yavaş / askıda            |

Alarm bildirimi: Telegram teknik grubu + e-posta. (Grafana'nın kendisi
ulaşamazsa bile radarın iç uyarıları çalışmaya devam eder.)

## Gereksinim karşılama tablosu

| Gereksinim                                   | Durum | Nasıl                                                   |
| -------------------------------------------- | ----- | ------------------------------------------------------- |
| Uygulamanın çalışma durumu (uptime)          | ✔     | `tur` olayının varlığı = canlılık; 90 dk yokluk alarmı   |
| Hata ve işlem loglarını merkezde toplamak    | ✔     | Tüm tur kayıtları Loki'de, LogQL ile aranabilir          |
| Fiyat kontrolü başarılı/başarısız takibi     | ✔     | `kaynak` ve `not` olayları (tarife, gişe tablosu)        |
| Son başarılı kontrol zamanı                  | ✔     | Dashboard'da "son başarılı tur" paneli; ayrıca panel sitesinde `health.json` |
| Bildirim kanallarının gönderim durumu        | ✔     | `bildirim` olayları, kanal etiketiyle                    |
| Hata / durma / uzun süre işlem yok alarmı    | ✔     | Yukarıdaki alarm tablosu                                 |
| Dashboard'dan geçmiş kayıtlar                | ✔     | Ücretsiz planda 14 gün log geçmişi                       |
| CPU, RAM, performans metrikleri              | ◐     | Bilinçli olarak kapsam dışı: her tur GitHub'ın tek kullanımlık sanal makinesinde çalışır; CPU/RAM o makineye aittir ve 2 dk sonra yok olur. Anlamlı performans ölçüsü **tur süresidir** (`sure_sn`), o izlenir. |
| SMS gönderim takibi                          | ✖     | Sistemde SMS kanalı yok (kanallar: Telegram, WhatsApp, e-posta). SMS eklenirse `bildirim` olayına `kanal="sms"` olarak kendiliğinden girer. |
| Docker ile kurulum                           | ✖     | Gerek kalmadı: izleme tarafı Grafana Cloud'da hazır çalışır, kurulup bakılacak sunucu yok. |

## Güvenlik

- `LOKI_URL`, `LOKI_USER`, `LOKI_TOKEN` yalnızca `.env` (git dışı) ve GitHub
  Secrets'ta durur; `yayinla --yalnizca-ayarlar` ile yüklenir.
- Loki'ye giden her satır maskelenir; kişisel veri ve anahtar içermez.
- Grafana hesabı tek kullanıcılıdır; dashboard dışarıya açık değildir.
- İzleme tamamen isteğe bağlıdır: anahtarlar silinirse radar hiçbir şey
  kaybetmeden çalışmaya devam eder.

## Maliyet

Her bileşen ücretsiz katmanda: GitHub Actions (herkese açık depo),
Grafana Cloud Free (14 gün log, 10k seri metrik, alarmlar dahil),
Telegram/WhatsApp/Gmail mevcut kurulum.

## Kurulum durumu

- [x] Radar tarafı: `radar/izleme.py`, iş akışı değişkenleri, testler (`79405eb`)
- [x] Grafana Cloud hesabı: **valiantpea937.grafana.net** (EU Germany)
- [x] Loki bağlantı bilgileri `.env`'de (`LOKI_URL`, `LOKI_USER`, `LOKI_TOKEN`; token yalnızca `logs:write` yetkili)
- [x] Anahtarlar GitHub Secrets'ta (`python -m radar yayinla --yalnizca-ayarlar`)
- [x] İlk kayıtlar Loki'de (yerelden ve GitHub turundan)
- [x] "İzleme Paneli" dashboard'u: `/d/otoyol-izleme-paneli` (klasör: Otoyol İzleme)
- [x] Alarm kuralları (grup `otoyol`, 10 dk'da bir) + Telegram teknik grubu bağlantısı
- [ ] E-posta alarm kanalı: Grafana yalnızca kuruluş üyesi adreslere alarm e-postası gönderir;
      alıcı adres Grafana'ya **Viewer** olarak davet edilip daveti kabul ettikten sonra eklenecek
- [x] Alarm tatbikatı: sahte bir bildirim hatası kaydı gönderildi, "Bildirim gönderilemedi" alarmı tetiklendi (15 Kasım 2026)
- [ ] Kurulum için açılan geçici Admin servis hesabının (`otoyol-kurulum`) silinmesi

## Grafana tarafındaki nesneler

| Nesne              | Ad / kimlik                         | Not                                        |
| ------------------ | ----------------------------------- | ------------------------------------------ |
| Klasör             | Otoyol İzleme (`otoyol-izleme`)     | pano ve alarm kuralları burada             |
| Pano               | İzleme Paneli (`otoyol-izleme-paneli`) | 24 saat görünüm, 5 dk'da bir yenilenir  |
| Kural grubu        | `otoyol` (10 dk aralık)             | 4 kural, hepsi `app=tarife-radari` etiketli |
| Alarm kanalı       | `otoyol-alarm`                      | Telegram teknik grubu (+ e-posta, üyelik sonrası) |
| Bildirim yönlendirme | `app=tarife-radari` → `otoyol-alarm` | 4 saatte bir tekrar hatırlatır            |
| Erişim ilkesi      | `otoyol-radar-yaz` (yalnızca logs:write) | radarın kalıcı log gönderim anahtarı   |
