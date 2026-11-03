"""Doctor's verdicts on the services and their grants - the parts that need no Mac."""

from chartremotely import doctor, services

OLD = "/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
NEW = OLD.replace("3.12.13", "3.12.15_1")


def test_both_grants_held_is_ok():
    status, _ = doctor.permission_verdict({"python": NEW, "accessibility": True, "screen_recording": True})
    assert status == doctor.OK


def test_a_missing_grant_names_it_the_python_and_the_fix():
    status, detail = doctor.permission_verdict({"python": NEW, "accessibility": True, "screen_recording": False})
    assert status == doctor.BAD
    assert "Screen Recording" in detail and "Accessibility" not in detail
    assert NEW in detail and "chartremotely setup" in detail


def test_a_probe_that_never_answered_fails():
    assert doctor.permission_verdict({})[0] == doctor.BAD


def test_a_service_on_a_deleted_python_says_restart_it():
    status, detail = doctor.service_verdict({"serve": NEW, "relay": OLD}, exists=lambda p: p == NEW)
    assert status == doctor.BAD
    assert "com.chartremotely.relay" in detail and "com.chartremotely.serve" not in detail


def test_a_stopped_service_points_at_setup():
    status, detail = doctor.service_verdict({"serve": None, "relay": NEW}, exists=lambda p: True)
    assert status == doctor.BAD and "serve" in detail and "setup" in detail


def test_both_running_on_a_live_python_is_ok():
    assert doctor.service_verdict({"serve": NEW, "relay": NEW}, exists=lambda p: True)[0] == doctor.OK


def test_launchctl_print_yields_the_pid_only_while_running():
    assert services.pid_in("com.chartremotely.relay = {\n\tstate = running\n\tpid = 12804\n}") == 12804
    assert services.pid_in("com.chartremotely.relay = {\n\tstate = not running\n}") is None


# -- the listener: a free table lookup, never a paid chart read ----------------------------

import urllib.error


def test_the_listener_probe_is_a_free_lookup_never_read():
    # server.LOOKUPS needs Quartz to import; the verb is pinned here instead.
    assert doctor.LISTENER_PROBE.split()[0] == b"scale"


def test_a_listener_that_answers_the_lookup_is_ok():
    assert doctor.listener_verdict(8899, "t", post=lambda port, token: "half")[0] == doctor.OK


def _raises(exc):
    def post(port, token):
        raise exc
    return post


def test_a_slow_listener_fails_and_says_so():
    for exc in (TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))):
        status, detail = doctor.listener_verdict(8899, "t", post=_raises(exc))
        assert status == doctor.BAD and "took over" in detail


def test_nothing_listening_points_at_serve():
    status, detail = doctor.listener_verdict(8899, "t", post=_raises(urllib.error.URLError(ConnectionRefusedError())))
    assert status == doctor.WARN and "chartremotely serve" in detail


def test_a_refused_token_is_named():
    refused = urllib.error.HTTPError("http://127.0.0.1:8899/chart", 403, "Forbidden", {}, None)
    status, detail = doctor.listener_verdict(8899, "t", post=_raises(refused))
    assert status == doctor.BAD and "token" in detail


def test_a_wrong_answer_fails():
    assert doctor.listener_verdict(8899, "t", post=lambda port, token: "ERR nope")[0] == doctor.BAD
