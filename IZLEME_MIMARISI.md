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

Grup `otoyol`, klasör Otoyol İzleme, 10 dakikada bir değerlendirilir. Her
kural `app=tarife-radari` etiketlidir ve `otoyol-alarm` kanalına gider.
Sorgular satır süzgeci kullanır: `T` = `` {app="tarife-radari", ortam="github"} |= `"olay": "tur"` ``.
Tur sayan kurallar **yalnızca `ortam="github"`** satırlarına bakar: yerel
çalıştırmalar GitHub'ın durduğunu gizlememeli.

| Grafana'daki ad           | Sorgu (LogQL)                                                                  | Koşul  | Veri yoksa | Anlamı |
| ------------------------- | ------------------------------------------------------------------------------ | ------ | ---------- | ------ |
| Radar turu yok (90 dk)    | `sum(count_over_time(T [90m]))`                                                | < 1    | **Alerting** | Zamanlayıcı durdu / iş akışı bozuldu / GitHub kesintisi |
| Tur çöktü                 | `` sum(count_over_time(T \|= `"durum": "coktu"` [30m])) ``                       | > 0    | OK | Radar istisnayla yarıda kesildi (`hata` alanında ayrıntı) |
| Tur anormal yavaş (5 dk)  | `max(max_over_time(T \| json \| unwrap sure_sn [2h]))`                         | > 300  | OK | Olağan tur 30-60 sn; kaynak siteler yavaş / askıda |
| Kaynak okunamıyor         | `` sum(count_over_time({app="tarife-radari", level="error"} \|= `"olay": "kaynak"` [3h])) `` | > 3 | OK | KGM/UAB sitesi değişti ya da erişilemiyor (30 dk düzende ~6 turun 4'ü) |
| Bildirim gönderilemedi    | `` sum(count_over_time({app="tarife-radari", level="error"} \|= `"olay": "bildirim"` [1h])) `` | > 0 | OK | Telegram/WhatsApp/e-posta anahtarı bozuldu |
| Hata yoğunluğu (24s)      | `sum(count_over_time({app="tarife-radari", level="error"} [24h]))`             | > 10   | OK | Genel sağlık bozuluyor |

"Radar turu yok" eşiği (90 dk) dış zamanlayıcı kurulduktan sonra bir gün
izlenip doğrulanır: 30 dakikalık düzende iki tur kaçırılırsa alarm verir.
Kurallardaki satır süzgeçleri `json.dumps` biçimine (`"olay": "tur"`, iki
noktadan sonra boşluk) dayanır; `radar/izleme.py`'deki JSON biçimi
değiştirilirse kurallar da güncellenmelidir.

Alarm bildirimi: Telegram teknik grubu + e-posta. (Grafana'nın kendisi
ulaşamazsa bile radarın iç uyarıları çalışmaya devam eder.)

### Bildirimlerin içeriği

Bildirimler Türkçedir ve "ne yapmalıyım" sorusunu yanıtlar. Kaynak dosyalar
depoda `grafana/` klasöründedir; Grafana'ya `python grafana/uygula.py` ile
uygulanır (geçici, Editor yetkili bir servis hesabı gerekir).

| Dosya | İçerik |
| --- | --- |
| `grafana/aciklamalar.json` | Her kuralın `ozet`, `aciklama`, `ne_yapmali` açıklamaları ve `onem` etiketi (kritik / uyari) |
| `grafana/kurallar.json` | Kuralların sorguları ve eşikleri (grup baştan kurulabilsin diye) |
| `grafana/sablonlar/otoyol-alarm.tmpl` | Bildirim şablonları: e-posta konusu, Telegram mesajı, e-posta gövdesi |
| `grafana/uygula.py` | `durum`, `sablon`, `kanal`, `kurallar`, `tatbikat-kur`, `tatbikat-sil` komutları |

- **Önem:** "Radar turu yok", "Tur çöktü" ve "Bildirim gönderilemedi" kritik; diğer üçü uyarı.
- **E-posta konusu:** `[Otoyol İzleme] 🔴 <özet>`; çözülünce `[Otoyol İzleme] ✅ Çözüldü: <özet>`.
  Birden çok alarm gruplanırsa sayı yazılır.
- **Telegram:** durum, özet, başlangıç (Türkiye saati), olası sebep, "Ne yapmalı?" adımları ve
  İzleme Paneli / GitHub Actions / Cloudflare bağlantıları. Çözüldü mesajı kısadır.
- **E-posta gövdesi düz metindir.** Grafana, kanalın mesaj alanını kendi e-posta kalıbına
  yerleştirirken HTML'i kaçışlar; tablo tabanlı tasarım gelen kutusunda ham kod olarak görünür
  (16 Kasım 2026'da Outlook'ta denendi). Kırmızı tasarım şablonda `otoyol.eposta` adıyla durur ama
  kullanılmaz; kullanılan `otoyol.eposta_duz`'dür.
- Açıklama metinlerinde `<`, `>`, `&` kullanılmaz (Telegram HTML biçimi bozulmasın).
- Tatbikat: `tatbikat-kur` geçici bir kural açar; Loki'ye `tatbikat-sablon` içeren bilgi seviyesinde bir
  kayıt gönderilince alarm, 3 dakika sonra çözüldü bildirimi gelir. İş bitince `tatbikat-sil`.

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
- [x] Dış zamanlayıcı: Cloudflare Workers'a yüklendi (`5,35 * * * *`), `GH_TOKEN` secret olarak kayıtlı (15 Kasım 2026)
- [x] Grafana kuralları: "Radar turu yok" yalnızca `ortam="github"`; "Tur çöktü" ve "Tur anormal yavaş (5 dk)" eklendi;
      liste bu belgeyle eşit (6 kural). Değişiklik geçici, yalnızca Editor yetkili bir servis hesabıyla yapıldı.
- [x] Alarm bildirimleri Türkçe şablona geçti; alarm ve çözüldü iki kanalda tatbikatla doğrulandı (16 Kasım 2026)
- [ ] Zamanlayıcı kurulduktan 24 saat sonra: ~48 tur/gün ve 90 dk eşiğinin doğrulanması

## Grafana tarafındaki nesneler

| Nesne              | Ad / kimlik                         | Not                                        |
| ------------------ | ----------------------------------- | ------------------------------------------ |
| Klasör             | Otoyol İzleme (`otoyol-izleme`)     | pano ve alarm kuralları burada             |
| Pano               | İzleme Paneli (`otoyol-izleme-paneli`) | 24 saat görünüm, 5 dk'da bir yenilenir  |
| Kural grubu        | `otoyol` (10 dk aralık)             | 6 kural (yukarıdaki alarm tablosu), hepsi `app=tarife-radari` ve `onem` etiketli |
| Bildirim şablonu   | `otoyol-alarm`                      | kaynak: `grafana/sablonlar/otoyol-alarm.tmpl` |
| Alarm kanalı       | `otoyol-alarm`                      | Telegram teknik grubu + e-posta            |
| Bildirim yönlendirme | `app=tarife-radari` → `otoyol-alarm` | 4 saatte bir tekrar hatırlatır            |
| Erişim ilkesi      | `otoyol-radar-yaz` (yalnızca logs:write) | radarın kalıcı log gönderim anahtarı   |
