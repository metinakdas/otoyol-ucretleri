"""GitHub'a güvenli yayın: python -m radar yayinla

Bu komut sizin bilgisayarınızda, sizin GitHub girişinizle (GitHub CLI, "gh") çalışır:

1. Ön kontroller: git ve gh kurulu mu, GitHub'a giriş yapılmış mı, iş akışı dosyaları yerinde mi.
2. Yayın öncesi güvenlik taraması: depoya girecek her dosya, .env'deki anahtar/şifre değerleri, bilinen
   anahtar biçimleri (Telegram, GitHub, özel anahtar…) ve kişisel klasör yolunuz için taranır.
   Tek bir bulgu varsa hiçbir şey gönderilmez.
3. Commit kişisel e-postanızla değil, GitHub'ın gizli "noreply" adresiyle yapılır.
4. Depo oluşturulur ve gönderilir; anahtarlar .env'den okunup doğrudan GitHub Secrets'a (şifreli) yazılır.
   Değerler ekrana, dosyaya ya da komut satırına hiçbir zaman yazılmaz.
5. Depo sıkılaştırılır: issue/wiki kapalı, yabancıların yorum/PR açması kısıtlı, Actions en az yetkiyle,
   gizli bilgi taraması ve gönderim koruması açık, ana dal silinemez ve geçmişi değiştirilemez.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 - yalnızca git ve gh, kabuk olmadan liste argümanlarla
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .guvenlik import SECRET_PATTERNS, redact

SECRET_KEYS = (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_TECH_CHAT_ID",
    "SMTP_HOST", "SMTP_PORT", "SMTP_SSL", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "EMAIL_TO",
)
# Depoda aranacak değerler (bunlar asla dosyalarda geçmemeli)
SCAN_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_TECH_CHAT_ID",
             "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "EMAIL_TO")
# İş akışı dosyaları ve güncel sürümde bulunması gereken ifade
WORKFLOWS = {
    ".github/workflows/radar.yml": "Bildirim ayarlarını denetle",
    ".github/workflows/testler.yml": "persist-credentials: false",
}
# Kişisel bilgi biçimleri: Windows kullanıcı klasörü yolları (sürücü harfi + Users + kullanıcı adı)
PERSONAL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("kişisel klasör yolu", re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|<)[^\\/\s\"'`<>]+", re.I)),
]
BINARY_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".zip"}
MAX_FILE_BYTES = 5_000_000
RULESET_NAME = "ana-dal-koruma"


class YayinHatasi(Exception):
    pass


@dataclass
class Bulgu:
    path: str
    line: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}{':' + str(self.line) if self.line else ''} · {self.kind}"


# ------------------------------------------------------------------ yardımcılar

def read_env(path: Path) -> dict[str, str]:
    """.env dosyasını okur; ortam değişkenlerine dokunmaz."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def channel_ready(env: dict[str, str]) -> bool:
    telegram = env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")
    email = env.get("SMTP_HOST") and env.get("EMAIL_TO")
    return bool(telegram or email)


def scan_terms(env: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, str]:
    """Taranacak değer → açıklama. Değerin kendisi hiçbir zaman ekrana yazılmaz."""
    terms: dict[str, str] = {}
    for key in SCAN_KEYS:
        for part in (env.get(key) or "").split(","):
            part = part.strip()
            if len(part) >= 5:
                terms[part] = f".env değeri ({key})"
    for value, label in (extra or {}).items():
        if value and len(value) >= 5:
            terms.setdefault(value, label)
    return terms


def scan_files(root: Path, files: list[str], terms: dict[str, str]) -> list[Bulgu]:
    """Depoya girecek dosyaları gizli bilgi için tarar."""
    found: list[Bulgu] = []
    lowered = {t.lower(): label for t, label in terms.items()}
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            found.append(Bulgu(rel, 0, "gizli ayar dosyası depoya giriyor (.gitignore'a eklenmeli)"))
            continue
        path = root / rel
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            found.append(Bulgu(rel, 0, f"beklenmeyen büyük dosya ({size // 1_000_000} MB)"))
            continue
        data = path.read_bytes()
        if path.suffix.lower() in BINARY_EXT or b"\x00" in data[:4096]:
            low = data.lower()
            for term, label in lowered.items():
                if term.encode("utf-8") in low:
                    found.append(Bulgu(rel, 0, label))
            continue
        text = data.decode("utf-8", errors="replace")
        for no, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for term, label in lowered.items():
                if term in low:
                    found.append(Bulgu(rel, no, label))
            for label, pattern in SECRET_PATTERNS + PERSONAL_PATTERNS:
                if pattern.search(line):
                    found.append(Bulgu(rel, no, label))
    return found


