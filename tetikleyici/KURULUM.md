# Dış zamanlayıcı kurulumu (Cloudflare Workers)

GitHub Actions'ın kendi `*/30` zamanlaması yoğunlukta seyreltiliyor: Kasım 2026 kayıtlarına göre günde 48 yerine
yalnızca 3-4 tur çalışıyor. Bu klasördeki küçük worker, radar turunu 30 dakikada bir (her saatin 05 ve 35. dakikası,
UTC) `workflow_dispatch` ile başlatır. GitHub'daki cron yedek olarak kalır; iki tetikleme çakışırsa iş akışındaki
`concurrency` ayarı turları sıraya koyar.

- Worker'ın herkese açık adresi yoktur: `workers_dev = false`, rota yok. Dışarıdan çağrılamaz.
- Tek gizli bilgi `GH_TOKEN`'dır. Yalnızca bu depoda ve yalnızca Actions yetkisiyle çalışır, Cloudflare'de şifreli
  saklanır. Depoya, `.env`'ye ya da ekrana yazılmaz.
- Zamanlayıcının başlattığı turlarda veri değişmediyse panel yeniden yayımlanmaz.
- Tüm adımlar ücretsiz planda yapılır. Alan adı ya da kredi kartı gerekmez.

## 1. GitHub anahtarı (fine-grained personal access token)

1. GitHub'da sağ üstteki profil resmi → **Settings**.
2. Sol menünün en altında **Developer settings**.
3. **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
4. Formu şöyle doldur:
   - **Token name:** `tarife-radari-zamanlayici`
   - **Description:** `Cloudflare zamanlayıcısı radar.yml'i başlatır`
   - **Resource owner:** kendi hesabın (`metinakdas`)
   - **Expiration:** **Custom** → bugünden 1 yıl sonrası. Bitiş tarihini takvimine yaz; yenileme adımı aşağıda.
   - **Repository access:** **Only select repositories** → `metinakdas/otoyol-ucretleri`
   - **Permissions** → **Repository permissions** → **Actions:** **Read and write**
     (**Metadata: Read-only** kendiliğinden eklenir.) Başka hiçbir yetki verme.
5. **Generate token** → açılan özet ekranında yetkileri bir kez daha kontrol et → **Generate token**.
6. Anahtar (`github_pat_...`) yalnızca bir kez gösterilir. Kopyala ve 3. bölümdeki adıma kadar panoda tut.
   Bir dosyaya, sohbete ya da `.env`'ye yapıştırma.

## 2. Cloudflare hesabı

1. https://dash.cloudflare.com/sign-up → e-posta ve şifreyle (ya da Google ile) kaydol.
2. Gelen doğrulama e-postasındaki bağlantıya tıkla.
3. Panelde "alan adı ekle" önerisini atla; alan adı gerekmez.
4. Sol menüden **Compute (Workers)** → **Workers & Pages** açılır. Bir `workers.dev` alt alan adı seçmen istenirse
   rastgele bir ad yazman yeterli. Bu worker o adresi kullanmaz.
5. Önerilir: sağ üst → **My Profile** → **Authentication** → **Two-Factor Authentication**'ı aç.
   Google ile girdiysen Google hesabının 2 Adımlı Doğrulaması bunu karşılar.

## 3. Worker'ı yükle (kendi PowerShell pencerende)

Bu adımlar tarayıcı girişi ve gizli giriş istediği için kendi terminalinde çalıştırılmalı.

```powershell
# Depo klasöründen:
cd tetikleyici

# 1) Cloudflare'e giriş: tarayıcı açılır → "Allow" de. Terminalde "Successfully logged in" görünür.
npx wrangler@4.156.0 login

# 2) Worker'ı yükle. Çıktıda "Deployed tarife-radari-zamanlayici triggers" ve
#    "schedule: 5,35 * * * *" görünmeli. workers.dev adresi YAZMAMALI.
npx wrangler@4.156.0 deploy

# 3) GitHub anahtarını Cloudflare'e kaydet: "Enter a secret value" sorusunda anahtarı yapıştır
#    (yazdıkların ekranda görünmez) → Enter. "Success! Uploaded secret GH_TOKEN" görünür.
npx wrangler@4.156.0 secret put GH_TOKEN
```

İşin bitince panoyu temizle: başka bir metin kopyala.

## 4. Doğrulama

- Bir sonraki :05 ya da :35'i bekle. Ardından GitHub → **Actions** → **Tarife Radarı**. Yeni turun tetikleyicisi
  `workflow_dispatch` olmalı.
- Cloudflare paneli → **Workers & Pages** → `tarife-radari-zamanlayici` → **Logs**: "Radar turu başlatıldı."
  görünmeli. Canlı izlemek için `npx wrangler@4.156.0 tail` de kullanılabilir.
- Hata görürsen:
  - `GitHub 401` ya da `403`: anahtar yanlış, süresi dolmuş ya da Actions yetkisi eksik.
  - `GitHub 404`: anahtar bu depoya erişemiyor (Repository access'i kontrol et).
  - `GitHub 422`: iş akışında `tetik` girdisi yok. `main` dalını kontrol et.
- Grafana'da `{app="tarife-radari"} | json | olay="tur"` sorgusunda `tetik="zamanlayici"` olan satırlar görünmeli.

## Yenileme ve durdurma

- **Anahtarın süresi dolmadan:** GitHub'da aynı anahtarın sayfasında **Regenerate token** → yeni anahtarı kopyala →
  `npx wrangler@4.156.0 secret put GH_TOKEN` ile yeniden kaydet.
- **Anahtar sızdıysa:** GitHub'da anahtarı hemen **Delete** et. Etkisi bu depoda iş akışı başlatmaktan ibarettir;
  kod, veri ya da secret okuyamaz. Ardından yeni bir anahtar oluşturup kaydet.
- **Zamanlayıcıyı durdurmak:** `npx wrangler@4.156.0 delete`. Radar GitHub'ın kendi cron'uyla
  (günde birkaç tur) çalışmaya devam eder.
