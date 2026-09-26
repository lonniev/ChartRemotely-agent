"""The pure half of closing thinkorswim's popups: what is open, and what to do next."""

from chartremotely import popups
from chartremotely.popups import CLOSE_LIST, CLOSE_SCALE, LEAVE_FIELD, Seen

# The symbol combo and the list thinkorswim hung under it, as measured live.
COMBO = (373, 119, 126, 25)
LIST = (375, 142, 511, 190)


def test_a_table_on_the_fields_bottom_left_corner_is_its_list():
    assert popups.hangs_under(COMBO, LIST)


def test_other_tables_are_not_the_list():
    assert not popups.hangs_under(COMBO, None)
    assert not popups.hangs_under(COMBO, (3, 662, 340, 1900))    # the watchlist
    assert not popups.hangs_under(COMBO, (375, 300, 511, 190))   # lower in the pane
    assert not popups.hangs_under(COMBO, (375, 142, 0, 0))       # collapsed, not drawn


def test_the_charts_title_names_its_symbol():
    assert popups.chart_symbol("PLTR 10 D 30m") == "PLTR"
    assert popups.chart_symbol("/ESZ26 5 D 5m") == "/ESZ26"
    assert popups.chart_symbol("BRK/B 1 Y 1D") == "BRK/B"
    assert popups.chart_symbol("Lo: 166.03") is None
    assert popups.chart_symbol("") is None
    assert popups.chart_symbol(None) is None


def test_the_chart_shows_an_entry_only_when_its_title_names_it():
    assert popups.shows("PLTR 10 D 30m", "pltr ")
    assert not popups.shows("PLTR 10 D 30m", "PLT")
    assert popups.shows("/ESZ26 5 D 5m", "/ES")      # a futures root, drawn as its contract
    assert not popups.shows("ESTC 5 D 5m", "ES")     # but not a mere prefix
    assert not popups.shows(None, "PLTR")
    assert not popups.shows("PLTR 10 D 30m", None)


def test_nothing_open_and_nothing_focused_needs_nothing():
    assert popups.next_step(Seen(title="PLTR 10 D 30m", field_value="PLTR")) is None
    assert Seen().clean


def test_the_menu_is_closed_before_the_list():
    both = Seen(scale_open=True, list_open=True, field_value="PLTR")
    assert not both.clean
    assert popups.next_step(both) == CLOSE_SCALE
    assert popups.next_step(Seen(list_open=True, field_value="PLTR")) == CLOSE_LIST


def test_focus_leaves_the_field_only_when_the_chart_shows_its_text():
    committed = Seen(field_focused=True, field_value="PLTR", title="PLTR 10 D 30m")
    assert popups.next_step(committed) == LEAVE_FIELD
    # Losing focus commits the field: a pending "PLT" must keep focus.
    pending = Seen(field_focused=True, field_value="PLT", title="PLTR 10 D 30m")
    assert popups.next_step(pending) is None
    # A title that has not caught up yet is not proof either.
    behind = Seen(field_focused=True, field_value="NVDA", title="PLTR 10 D 30m")
    assert popups.next_step(behind) is None


class Chart:
    """A fake thinkorswim: popups that close when acted on, and a clock."""

    def __init__(self, seen: Seen, title_after: float = 0.0, *, stuck: bool = False):
        self.seen, self.title_after, self.stuck = seen, title_after, stuck
        self.now, self.acts = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def look(self):
        title = self.seen.title if self.now >= self.title_after else "OLD 1 D 1m"
        return Seen(self.seen.scale_open, self.seen.list_open, self.seen.field_focused,
                    self.seen.field_value, None if self.seen.list_open else title)

    def act(self, step):
        self.acts.append(step)
        if self.stuck:
            return
        s = self.seen
        if step == CLOSE_SCALE:
            self.seen = Seen(False, s.list_open, s.field_focused, s.field_value, s.title)
        elif step == CLOSE_LIST:
            self.seen = Seen(s.scale_open, False, True, s.field_value, s.title)
        elif step == LEAVE_FIELD:
            self.seen = Seen(s.scale_open, s.list_open, False, s.field_value, s.title)

    def run(self, **kw):
        return popups.run(self.look, self.act, clock=self.clock, sleep=self.sleep, **kw)


def test_run_closes_menu_then_list_then_lets_go_of_the_field():
    chart = Chart(Seen(True, True, False, "PLTR", "PLTR 10 D 30m"))
    done = chart.run()
    assert chart.acts == [CLOSE_SCALE, CLOSE_LIST, LEAVE_FIELD]
    assert done.clean and done.did == (CLOSE_SCALE, CLOSE_LIST, LEAVE_FIELD)


def test_run_is_cheap_and_silent_when_nothing_is_open():
    chart = Chart(Seen(field_value="PLTR", title="PLTR 10 D 30m"))
    done = chart.run()
    assert chart.acts == [] and chart.now == 0
    assert done.clean and not done and str(done) == "nothing open"


def test_run_leaves_a_pending_entry_in_the_field():
    chart = Chart(Seen(list_open=True, field_value="PLT", title="PLTR 10 D 30m"))
    done = chart.run()
    assert chart.acts == [CLOSE_LIST]
    assert done.clean and chart.seen.field_focused


def test_run_waits_for_the_title_to_name_the_new_symbol_before_letting_go():
    chart = Chart(Seen(list_open=True, field_value="NVDA", title="NVDA 10 D 30m"),
                  title_after=0.8)
    done = chart.run(until=lambda seen: popups.shows(seen.title, "NVDA"), timeout=3.0)
    assert chart.acts == [CLOSE_LIST, LEAVE_FIELD]
    assert 0.8 <= chart.now < 3.0 and done.clean


def test_run_gives_up_at_the_deadline_and_says_so():
    chart = Chart(Seen(scale_open=True, field_value="PLTR"), stuck=True)
    done = chart.run(timeout=1.5)
    assert not done.clean and chart.now >= 1.5
    # A toggle is pressed again only after it has had time to show.
    assert 2 <= len(chart.acts) <= 1.5 / popups.ACT_WAIT + 1
    assert str(done).endswith("a popup is still open")
