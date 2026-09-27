"""The one log line per request: enough to diagnose an ERR, nothing secret."""

from chartremotely import requestlog


def test_a_line_carries_time_source_verb_and_where_only():
    line = requestlog.line("serve", "set PLTR | daily", "mac mini", "Showing PLTR at daily.")
    stamp, rest = line.split(" ", 1)
    assert stamp[:4].isdigit() and "T" in stamp
    assert rest == "serve verb=set where='mac mini'"


def test_an_err_reply_is_kept_truncated_and_on_one_line():
    reply = "ERR no\nsuch display " + "x" * 500
    line = requestlog.line("relay", "read", "", reply)
    assert "\n" not in line
    logged = line.split("reply=", 1)[1]
    assert logged.startswith("'ERR no such display") and len(logged) == requestlog.ERR_MAX + 2


def test_where_is_truncated_and_an_empty_command_is_a_dash():
    line = requestlog.line("serve", "", "w" * 100, "ERR empty")
    assert "verb=- " in line and f"where='{'w' * requestlog.WHERE_MAX}'" in line


def test_lookups_log_what_was_heard_and_nothing_else_does():
    line = requestlog.line("serve", "resolve pal and tear", "", "PLTR")
    assert line.endswith("verb=resolve where='' heard='pal and tear'")
    line = requestlog.line("serve", "scale " + "h" * 100, "", "ERR You say minute")
    assert f"heard='{'h' * requestlog.HEARD_MAX}'" in line
    line = requestlog.line("serve", "set PLTR | half", "", "Chart PLTR")
    assert "heard" not in line and "PLTR" not in line