def personal_terms(git_email: str | None) -> dict[str, str]:
    """Kişisel bilgiler: kullanıcı klasörünüzün yolu (adınızı içerir) ve kişisel git e-postanız."""
    terms: dict[str, str] = {}
    home = str(Path.home())
    if home and home not in ("/", "/root") and len(home) >= 8:
        terms[home] = "kişisel klasör yolu"
        terms[home.replace("\\", "/")] = "kişisel klasör yolu"
        terms[home.replace("\\", "\\\\")] = "kişisel klasör yolu"
    if git_email and "noreply" not in git_email:
        terms[git_email] = "kişisel e-posta adresi"
    return terms


def parse_remote(url: str) -> str | None:
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


# ------------------------------------------------------------------ komut çalıştırma

class Runner:
    def __init__(self, root: Path, out=print):
        self.root = root
        self.out = out
        self.git = shutil.which("git")
        self.gh = shutil.which("gh")

    def run(self, tool: str, *args: str, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        exe = self.git if tool == "git" else self.gh
        if not exe:
            raise YayinHatasi(f"{tool} bulunamadı")
        # Alt programlara anahtarlar ortam değişkeni olarak da geçmez
        env = {k: v for k, v in os.environ.items() if k not in SECRET_KEYS}
        env.update(GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0", NO_COLOR="1")
        # Girdi verilmeyen komutlar terminali beklemesin diye standart girdi boş bağlanır
        stdin_args = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        proc = subprocess.run(  # nosec B603 - program yolu which ile bulunur, kabuk kullanılmaz
            [exe, *args], cwd=self.root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=env, **stdin_args,
        )
        if check and proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise YayinHatasi(f"{tool} {' '.join(args[:2])} başarısız: {redact(msg)[:400]}")
        return proc

    def api(self, method: str, path: str, body=None) -> tuple[bool, object]:
        args = ["api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
        if body is not None:
            args += ["--input", "-"]
        proc = self.run("gh", *args, input=json.dumps(body) if body is not None else None, check=False)
        text = (proc.stdout or "").strip()
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = text
        if proc.returncode != 0:
            message = data.get("message") if isinstance(data, dict) else None
            return False, redact(message or (proc.stderr or text).strip())[:300]
        return True, data


# ------------------------------------------------------------------ adımlar

def check_prerequisites(r: Runner) -> None:
    missing = [name for name, exe in (("git", r.git), ("gh", r.gh)) if not exe]
    if missing:
        raise YayinHatasi(
            "Gerekli programlar kurulu değil: " + ", ".join(missing) + ".\n"
            "  Kurmak için (Windows):\n"
            "    winget install --id Git.Git -e\n"
            "    winget install --id GitHub.cli -e\n"
            "  Kurduktan sonra yeni bir terminal açın.")
    status = r.run("gh", "auth", "status", "--hostname", "github.com", check=False)
    text = (status.stdout or "") + (status.stderr or "")
    if status.returncode != 0:
        raise YayinHatasi(
            "GitHub'a giriş yapılmamış. Şunu çalıştırıp tarayıcıda onaylayın:\n"
            "    gh auth login --hostname github.com --git-protocol https --web --scopes workflow")
    scopes_line = next((line for line in text.splitlines() if "scopes" in line.lower()), "")
    if scopes_line and "workflow" not in scopes_line:
        raise YayinHatasi(
            "GitHub girişinde 'workflow' izni yok (iş akışı dosyalarını göndermek için gerekli). Şunu çalıştırın:\n"
            "    gh auth refresh --hostname github.com --scopes workflow")


def check_workflows(root: Path) -> None:
    problems = []
    for rel, marker in WORKFLOWS.items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel} yok")
        elif marker not in path.read_text(encoding="utf-8"):
            problems.append(f"{rel} eski sürüm")
    if problems:
        raise YayinHatasi(
            "İş akışı dosyaları eksik ya da eski: " + "; ".join(problems) + ".\n"
            "  radar.yml ve testler.yml dosyalarının güncel sürümleri .github\\workflows\\ içinde olmalı.")


def publish_files(r: Runner) -> list[str]:
    proc = r.run("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted(f for f in proc.stdout.split("\0") if f)


def security_scan(r: Runner, env: dict[str, str]) -> list[str]:
    if not (r.root / ".git").exists():
        r.run("git", "init", "-b", "main")
    ignored = r.run("git", "check-ignore", "-q", ".env", check=False)
    if ignored.returncode != 0:
        raise YayinHatasi(".env dosyası .gitignore ile dışarıda bırakılmıyor; anahtarlar depoya girebilir. Durduruldu.")
    files = publish_files(r)
    git_email = r.run("git", "config", "--global", "user.email", check=False).stdout.strip() or None
    findings = scan_files(r.root, files, scan_terms(env, personal_terms(git_email)))
    if findings:
        lines = "\n".join(f"    {f}" for f in findings[:30])
        raise YayinHatasi(
            "Güvenlik taraması gizli ya da kişisel bilgi buldu; hiçbir şey gönderilmedi:\n" + lines +
            "\n  Bu satırları düzeltin (ya da dosyayı silin) ve komutu yeniden çalıştırın.")
    return files


def github_identity(r: Runner) -> tuple[str, str]:
    ok, data = r.api("GET", "user")
    if not ok or not isinstance(data, dict) or "login" not in data:
        raise YayinHatasi(f"GitHub kullanıcı bilgisi alınamadı: {data}")
    login, uid = data["login"], data["id"]
    return login, f"{uid}+{login}@users.noreply.github.com"


def harden(r: Runner, full: str, public: bool, out) -> None:
    """Depo ayarlarını sıkılaştırır. Her adım ayrı denenir; biri başarısız olursa diğerleri sürer."""
    def step(label: str, method: str, path: str, body=None) -> bool:
        ok, info = r.api(method, f"repos/{full}{path}", body)
        out(f"  {'✓' if ok else '⚠'} {label}" + ("" if ok else f" (yapılamadı: {info})"))
        return ok

    repo_body = {"has_issues": False, "has_wiki": False, "has_projects": False, "has_discussions": False}
    step("Issue, wiki, proje ve tartışma bölümleri kapatıldı", "PATCH", "", repo_body)
    if public:
        step("Gizli bilgi taraması ve gönderim koruması açıldı", "PATCH", "", {"security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }})
    step("Actions varsayılan yetkisi: yalnızca okuma", "PUT", "/actions/permissions/workflow",
         {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False})
    if step("Actions yalnızca GitHub'ın kendi eylemlerini çalıştırabilir", "PUT", "/actions/permissions",
            {"enabled": True, "allowed_actions": "selected"}):
        r.api("PUT", f"repos/{full}/actions/permissions/selected-actions",
              {"github_owned_allowed": True, "verified_allowed": False, "patterns_allowed": []})
    step("Bağımlılık güvenlik uyarıları açıldı", "PUT", "/vulnerability-alerts")
    step("Güvenlik düzeltmeleri otomatik önerilecek", "PUT", "/automated-security-fixes")
    if public:
        until = (date.today() + timedelta(days=182)).strftime("%d.%m.%Y")
        step(f"Yabancıların issue, yorum ve PR açması kapatıldı ({until} tarihine kadar; "
             "süre dolunca 'python -m radar yayinla --yalnizca-ayarlar' ile yenileyin)",
             "PUT", "/interaction-limits", {"limit": "collaborators_only", "expiry": "six_months"})
    ok, rules = r.api("GET", f"repos/{full}/rulesets")
    if ok and isinstance(rules, list) and any(x.get("name") == RULESET_NAME for x in rules):
        out("  ✓ Ana dal koruması zaten açık")
    else:
        step("Ana dal silinemez ve geçmişi değiştirilemez", "POST", "/rulesets", {
            "name": RULESET_NAME, "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
        })


def set_secrets(r: Runner, full: str, env: dict[str, str], out) -> int:
    count = 0
    for key in SECRET_KEYS:
        value = env.get(key, "")
        if not value:
            continue
        # Değer komut satırına değil, standart girdiye verilir; ekrana ve dosyaya yazılmaz.
        r.run("gh", "secret", "set", key, "--repo", full, input=value)
        out(f"  ✓ {key} şifreli olarak kaydedildi")
        count += 1
    return count


def enable_pages(r: Runner, full: str) -> tuple[bool, str]:
    ok, info = r.api("POST", f"repos/{full}/pages", {"build_type": "workflow"})
    if not ok:
        ok, info = r.api("PUT", f"repos/{full}/pages", {"build_type": "workflow"})
    return ok, str(info)


# ------------------------------------------------------------------ ana akış

def yayinla(root: Path, *, repo_name: str = "otoyol-ucretleri", public: bool = True, dry_run: bool = False,
            settings_only: bool = False, out=print) -> int:
    root = Path(root).resolve()
    r = Runner(root, out)
    env = read_env(root / ".env")
    out("Tarife Radarı · GitHub'a güvenli yayın\n")

    check_prerequisites(r)
    out("✓ git ve GitHub CLI hazır, GitHub girişi yapılmış")
    check_workflows(root)
    out("✓ İş akışı dosyaları yerinde ve güncel")

    files = security_scan(r, env)
    out(f"✓ Güvenlik taraması: depoya girecek {len(files)} dosya tarandı, gizli ya da kişisel bilgi yok "
        "(.env depo dışında)")

    login, noreply = github_identity(r)
    remote = r.run("git", "remote", "get-url", "origin", check=False)
    full = parse_remote(remote.stdout) if remote.returncode == 0 else None
    full = full or f"{login}/{repo_name}"
    visibility = "herkese açık" if public else "gizli"
    out(f"✓ GitHub hesabı: {login} · depo: {full} ({visibility})")

    if dry_run:
        out("\nDeneme modu: hiçbir şey gönderilmedi. Yapılacaklar:")
        out(f"  - commit (yazar: {login} <{noreply}>), depo oluşturma ve gönderme")
        out("  - .env'deki anahtarları GitHub Secrets'a yazma: " +
            (", ".join(k for k in SECRET_KEYS if env.get(k)) or "(.env'de değer yok)"))
        out("  - Pages, depo sıkılaştırma ve ilk radar turu")
        return 0

    if not settings_only:
        # Kişisel e-posta yerine GitHub'ın gizli adresi (yalnızca bu depo için)
        r.run("git", "config", "user.name", login)
        r.run("git", "config", "user.email", noreply)
        r.run("git", "add", "-A")
        staged = r.run("git", "diff", "--cached", "--quiet", check=False).returncode != 0
        has_commit = r.run("git", "rev-parse", "--verify", "HEAD", check=False).returncode == 0
        if staged:
            title = "Tarife Radarı: güncelleme" if has_commit else "Tarife Radarı: ilk yayın"
            r.run("git", "commit", "-q", "-m", title)
            out(f"✓ Commit oluşturuldu (yazar: {login}, e-posta: GitHub'ın gizli adresi)")
        r.run("git", "branch", "-M", "main")
        if remote.returncode != 0:
            r.run("gh", "repo", "create", full, "--public" if public else "--private", "--source", ".",
                  "--remote", "origin", "--disable-wiki", "--disable-issues",
                  "--description", "Köprü ve otoyol geçiş ücreti değişikliklerini izleyen radar")
            out(f"✓ Depo oluşturuldu: https://github.com/{full}")
        r.run("gh", "auth", "setup-git", "--hostname", "github.com", check=False)
        r.run("git", "push", "-u", "origin", "main")
        out("✓ Dosyalar gönderildi")

    out("\nAnahtarlar (GitHub Secrets):")
    n_secrets = set_secrets(r, full, env, out)
    if not n_secrets:
        out("  ⚠ .env'de anahtar yok. Telegram/e-posta bilgilerini .env'ye yazıp komutu\n"
            "    'python -m radar yayinla --yalnizca-ayarlar' ile yeniden çalıştırın.")

    owner, name = full.split("/", 1)
    panel_url = f"https://{owner.lower()}.github.io/{name}/"
    if public:
        r.run("gh", "variable", "set", "PANEL_URL", "--body", panel_url, "--repo", full)
        ok, info = enable_pages(r, full)
        out(f"  {'✓' if ok else '⚠'} GitHub Pages: {panel_url}" + ("" if ok else f" (açılamadı: {info})"))

    out("\nDepo güvenliği:")
    harden(r, full, public, out)

    out("")
    if channel_ready(env):
        started = False
        for attempt in range(4):  # yeni depoda iş akışlarının tanınması birkaç saniye sürebilir
            if r.run("gh", "workflow", "run", "radar.yml", "--repo", full, check=False).returncode == 0:
                started = True
                break
            time.sleep(5 * (attempt + 1))
        out("✓ İlk radar turu başlatıldı" if started else
            "⚠ İlk tur başlatılamadı; Actions sekmesinden 'Tarife Radarı' → Run workflow ile başlatın")
    else:
        out("⚠ Bildirim kanalı (Telegram ya da e-posta) tanımlı değil; radar ayarlar girilene kadar çalışmaz.")

    out(f"\nDepo: https://github.com/{full}")
    out(f"Çalışmalar: https://github.com/{full}/actions")
    if public:
        out(f"Panel: {panel_url} (ilk tur bitince birkaç dakika içinde açılır)")
    else:
        out("Not: gizli depoda ücretsiz dakika sınırı için radar.yml'de zamanlamayı saatlik yapın: cron: \"0 * * * *\"")
    return 0


def main(args) -> int:
    from .config import ROOT

    try:
        return yayinla(ROOT, repo_name=args.depo, public=not args.gizli, dry_run=args.deneme,
                       settings_only=args.yalnizca_ayarlar)
    except YayinHatasi as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 1
