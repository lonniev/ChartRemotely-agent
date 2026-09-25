"""The pure half of bringing the chart in front: which window, whether it is back, what covers it."""

from chartremotely import screen

TOS, SAFARI, MAIL, OVERLAY = 10, 20, 30, 40


def win(pid, x, y, w, h, layer=0):
    return {"kCGWindowOwnerPID": pid, "kCGWindowLayer": layer,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


CHART = win(TOS, 0, 25, 1600, 1000)


def test_overlap_needs_shared_area_not_a_shared_edge():
    a = {"X": 0, "Y": 0, "Width": 100, "Height": 100}
    assert screen.overlaps(a, {"X": 50, "Y": 50, "Width": 100, "Height": 100})
    assert not screen.overlaps(a, {"X": 100, "Y": 0, "Width": 50, "Height": 50})
    assert not screen.overlaps(a, {"X": 0, "Y": 100, "Width": 50, "Height": 50})


def test_largest_takes_only_the_apps_own_windows():
    windows = [win(SAFARI, 0, 0, 3000, 3000), win(TOS, 0, 0, 200, 200), CHART]
    assert screen.largest(windows, TOS) is CHART
    assert screen.largest(windows, MAIL) is None


def test_the_chart_is_showing_only_when_its_own_frame_is_on_screen():
    detached = win(TOS, 1700, 0, 400, 300)
    assert screen.showing([detached], TOS, (0, 25, 1600, 1000)) is None
    assert screen.showing([detached, CHART], TOS, (0, 25, 1600, 1000)) is CHART
    # A point of rounding between the two APIs is not a different window.
    assert screen.showing([CHART], TOS, (1, 24, 1600, 1001)) is CHART
    assert screen.showing([CHART], SAFARI, (0, 25, 1600, 1000)) is None


def test_covering_names_each_overlapping_ordinary_app_once():
    windows = [win(SAFARI, 100, 100, 500, 500), win(SAFARI, 200, 200, 50, 50),
               win(MAIL, 2000, 0, 300, 300), CHART]
    assert screen.covering(windows, CHART["kCGWindowBounds"], TOS,
                           {SAFARI, MAIL}) == [SAFARI]


def test_covering_never_touches_overlays_the_desktop_or_the_chart_itself():
    windows = [win(OVERLAY, 0, 0, 3000, 2000, layer=25),     # not a regular app
               win(SAFARI, 0, 0, 3000, 2000, layer=-2147483603),  # desktop layer
               CHART]
    assert screen.covering(windows, CHART["kCGWindowBounds"], TOS,
                           {SAFARI, TOS}) == []


def test_wait_for_returns_the_first_truthy_probe():
    answers = iter([None, None, "here"])
    t = [0.0]
    got = screen.wait_for(lambda: next(answers), timeout=2.0, interval=0.1,
                          clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert got == "here"
    assert abs(t[0] - 0.2) < 1e-9


def test_wait_for_gives_up_after_the_timeout_having_probed_at_least_once():
    probes = []
    t = [0.0]
    got = screen.wait_for(lambda: probes.append(1), timeout=0.5, interval=0.1,
                          clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert got is None
    assert 5 <= len(probes) <= 7


def test_presented_says_what_it_took():
    assert not screen.Presented()
    assert str(screen.Presented()) == "already in front"
    done = screen.Presented(unhid=True, raised=True, hid=("Mail", "Safari"))
    assert done
    assert str(done) == "unhid; raised; hid Mail, Safari"
    assert str(screen.Presented(unminimized=True, raised=True)) == "unminimized; raised"
