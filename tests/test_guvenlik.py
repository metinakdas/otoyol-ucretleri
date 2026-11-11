"""Güvenlik: anahtar maskeleme, güvenli bağlantılar, yerel sunucu ve GitHub'a yayın betiği.

Yayın testi gerçek git ile yerel bir "uzak depo"ya gönderir; GitHub CLI (gh) sahte bir betikle taklit edilir.
İnternete çıkılmaz.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from conftest import ROOT
from radar import guvenlik, yayin
from radar.extract import extract_links
from radar.messages import _link
from radar.panel import _PanelHandler

FAKE_TOKEN = "123456789:" + "AAH" + "x" * 32          # biçimi gerçek bir bot anahtarına benzer
FAKE_CHAT = "-1001234567890"
FAKE_PASSWORD = "cok-gizli-sifre-123"  # test için uydurma değer  # pragma: allowlist secret


# ------------------------------------------------------------------ maskeleme ve bağlantılar

def test_anahtarlar_hata_metninde_maskelenir(cfg):
    cfg.settings.telegram_token = FAKE_TOKEN
    cfg.settings.smtp_password = FAKE_PASSWORD
    msg = f"Client error for url https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage; pass={FAKE_PASSWORD}"
    out = guvenlik.redact(msg, cfg.settings)
    assert FAKE_TOKEN not in out and FAKE_PASSWORD not in out and "***" in out
    # ayarlarda olmasa bile bilinen anahtar biçimi maskelenir
    assert FAKE_TOKEN not in guvenlik.redact(f"token {FAKE_TOKEN}")


def test_yalnizca_http_baglantilari_kullanilir():
    html = """<a href="JavaScript:alert(1)">Köprü ücretleri değişti, ayrıntılar burada</a>
              <a href=" data:text/html,x">Ücretsiz geçiş duyurusu hakkında bilgi</a>
              <a href="/haber/1">Bayramda köprü ve otoyollar ücretsiz olacak</a>"""
    links = extract_links(html, "https://www.uab.gov.tr/haberler/")
    assert [l.url for l in links] == ["https://www.uab.gov.tr/haber/1"]
    assert guvenlik.safe_url("javascript:alert(1)") is None
    assert guvenlik.safe_url("https://www.kgm.gov.tr/x.pdf") == "https://www.kgm.gov.tr/x.pdf"
    assert _link("javascript:alert(1)", "kaynak") == "kaynak"
    assert _link("https://www.kgm.gov.tr/", "kaynak").startswith('<a href="https://www.kgm.gov.tr/"')


def test_telegram_baglanti_hatasi_anahtari_ifsa_etmez(cfg):
    from radar.notify import send_telegram

    cfg.settings.telegram_token = FAKE_TOKEN

    def boom(request):
        raise httpx.ConnectError(f"bağlanamadı: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(RuntimeError) as err:
        send_telegram(cfg, FAKE_CHAT, "deneme", client)
    assert FAKE_TOKEN not in str(err.value)


def test_eposta_sertifikayi_dogrular(cfg, monkeypatch):
    from radar import notify

    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30, context=None):
            seen["init_context"] = context

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            seen["starttls_context"] = context

        def login(self, *a):
            pass

        def send_message(self, m):
            seen["sent"] = True

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    s = cfg.settings
    s.smtp_host, s.smtp_user, s.smtp_password, s.email_to, s.smtp_ssl = "smtp.ornek.com", "u", "p", ["a@ornek.com"], False
    notify.send_email(cfg, "konu", "metin")
    ctx = seen["starttls_context"]
    assert ctx is not None and ctx.verify_mode.name == "CERT_REQUIRED" and ctx.check_hostname


# ------------------------------------------------------------------ yerel panel sunucusu

@pytest.fixture
def local_server(tmp_path):
    (tmp_path / "panel" / "vendor").mkdir(parents=True)
    (tmp_path / "panel" / "index.html").write_text("<h1>panel</h1>", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "panel.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "state.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text(f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\n", encoding="utf-8")
    handler = functools.partial(_PanelHandler, directory=str(tmp_path))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_yerel_sunucu_yalnizca_paneli_verir(local_server):
    with httpx.Client(base_url=local_server, follow_redirects=False) as c:
        assert c.get("/panel/index.html").status_code == 200
        assert c.get("/panel/").text == "<h1>panel</h1>"
        assert c.get("/data/panel.json").status_code == 200
        assert c.get("/").status_code == 302
        for path in ("/.env", "/data/state.json", "/panel/../.env", "/panel/%2e%2e/.env", "/panel/vendor/", "/data/"):
            r = c.get(path)
            assert r.status_code == 404 and FAKE_TOKEN not in r.text, path
        r = c.get("/panel/index.html", headers={"Host": "saldirgan.example"})
        assert r.status_code == 403
        assert c.get("/panel/index.html").headers["X-Content-Type-Options"] == "nosniff"


# ------------------------------------------------------------------ yayın öncesi tarama

def test_tarama_gizli_ve_kisisel_bilgiyi_bulur(tmp_path):
    (tmp_path / "a.md").write_text(f"bot anahtarı: {FAKE_TOKEN}\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(f"CHAT = '{FAKE_CHAT}'\n", encoding="utf-8")
    profile = "C:" + "\\Users\\ornekkisi"   # kaynakta bitişik yazılmaz; bu dosya da taranıyor
    (tmp_path / "c.txt").write_text(f"yol: {profile}\\Desktop\\otoyol\n", encoding="utf-8")
    (tmp_path / "d.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    env = {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "TELEGRAM_CHAT_ID": FAKE_CHAT}
    terms = yayin.scan_terms(env, {profile: "kişisel klasör yolu"})
    found = yayin.scan_files(tmp_path, ["a.md", "b.py", "c.txt", "d.json", ".env"], terms)
    text = "\n".join(map(str, found))
    assert "a.md:1 · .env değeri (TELEGRAM_BOT_TOKEN)" in text and "a.md:1 · Telegram bot anahtarı" in text
    assert "b.py:1 · .env değeri (TELEGRAM_CHAT_ID)" in text
    assert "c.txt:1 · kişisel klasör yolu" in text
    assert ".env · gizli ayar dosyası" in text
    assert "d.json" not in text
    assert FAKE_TOKEN not in text  # bulgu satırları değerin kendisini göstermez


def test_proje_dosyalarinda_gizli_bilgi_yok():
    proc = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
                          capture_output=True, text=True)
    if proc.returncode != 0:  # proje henüz git deposu değil: tüm dosyalar
        files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*")
                 if p.is_file() and not any(x in p.parts for x in (".git", "__pycache__", ".pytest_cache", ".venv"))
                 and p.name != ".env"]
    else:
        files = [f for f in proc.stdout.split("\0") if f]
    found = yayin.scan_files(ROOT, files, yayin.scan_terms({}, {}))
    assert not found, "\n".join(map(str, found))


# ------------------------------------------------------------------ yayın betiği (sahte gh ile)

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
log = os.environ["SAHTE_GH_LOG"]
args = sys.argv[1:]
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
if args[:2] == ["auth", "status"]:
    print("github.com\n  ✓ Logged in\n  - Token scopes: " + os.environ.get("SAHTE_GH_SCOPES", "'repo', 'workflow'"))
elif args[:2] == ["api", "-X"] and args[3] == "user":
    print(json.dumps({"login": "OrnekKullanici", "id": 4242}))
elif args[:2] == ["repo", "create"]:
    subprocess.run(["git", "remote", "add", "origin", os.environ["SAHTE_UZAK"]], check=True)
elif args[:2] == ["api", "-X"] and args[2] == "GET" and args[3].endswith("/rulesets"):
    print("[]")
elif args[:1] == ["api"]:
    print("{}")
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    if os.name == "nt" or not shutil.which("git"):
        pytest.skip("sahte gh betiği yalnızca Linux/macOS'ta çalışır")
    root = tmp_path / "otoyol"
    (root / ".github" / "workflows").mkdir(parents=True)
    for rel in yayin.WORKFLOWS:
        shutil.copy(ROOT / rel, root / rel)
    shutil.copy(ROOT / ".gitignore", root / ".gitignore")
    (root / "README.md").write_text("# Tarife Radarı\n", encoding="utf-8")
    (root / "radar").mkdir()
    (root / "radar" / "__init__.py").write_text("", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "not.txt").write_text(FAKE_TOKEN, encoding="utf-8")  # .gitignore dışarıda bırakır
    (root / ".env").write_text(
        f"TELEGRAM_BOT_TOKEN={FAKE_TOKEN}\nTELEGRAM_CHAT_ID={FAKE_CHAT}\nSMTP_PASSWORD=\nEMAIL_TO=\n", encoding="utf-8")
    bare = tmp_path / "uzak.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SAHTE_GH_LOG", str(log))
    monkeypatch.setenv("SAHTE_UZAK", str(bare))
    monkeypatch.setenv("HOME", str(tmp_path / "ev"))   # kişisel git ayarları teste karışmasın
    monkeypatch.setattr(yayin.time, "sleep", lambda s: None)
    calls = lambda: [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return root, bare, calls


def test_yayin_guvenli_akis(project, capsys):
    root, bare, calls = project
    assert yayin.yayinla(root) == 0
    output = capsys.readouterr().out
    assert FAKE_TOKEN not in output and FAKE_CHAT not in output

    # Uzak depoda .env ve .venv yok; commit yazarı GitHub'ın gizli adresi
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"], cwd=bare, capture_output=True, text=True).stdout
    assert ".github/workflows/radar.yml" in files and "README.md" in files
    assert ".env" not in files.split() and ".venv/" not in files
    author = subprocess.run(["git", "log", "-1", "--format=%an <%ae>", "main"], cwd=bare, capture_output=True, text=True).stdout
    assert author.strip() == "OrnekKullanici <4242+OrnekKullanici@users.noreply.github.com>"

    log = calls()
    # Anahtarlar komut satırında değil, standart girdide
    assert not any(FAKE_TOKEN in " ".join(c["args"]) or FAKE_CHAT in " ".join(c["args"]) for c in log)
    secrets = {c["args"][2]: c["stdin"] for c in log if c["args"][:2] == ["secret", "set"]}
    assert secrets == {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "TELEGRAM_CHAT_ID": FAKE_CHAT}
    create = next(c["args"] for c in log if c["args"][:2] == ["repo", "create"])
    assert "--public" in create and "--disable-issues" in create and "--disable-wiki" in create
    api = [(c["args"][2], c["args"][3], c["stdin"]) for c in log if c["args"][:1] == ["api"]]
    paths = [p for _, p, _ in api]
    full = "repos/OrnekKullanici/otoyol-ucretleri"
    for expected in (f"{full}/interaction-limits", f"{full}/actions/permissions/workflow", f"{full}/pages",
                     f"{full}/vulnerability-alerts", f"{full}/rulesets", f"{full}/actions/permissions/selected-actions"):
        assert expected in paths, expected
    limits = next(json.loads(b) for m, p, b in api if p.endswith("/interaction-limits"))
    assert limits == {"limit": "collaborators_only", "expiry": "six_months"}
    perms = next(json.loads(b) for m, p, b in api if p.endswith("/actions/permissions/workflow"))
    assert perms["default_workflow_permissions"] == "read"
    variable = next(c["args"] for c in log if c["args"][:2] == ["variable", "set"])
    assert "https://ornekkullanici.github.io/otoyol-ucretleri/" in variable
    assert any(c["args"][:2] == ["workflow", "run"] for c in log)


def test_yayin_gizli_bilgi_bulursa_hicbir_sey_gondermez(project):
    root, bare, calls = project
    (root / "README.md").write_text(f"# Tarife Radarı\nanahtar: {FAKE_TOKEN}\n", encoding="utf-8")
    with pytest.raises(yayin.YayinHatasi) as err:
        yayin.yayinla(root)
    assert "README.md:2" in str(err.value) and FAKE_TOKEN not in str(err.value)
    assert not any(c["args"][:2] in (["repo", "create"], ["secret", "set"]) for c in calls())
    assert subprocess.run(["git", "rev-parse", "--verify", "main"], cwd=bare, capture_output=True).returncode != 0


def test_yayin_eksik_is_akisi_ve_izin(project, monkeypatch):
    root, _, _ = project
    monkeypatch.setenv("SAHTE_GH_SCOPES", "'gist', 'read:org', 'repo'")
    with pytest.raises(yayin.YayinHatasi, match="workflow"):
        yayin.yayinla(root)
    monkeypatch.setenv("SAHTE_GH_SCOPES", "'repo', 'workflow'")
    (root / ".github" / "workflows" / "radar.yml").unlink()
    with pytest.raises(yayin.YayinHatasi, match="radar.yml yok"):
        yayin.yayinla(root)


def test_yayin_deneme_modu_gondermez(project, capsys):
    root, bare, calls = project
    assert yayin.yayinla(root, dry_run=True) == 0
    assert "Deneme modu" in capsys.readouterr().out
    assert not any(c["args"][:2] in (["repo", "create"], ["secret", "set"]) for c in calls())
