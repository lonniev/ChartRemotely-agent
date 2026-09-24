"""The picture pushed after a chart change: only after the reply, one per burst, never in the way."""

import threading
import time
import types

import pytest

from chartremotely import guilock, push

PAIRED = {"operator_url": "https://op.test/", "agent_id": "a1", "agent_secret": "s1"}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(guilock.config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(push, "_named", None)


def test_an_unpaired_mac_pushes_nothing():
    assert push.payload({"operator_url": None, "agent_id": None, "agent_secret": None}, "x") is None
    assert push.payload({**PAIRED, "agent_secret": ""}, "x") is None


def test_the_push_carries_the_agents_identity_and_the_picture():
    url, body = push.payload(PAIRED, "data:image/jpeg;base64,AAAA")
    assert url == "https://op.test/agent/snapshot"
    assert body == {"agent_id": "a1", "secret": "s1", "image": "data:image/jpeg;base64,AAAA"}


def test_the_push_names_the_symbol_the_chart_shows():
    _, body = push.payload(PAIRED, "img", " pltr ")
    assert body["symbol"] == "PLTR"


@pytest.mark.parametrize("raw", ["/ES", ".SPX", "$SPX.X", "^VIX", "BRK/B", "BRK-B", "A"])
def test_futures_indices_and_share_classes_are_symbol_shaped(raw):
    assert push.symbol_label(raw) == raw


@pytest.mark.parametrize("raw", [None, "", "   ", "TOO-LONG-A-SYMBOL", "PL TR", "<b>", "PLTR;", 7])
def test_an_unreadable_symbol_is_left_off_rather_than_sent(raw):
    _, body = push.payload(PAIRED, "img", raw)
    assert "symbol" not in body


@pytest.fixture
def labelled(monkeypatch):
    """Capture stubbed out; returns the bodies pushed. The symbol field reads OLD."""
    import chartremotely

    sent = []
    monkeypatch.setattr(push.config, "load", lambda: PAIRED)
    monkeypatch.setattr(push.relay, "_post", lambda url, body, timeout: sent.append(body))
    monkeypatch.setattr(push, "_showing", lambda: "OLD")
    monkeypatch.setattr(chartremotely, "window",
                        types.SimpleNamespace(capture=lambda: b"png"), raising=False)
    monkeypatch.setattr(chartremotely, "snapshot",
                        types.SimpleNamespace(shrink=lambda b: b, as_reply=lambda b: "data:img"),
                        raising=False)
    return sent


def test_a_burst_is_labelled_with_its_last_set(monkeypatch, labelled):
    monkeypatch.setattr(push, "QUIET_SECONDS", 0.1)
    push.after_reply("set AAPL", "Showing AAPL at swing, as is. Good luck.", "AAPL")
    push.after_reply("set MSFT | daily", "Showing MSFT at daily. Good luck.", "MSFT")
    time.sleep(0.4)
    assert [b["symbol"] for b in labelled] == ["MSFT"]


def test_a_change_naming_no_symbol_keeps_the_last_sets(monkeypatch, labelled):
    monkeypatch.setattr(push, "schedule", lambda: None)
    push.after_reply("set NVDA", "Showing NVDA. Good luck.", "NVDA")
    push.after_reply("set | swing", "Scale is swing.")  # a change that names no symbol
    push.push_now()
    assert labelled[-1]["symbol"] == "NVDA"


def test_a_failed_set_does_not_relabel(monkeypatch, labelled):
    monkeypatch.setattr(push, "schedule", lambda: None)
    push.after_reply("set NVDA", "Showing NVDA. Good luck.", "NVDA")
    push.after_reply("set ZZZZ", "ERR no symbol field found")
    push.push_now()
    assert labelled[-1]["symbol"] == "NVDA"


def test_the_label_comes_from_the_command_not_the_wording(monkeypatch, labelled):
    monkeypatch.setattr(push, "schedule", lambda: None)
    push.after_reply("set TSLA", "Now on the wall: Tesla. Enjoy.", "TSLA")
    push.push_now()
    assert labelled[-1]["symbol"] == "TSLA"


def test_the_symbol_field_is_only_the_fallback(labelled):
    push.push_now()
    assert labelled[-1]["symbol"] == "OLD"


def test_a_failed_symbol_read_still_sends_the_picture(monkeypatch):
    import chartremotely

    def unreadable():
        raise RuntimeError("no symbol field")
    monkeypatch.setattr(chartremotely, "symbol",
                        types.SimpleNamespace(current=unreadable), raising=False)
    assert push._showing() is None


@pytest.mark.parametrize("request_, reply, changed", [
    ("set PLTR | swing", "Showing PLTR at swing. Good luck.", True),
    ("palantir", "Showing PLTR at swing, as is. Good luck.", True),
    ("set PLTR", "ERR no symbol field found", False),
    ("resolve palantir", "PLTR", False),
    ("scale swing", "swing", False),
    ("read", "PLTR at swing", False),
    ("snapshot", "data:image/jpeg;base64,AAAA", False),
    ("", "ERR I didn't catch that.", False),
])
def test_only_an_answered_change_earns_a_picture(request_, reply, changed):
    assert push.changes_chart(request_, reply) is changed


def test_a_burst_of_changes_gives_one_picture_after_the_last(monkeypatch):
    shots = []
    monkeypatch.setattr(push, "QUIET_SECONDS", 0.15)
    monkeypatch.setattr(push, "push_now", lambda: shots.append(time.monotonic()))
    started = time.monotonic()
    for i in range(4):
        if i:
            time.sleep(0.05)
        push.after_reply("set PLTR", "Showing PLTR. Good luck.")
        last = time.monotonic()
    time.sleep(0.5)
    assert len(shots) == 1, "one picture for the whole burst"
    assert shots[0] - last >= 0.14, "taken only once the chart went quiet"
    assert shots[0] > started


def test_nothing_is_scheduled_for_a_request_that_changed_nothing(monkeypatch):
    shots = []
    monkeypatch.setattr(push, "QUIET_SECONDS", 0.05)
    monkeypatch.setattr(push, "push_now", lambda: shots.append(1))
    push.after_reply("resolve palantir", "PLTR")
    time.sleep(0.2)
    assert shots == []


def test_a_push_never_raises_whatever_goes_wrong(monkeypatch):
    monkeypatch.setattr(push.config, "load", lambda: PAIRED)

    def boom(*a, **k):
        raise OSError("operator unreachable")
    monkeypatch.setattr(push.relay, "_post", boom)
    push.push_now()  # the capture or the post fails; the chart already changed


def test_the_chart_is_driven_by_one_holder_at_a_time():
    order = []

    def hold(name, pause):
        with guilock.driving():
            order.append(f"{name} in")
            time.sleep(pause)
            order.append(f"{name} out")

    a = threading.Thread(target=hold, args=("a", 0.2))
    a.start()
    time.sleep(0.05)
    hold("b", 0)
    a.join()
    assert order == ["a in", "a out", "b in", "b out"]


def test_a_holder_that_never_lets_go_is_reported_busy():
    release = threading.Event()

    def hog():
        with guilock.driving():
            release.wait(2)

    t = threading.Thread(target=hog)
    t.start()
    time.sleep(0.05)
    with pytest.raises(guilock.Busy), guilock.driving(wait=0.2):
        pass
    release.set()
    t.join()
