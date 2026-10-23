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
