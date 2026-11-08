from radar.matching import KIND_FREE, KIND_PRICE, Matcher


def matcher(cfg):
    return Matcher(cfg.crossings, cfg.generic_phrases)


def test_aliases(cfg):
    m = matcher(cfg)
    assert m.find_crossings("Boğaziçi Köprüsü'nde yeni dönem") == ["15-temmuz-sehitler"]
    assert m.find_crossings("3. Köprü ve Avrasya Tüneli") == ["yavuz-sultan-selim", "avrasya-tuneli"]
    assert m.find_crossings("1915 Çanakkale Köprüsü") == ["1915-canakkale"]
    # Bölüm adı geçiş adı değildir
    assert m.find_crossings("Kuzey Marmara bölgesinde yağış") == []


def test_classify_free_passage(cfg):
    c = matcher(cfg).classify("Kurban Bayramı'nda köprü ve otoyollar ücretsiz olacak")
    assert c.kind == KIND_FREE and c.generic and not c.cancel


def test_classify_price(cfg):
    c = matcher(cfg).classify("Avrasya Tüneli geçiş ücretlerine zam")
    assert c.kind == KIND_PRICE and c.crossings == ["avrasya-tuneli"]


def test_classify_ignores_unrelated(cfg):
    m = matcher(cfg)
    assert m.classify("Bayramda toplu taşıma ücretsiz") is None  # köprü/otoyol yok
    assert m.classify("Köprü ve otoyollarda bakım çalışması") is None  # ücret yok
    assert m.classify("Köprü ve otoyollarda geçiş ücreti ödemeyenlere ceza") is None  # ceza haberi


def test_classify_with_source_default(cfg):
    c = matcher(cfg).classify("Yeni ücret tarifesi açıklandı", default_crossings=["avrasya-tuneli"])
    assert c.kind == KIND_PRICE


def test_cancel_in_title(cfg):
    c = matcher(cfg).classify("Köprü ve otoyol zammı ertelendi")
    assert c.cancel and c.kind == KIND_PRICE


def test_excluded_yid(cfg):
    text = ("Bayram boyunca KGM'nin işlettiği köprü ve otoyollar ücretsiz olacak. "
            "Yap-işlet-devret modeliyle yapılan Yavuz Sultan Selim Köprüsü ve Osmangazi Köprüsü'nde uygulanmayacak.")
    excluded = matcher(cfg).find_excluded(text)
    for cid in ("yavuz-sultan-selim", "osmangazi", "1915-canakkale", "avrasya-tuneli"):
        assert cid in excluded
    assert "15-temmuz-sehitler" not in excluded


def test_document_mapping(cfg):
    m = matcher(cfg)
    ids = lambda text, url: [c.id for c in m.crossings_for_document(text, url)]
    base = "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/2026Gecis_Ucret/"
    assert ids("1- 15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri Geçiş Ücretleri Tarifesi", base + "1-15Temmuz-FSM.pdf") == [
        "15-temmuz-sehitler", "fatih-sultan-mehmet"]
    assert ids("3- Yavuz Sultan Selim Köprüsü", base + "3-YSSKoprusu.pdf") == ["yavuz-sultan-selim"]
    assert ids("13- Yavuz Sultan Selim Köprüsü ve Kuzey Çevre Otoyolu", base + "13-YSSKuzeyCevreYolu.pdf") == []
    assert ids("12- Gebze-Orhangazi-İzmir Otoyolu", base + "12-Gebze-Orhangazi-Izmir.pdf") == []
    assert ids("4- 1915 Çanakkale Köprüsü", base + "4-1915Canakkale.pdf") == ["1915-canakkale"]
    assert ids("18- Malkara-Çanakkale Otoyolu", base + "18-Malkara-Canakkale.pdf") == []
