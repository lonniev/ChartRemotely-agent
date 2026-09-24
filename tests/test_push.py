"""The picture pushed after a chart change: when it goes, and that it never hurts."""

import threading

from chartremotely import push

PAIRED = {"operator_url": "https://op.test/", "agent_id": "a1", "agent_secret": "s1"}


def test_an_unpaired_mac_pushes_nothing():
    assert push.payload({"operator_url": None, "agent_id": None, "agent_secret": None}, "x") is None
    assert push.payload({**PAIRED, "agent_secret": ""}, "x") is None


def test_the_push_carries_the_agents_identity_and_the_picture():
    url, body = push.payload(PAIRED, "data:image/jpeg;base64,AAAA")
    assert url == "https://op.test/agent/snapshot"
    assert body == {"agent_id": "a1", "secret": "s1", "image": "data:image/jpeg;base64,AAAA"}


def test_a_failed_change_starts_no_push(monkeypatch):
    started = []
    monkeypatch.setattr(threading, "Thread", lambda **kw: started.append(kw) or _Never())
    assert push.after_change("ERR no match for 'volunteer'") == "ERR no match for 'volunteer'"
    assert started == []


def test_a_good_change_answers_at_once_and_pushes_behind_it(monkeypatch):
    started = []
    monkeypatch.setattr(threading, "Thread", lambda **kw: started.append(kw) or _Never())
    assert push.after_change("Showing PLTR at swing. Good luck.").startswith("Showing PLTR")
    assert [kw["target"] for kw in started] == [push.push_now]


def test_a_push_never_raises_whatever_goes_wrong(monkeypatch):
    monkeypatch.setattr(push.config, "load", lambda: PAIRED)
    monkeypatch.setattr(push, "SETTLE_SECONDS", 0)

    def boom(*a, **k):
        raise OSError("operator unreachable")
    monkeypatch.setattr(push.relay, "_post", boom)
    push.push_now()  # the capture or the post fails; the chart already changed


class _Never:
    def start(self):
        pass
