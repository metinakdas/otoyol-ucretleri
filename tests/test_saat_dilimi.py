"""Saat dilimi izleme: eski kurallar uydurularak yeni tzdata sürümünün farkları yakalanıyor mu."""

from __future__ import annotations

from datetime import datetime

import pytest

from radar import saat_dilimi as sd
from radar.store import Store
from radar.timeutil import TZ

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)


@pytest.fixture(scope="module")
def snap():
    paket, iana = sd.surum()
    return sd.anlik_goruntu(NOW, paket, iana)


@pytest.fixture
def ortam(cfg, snap):
    cfg.settings.tz_watch = True
    return cfg, Store(cfg.data_dir), {}, {}


def eski_surum(snap, **degisiklik):
    import copy
    s = copy.deepcopy(snap)
    s["tzdata"] = "2020.1"
    for zone, gs in degisiklik.items():
        if gs is None:
            del s["zones"][zone]
        else:
            s["zones"][zone]["t"] = gs
    return s


def test_snapshot(snap):
    tr = snap["zones"]["Europe/Istanbul"]
    assert tr["cc"] == "TR" and tr["t"] == [[snap["start"], 10800, False]]
    berlin = snap["zones"]["Europe/Berlin"]["t"]
    assert [x[1:] for x in berlin[:3]] == [[3600, False], [7200, True], [3600, False]]
    assert berlin[1][0] == "2027-03-28T01:00+00:00"  # yaz saati dakikasına kadar doğru
    assert len(snap["zones"]) > 300
    assert snap["ulkeler"]["TR"] == "Turkey" and snap["ulkeler"]["DE"] == "Germany"


def test_first_run_sends_setup_once(ortam):
    cfg, store, state, sent = ortam
    msgs, _, written = sd.kontrol(cfg, store, state, sent, NOW)
    assert written and [m.key for m in msgs] == ["saatdilimi:kurulum"]
    assert "Türkiye: UTC+03:00, yaz saati yok." in msgs[0].plain
    assert msgs[0].channels == ("telegram",)
    sent["saatdilimi:kurulum"] = "x"
    msgs, _, written = sd.kontrol(cfg, store, state, sent, NOW)
    assert msgs == [] and not written


def test_offset_change_reported(ortam, snap):
    cfg, store, state, sent = ortam
    start = snap["start"]
    # Eski kurala göre Türkiye UTC+02 olacaktı; Paraguay'ın bölgesi eski kayıtta yoktu
    store.write(sd.DOSYA, eski_surum(snap, **{"Europe/Istanbul": [[start, 7200, False]], "America/Asuncion": None}))
    msgs, notes, written = sd.kontrol(cfg, store, state, sent, NOW)
    assert written and len(msgs) == 1
    m = msgs[0]
    assert m.key.startswith("saatdilimi:") and m.channels == ("telegram", "email")
    assert "[SAAT DİLİMİ DEĞİŞTİ] 2 ülke" in m.plain
    assert "(Europe/Istanbul): Şu andan itibaren UTC+03:00; eski kurala göre UTC+02:00 olacaktı. Yaz saati yok, sabit." in m.plain
    assert "(America/Asuncion): yeni saat dilimi bölgesi, şu an UTC-03:00." in m.plain
    assert "<b>[SAAT DİLİMİ DEĞİŞTİ]" in m.html
    assert store.read(sd.DOSYA, None)["tzdata"] == sd.surum()[0]  # görüntü yeni sürümle yenilendi
    ozet = sd.panel_ozeti(state)
    assert any("Europe/Istanbul" in x for x in ozet["degisiklikler"][0]["lines"])
    assert ozet["farklar"]["Europe/Istanbul"]["eski"] == 7200 and ozet["farklar"]["Europe/Istanbul"]["yeni"] == 10800
    assert ozet["farklar"]["America/Asuncion"]["eski"] is None and ozet["farklar"]["America/Asuncion"]["yeni"] == -10800
    assert not any(x.startswith("Kaynak:") or x.startswith("[SAAT") for x in ozet["degisiklikler"][0]["lines"])
    # Gönderilemezse sonraki turda yeniden denenir; gönderilince bir daha gelmez
    assert [x.key for x in sd.kontrol(cfg, store, state, sent, NOW)[0]] == [m.key]
    sent[m.key] = "x"
    assert sd.kontrol(cfg, store, state, sent, NOW)[0] == []


def test_dst_date_change_reported(ortam, snap):
    cfg, store, state, sent = ortam
    berlin = [list(x) for x in snap["zones"]["Europe/Berlin"]["t"]]
    berlin[1][0] = "2027-04-04T01:00+00:00"  # eski kurala göre yaz saati bir hafta sonra başlayacaktı
    store.write(sd.DOSYA, eski_surum(snap, **{"Europe/Berlin": berlin}))
    msgs, _, _ = sd.kontrol(cfg, store, state, sent, NOW)
    line = next(x for x in msgs[0].plain.splitlines() if "Europe/Berlin" in x)
    assert "28 Mart 2027 03:00 itibarıyla UTC+02:00 (yaz saati); eski kurala göre UTC+01:00 olacaktı." in line


def test_no_change_on_new_version(ortam, snap):
    cfg, store, state, sent = ortam
    sent["saatdilimi:kurulum"] = "x"
    store.write(sd.DOSYA, eski_surum(snap))
    msgs, notes, written = sd.kontrol(cfg, store, state, sent, NOW)
    assert msgs == [] and written and "değişiklik yok" in notes[0]


def test_older_package_does_nothing(ortam, snap):
    cfg, store, state, sent = ortam
    s = eski_surum(snap, **{"Europe/Istanbul": [[snap["start"], 7200, False]]})
    s["tzdata"] = "2999.1"  # örn. GitHub'da daha yeni paket çalışmış, yerelde eski paket var
    store.write(sd.DOSYA, s)
    msgs, notes, written = sd.kontrol(cfg, store, state, sent, NOW)
    assert msgs == [] and not written and notes == []


def test_disabled(cfg):
    cfg.settings.tz_watch = False
    assert sd.kontrol(cfg, Store(cfg.data_dir), {}, {}, NOW) == ([], [], False)


def test_utc_format():
    assert sd.utc(10800) == "UTC+03:00" and sd.utc(-12600) == "UTC-03:30" and sd.utc(0) == "UTC+00:00"
