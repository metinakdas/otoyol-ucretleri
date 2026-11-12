"""WhatsApp kanalı (Meta Cloud API). İnternete çıkılmaz; istekler sahte yanıtlarla karşılanır."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from radar.notify import Message, deliver, one_line, send_whatsapp
from radar.timeutil import TZ

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)
TOKEN = "EAA" + "x" * 80


class Net:
    """Telegram ve WhatsApp isteklerini kaydeder; istenen servisi hata verdirebilir."""

    def __init__(self, fail: set[str] | None = None):
        self.reqs: list[httpx.Request] = []
        self.fail = fail or set()
        self.client = httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.reqs.append(request)
        host = request.url.host
        if "telegram" in host:
            return httpx.Response(500 if "telegram" in self.fail else 200, json={"ok": "telegram" not in self.fail})
        if "facebook" in host:
            if "meta" in self.fail:
                return httpx.Response(400, json={"error": {"message": f"bad token {TOKEN}"}})
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
        return httpx.Response(404)

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.reqs]


@pytest.fixture
def meta(cfg):
    s = cfg.settings
    s.wa_token, s.wa_phone_id, s.wa_to = TOKEN, "1234567890", ["905551112233", "905554445566"]
    s.wa_template, s.wa_template_lang = "radar_bildirim", "tr"
    return cfg


def msg(key="olay:karar", channels=("telegram", "email")):
    return Message(key=key, channels=channels, subject="[KARAR ÇIKTI] Köprü",
                   html="<b>KARAR</b>", plain="[KARAR ÇIKTI] Köprü\n\nYürürlük:   1 Ocak\thttps://ornek")


def test_not_configured(cfg):
    assert not cfg.settings.whatsapp_ready
    net, sent = Net(), {}
    deliver(cfg, [msg()], sent, NOW, client=net.client)
    assert net.hosts() == ["api.telegram.org"]
    assert not any("#wa" in k for k in sent)


def test_copy_of_telegram_to_every_recipient(meta):
    net, sent = Net(), {}
    lines = deliver(meta, [msg()], sent, NOW, client=net.client)
    assert sorted(net.hosts()) == ["api.telegram.org", "graph.facebook.com", "graph.facebook.com"]
    assert [json.loads(r.content)["to"] for r in net.reqs if "facebook" in r.url.host] == ["905551112233", "905554445566"]
    assert {"olay:karar", "olay:karar#wa1", "olay:karar#wa2"} <= set(sent)
    assert not any("905551112233" in k for k in sent)  # numara data/ klasörüne yazılmaz
    assert sum("WhatsApp'a gönderildi" in x for x in lines) == 2


def test_tech_and_email_only_not_copied(meta):
    net, sent = Net(), {}
    deliver(meta, [msg("kaynak:x", ("tech",)), msg("ozet:1", ("email",))], sent, NOW, client=net.client)
    assert "graph.facebook.com" not in net.hosts()


def test_telegram_retry_does_not_repeat_whatsapp(meta):
    net, sent = Net(fail={"telegram"}), {}
    deliver(meta, [msg()], sent, NOW, client=net.client)
    assert "olay:karar" not in sent and "olay:karar#wa1" in sent  # Telegram yeniden denenecek
    net.fail.clear()
    net.reqs.clear()
    deliver(meta, [msg()], sent, NOW, client=net.client)
    assert net.hosts() == ["api.telegram.org"]
    assert "olay:karar" in sent


def test_whatsapp_failure_does_not_repeat_telegram(meta):
    net, sent = Net(fail={"meta"}), {}
    lines = deliver(meta, [msg()], sent, NOW, client=net.client)
    assert "olay:karar" in sent and not any("#wa" in k for k in sent)  # Telegram gitti, tekrar gönderilmez
    assert sum("WhatsApp'a gönderilemedi" in x for x in lines) == 2
    assert all(TOKEN not in x for x in lines)


def test_one_recipient_failing_does_not_spam_others(meta):
    net, sent = Net(), {}
    sent["olay:karar#wa1"] = "2026-11-12T09:00:00+03:00"  # 1. alıcıya daha önce gitmiş
    deliver(meta, [msg()], sent, NOW, client=net.client)
    assert [json.loads(r.content)["to"] for r in net.reqs if "facebook" in r.url.host] == ["905554445566"]


def test_template_single_line(meta):
    net = Net()
    send_whatsapp(meta, msg().plain, net.client)
    assert [r.url.path for r in net.reqs] == ["/v25.0/1234567890/messages"] * 2
    body = json.loads(net.reqs[0].content)
    assert body["messaging_product"] == "whatsapp" and body["type"] == "template"
    assert body["template"]["name"] == "radar_bildirim" and body["template"]["language"] == {"code": "tr"}
    text = body["template"]["components"][0]["parameters"][0]["text"]
    assert text == "[KARAR ÇIKTI] Köprü · Yürürlük: 1 Ocak https://ornek"
    assert net.reqs[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_long_text_cut(meta):
    net = Net()
    send_whatsapp(meta, "a " * 2000, net.client)
    text = json.loads(net.reqs[0].content)["template"]["components"][0]["parameters"][0]["text"]
    assert len(text) <= 900 and text.endswith("…")


def test_error_is_masked(meta):
    net = Net(fail={"meta"})
    with pytest.raises(RuntimeError) as e:
        send_whatsapp(meta, "x", net.client)
    assert TOKEN not in str(e.value)


def test_one_line():
    assert one_line("a\n\n  b\t c     d \n") == "a · b c d"
