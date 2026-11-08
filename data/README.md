# data/

Radarın kendi kayıtları. Bu klasördeki dosyaları radar yazar; elle düzenlemeniz gerekmez.
GitHub Actions her değişikliği bir commit olarak saklar, böylece tüm geçmiş Git'te durur.

| Dosya | İçerik |
| --- | --- |
| `crossings.json` | Geçişlerin tarihli ücret kayıtları (1–6. sınıf). Eski kayıt silinmez, bitiş tarihi doldurulur. |
| `events/*.json` | Her değişiklik kaydı: durum, kanıtlar (kaynak bağlantısı ve alıntı), yürürlük tarihi, geçmiş. |
| `rules/*.json` | Süreli ücretsiz geçiş kuralları (kapsam, başlangıç, bitiş). |
| `state.json` | Kaynakların son durumu: görülen başlıklar, tarife PDF'lerinin özetleri. |
| `health.json` | Kaynak sağlığı: son başarılı okuma, hata. |
| `notifications.json` | Gönderilen bildirimlerin listesi (aynı bildirim iki kez gitmesin diye). |
| `panel.json` | Web panelinin okuduğu özet. |
| `harita.json` | Haritadaki otoyol gişeleri (OpenStreetMap verisi, ayda bir yenilenir). © OpenStreetMap katkıcıları, ODbL. |
| `meta.json` | Panelin en son ne zaman yazıldığı. |

Sıfırdan başlamak isterseniz bu klasördeki README dışındaki her şeyi silin; bir sonraki çalışma
ilk çalıştırma gibi davranır (başlangıç kaydı alır, değişiklik bildirimi göndermez).
