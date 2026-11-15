"""Grafana Cloud alarm kurulumunu depodaki dosyalardan uygular.

    python grafana/uygula.py durum              kurallar, alarm kanalı ve şablonların özeti (yalnızca okur)
    python grafana/uygula.py sablon             sablonlar/otoyol-alarm.tmpl dosyasını yükler
    python grafana/uygula.py kanal [duz|html]   otoyol-alarm kanalının konu ve mesaj alanlarını şablona bağlar
                                                (varsayılan duz: Grafana e-posta gövdesindeki HTML'i kaçışlar,
                                                html seçeneği gelen kutusunda ham kod olarak görünür)
    python grafana/uygula.py kurallar           kurallar.json + aciklamalar.json -> "otoyol" kural grubu
    python grafana/uygula.py tatbikat-kur       geçici tatbikat kuralı (sonraki 3 dakikada alarm, sonra çözüldü)
    python grafana/uygula.py tatbikat-sil       tatbikat kuralını siler

Gereken: ortamda ya da .env'de GRAFANA_URL ve GRAFANA_SA_TOKEN (geçici, Editor yetkili servis hesabı).
Betik bu iki değeri ve alarm kanalındaki gizli alanları (bot anahtarı, sohbet kimliği, adresler)
hiçbir zaman ekrana yazmaz. İş bitince servis hesabı silinmeli, iki satır .env'den kaldırılmalıdır.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import httpx

KOK = Path(__file__).resolve().parent
KLASOR = "otoyol-izleme"
KANAL = "otoyol-alarm"
SABLON_ADI = "otoyol-alarm"
TATBIKAT_GRUP = "otoyol-tatbikat"
TATBIKAT_IZ = "tatbikat-sablon"
# Arayüzden de düzenlenebilsin diye "API ile sağlandı" kilidi konmaz
BASLIK = {"X-Disable-Provenance": "true"}
GIZLI_ALAN = ("bottoken", "chatid", "addresses", "password", "token", "url", "message_thread_id")


def ayar() -> tuple[str, str]:
    deger = {k: os.environ.get(k, "") for k in ("GRAFANA_URL", "GRAFANA_SA_TOKEN")}
    env = KOK.parent / ".env"
    if env.is_file():
        for satir in env.read_text(encoding="utf-8").splitlines():
            ad, _, v = satir.partition("=")
            if ad.strip() in deger and not deger[ad.strip()]:
                deger[ad.strip()] = v.strip().strip('"').strip("'")
    url, anahtar = deger["GRAFANA_URL"].rstrip("/"), deger["GRAFANA_SA_TOKEN"]
    if not (url.startswith("https://") and anahtar):
        sys.exit("GRAFANA_URL (https ile başlamalı) ya da GRAFANA_SA_TOKEN tanımlı değil.")
    return url, anahtar


def istemci() -> httpx.Client:
    url, anahtar = ayar()
    return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {anahtar}"}, timeout=30)


def gizle(metin) -> str:
    url, anahtar = ayar()
    return str(metin).replace(anahtar, "***").replace(url, "<grafana>")


def tamam(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 300:
        sys.exit(f"HTTP {r.status_code}: {gizle(r.text)[:600]}")
    return r


def aciklamalar() -> dict:
    d = json.loads((KOK / "aciklamalar.json").read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def kural_grubu() -> dict:
    """kurallar.json'daki kurallara aciklamalar.json'daki etiket ve açıklamaları ekler."""
    d = json.loads((KOK / "kurallar.json").read_text(encoding="utf-8"))
    acik = aciklamalar()
    for r in d["grup"]["rules"]:
        a = acik.get(r["grafana_alert"]["title"])
        if not a:
            sys.exit(f"aciklamalar.json içinde yok: {r['grafana_alert']['title']}")
        r["labels"] = {"app": "tarife-radari", "onem": a["onem"]}
        r["annotations"] = {"ozet": a["ozet"], "aciklama": a["aciklama"], "ne_yapmali": "\n".join(a["ne_yapmali"])}
    return d


# ---------------------------------------------------------------- komutlar

def durum() -> None:
    with istemci() as c:
        r = c.get("/api/health")
        print("Grafana sürümü:", r.json().get("version") if r.status_code == 200 else r.status_code)
        for klasor, gruplar in tamam(c.get("/api/ruler/grafana/api/v1/rules")).json().items():
            for g in gruplar:
                print(f"\nKural grubu: {g['name']} ({g.get('interval')})")
                for k in g["rules"]:
                    a = k["grafana_alert"]
                    print(f"  {a['title']:28} etiket={k.get('labels')} açıklama={sorted((k.get('annotations') or {}))}")
        print("\nAlarm kanalı:")
        for cp in tamam(c.get("/api/v1/provisioning/contact-points")).json():
            s = {k: ("<gizli>" if k in GIZLI_ALAN else v) for k, v in (cp.get("settings") or {}).items()}
            print(f"  {cp['name']} · {cp['type']} · {s}")
        r = c.get("/api/v1/provisioning/templates")
        print("\nŞablonlar:", [t.get("name") for t in r.json() or []] if r.status_code == 200 else r.status_code)
        r = c.get("/api/alertmanager/grafana/config/api/v1/receivers")
        if r.status_code == 200:
            print("\nSon teslim:")
            for rc in r.json():
                for i in rc.get("integrations", []):
                    print(f"  {rc['name']} · {i['name']} · {str(i.get('lastNotifyAttempt', ''))[:19]} · "
                          f"hata={gizle(i.get('lastNotifyAttemptError', ''))[:300] or 'yok'}")
        r = c.get("/api/alertmanager/grafana/api/v2/alerts")
        if r.status_code == 200:
            print("\nEtkin alarmlar:", [(a["labels"].get("alertname"), a["startsAt"][:19]) for a in r.json()] or "yok")


def sablon() -> None:
    metin = (KOK / "sablonlar" / "otoyol-alarm.tmpl").read_text(encoding="utf-8")
    with istemci() as c:
        govde = {"name": SABLON_ADI, "template": metin}
        r = c.get(f"/api/v1/provisioning/templates/{SABLON_ADI}")
        if r.status_code == 200 and r.json().get("version"):
            govde["version"] = r.json()["version"]
        tamam(c.put(f"/api/v1/provisioning/templates/{SABLON_ADI}", json=govde, headers=BASLIK))
    print(f"Şablon yüklendi: {SABLON_ADI} ({len(metin)} karakter)")


def kanal(govde_turu: str = "duz") -> None:
    eposta = "otoyol.eposta" if govde_turu == "html" else "otoyol.eposta_duz"
    with istemci() as c:
        noktalar = [cp for cp in tamam(c.get("/api/v1/provisioning/contact-points")).json() if cp["name"] == KANAL]
        if not noktalar:
            sys.exit(f"Alarm kanalı bulunamadı: {KANAL}")
        for cp in noktalar:
            s = cp.setdefault("settings", {})   # gizli alanlar "[REDACTED]" olarak gelir; Grafana kayıtlı değeri korur
            if cp["type"] == "email":
                s["subject"] = '{{ template "otoyol.konu" . }}'
                s["message"] = '{{ template "' + eposta + '" . }}'
                s["singleEmail"] = True
            elif cp["type"] == "telegram":
                s["message"] = '{{ template "otoyol.telegram" . }}'
                s["parse_mode"] = "HTML"
                s["disable_web_page_preview"] = True
            else:
                continue
            cp.pop("provenance", None)
            tamam(c.put(f"/api/v1/provisioning/contact-points/{cp['uid']}", json=cp, headers=BASLIK))
            print(f"Kanal güncellendi: {cp['name']} · {cp['type']}" + (f" · gövde: {eposta}" if cp["type"] == "email" else ""))


def kurallar() -> None:
    d = kural_grubu()
    with istemci() as c:
        r = tamam(c.post(f"/api/ruler/grafana/api/v1/rules/{d['klasor_uid']}", json=d["grup"], headers=BASLIK))
    print("Kurallar yazıldı:", gizle(r.text)[:300])


def tatbikat_kur() -> None:
    """Yalnızca tatbikat izini taşıyan kayıtları sayan geçici kural. Kayıt 3 dakikalık pencereden çıkınca çözülür."""
    d = kural_grubu()
    ornek = copy.deepcopy([r for r in d["grup"]["rules"] if r["grafana_alert"]["title"] == "Bildirim gönderilemedi"][0])
    a = ornek["grafana_alert"]
    a.pop("uid", None)
    a["title"] = "TATBİKAT"
    a["no_data_state"] = "OK"
    a["data"][0]["model"]["expr"] = ('sum(count_over_time({app="tarife-radari"} |= `' + TATBIKAT_IZ + '` [3m]))')
    ornek["labels"]["onem"] = "tatbikat"
    ornek["annotations"]["ozet"] = "TATBİKAT: " + ornek["annotations"]["ozet"]
    grup = {"name": TATBIKAT_GRUP, "interval": "1m", "rules": [ornek]}
    with istemci() as c:
        tamam(c.post(f"/api/ruler/grafana/api/v1/rules/{KLASOR}", json=grup, headers=BASLIK))
    print(f"Tatbikat kuralı kuruldu. Tetiklemek için Loki'ye '{TATBIKAT_IZ}' içeren bir kayıt gönderin.")


def tatbikat_sil() -> None:
    with istemci() as c:
        r = c.delete(f"/api/ruler/grafana/api/v1/rules/{KLASOR}/{TATBIKAT_GRUP}")
    print("Tatbikat kuralı silindi." if r.status_code < 300 else f"HTTP {r.status_code}: {gizle(r.text)[:200]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    komutlar = {"durum": durum, "sablon": sablon, "kanal": kanal, "kurallar": kurallar,
                "tatbikat-kur": tatbikat_kur, "tatbikat-sil": tatbikat_sil}
    if len(sys.argv) < 2 or sys.argv[1] not in komutlar:
        sys.exit(__doc__)
    komutlar[sys.argv[1]](*sys.argv[2:3])
