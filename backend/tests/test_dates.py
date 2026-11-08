from datetime import date

import pytest

from leavedesk.domain.dates import (
    count_leave_days,
    find_overlap,
    is_weekend,
    requests_overlap,
    working_days,
)
from leavedesk.domain.exceptions import InvalidLeaveRequestError, LeaveDeskError
from leavedesk.domain.models import DayPart, LeaveRequest, LeaveStatus, LeaveType

FRIDAY = date(2026, 11, 6)
SATURDAY = date(2026, 11, 7)
SUNDAY = date(2026, 11, 8)
MONDAY = date(2026, 11, 9)
TUESDAY = date(2026, 11, 10)
WEDNESDAY = date(2026, 11, 11)
NEXT_FRIDAY = date(2026, 11, 13)


def make_request(**changes):
    data = {
        "id": "r1",
        "employee_id": "e1",
        "leave_type": LeaveType.ANNUAL,
        "start_date": MONDAY,
        "end_date": TUESDAY,
        "reason": "Family trip",
    }
    return LeaveRequest(**{**data, **changes})


# --- is_weekend -------------------------------------------------------------


@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_saturday_and_sunday_are_weekend(day):
    assert is_weekend(day)


@pytest.mark.parametrize("day", [FRIDAY, MONDAY])
def test_weekdays_are_not_weekend(day):
    assert not is_weekend(day)


# --- working_days -----------------------------------------------------------


@pytest.mark.parametrize(
    "start, end, expected",
    [
        (MONDAY, MONDAY, 1),
        (MONDAY, TUESDAY, 2),
        (MONDAY, NEXT_FRIDAY, 5),
        (FRIDAY, MONDAY, 2),  # skips the weekend in between
        (SATURDAY, SUNDAY, 0),
        (SATURDAY, SATURDAY, 0),
        (FRIDAY, NEXT_FRIDAY, 6),
    ],
)
def test_working_days_counts_weekdays_inclusive(start, end, expected):
    assert working_days(start, end) == expected


def test_working_days_rejects_end_before_start():
    with pytest.raises(InvalidLeaveRequestError):
        working_days(TUESDAY, MONDAY)


# --- count_leave_days -------------------------------------------------------


def test_full_days_are_counted_as_a_float():
    days = count_leave_days(MONDAY, WEDNESDAY)

    assert days == 3.0
    assert isinstance(days, float)


def test_full_day_range_over_a_weekend_skips_it():
    assert count_leave_days(FRIDAY, MONDAY) == 2.0


@pytest.mark.parametrize("day_part", [DayPart.AM, DayPart.PM])
def test_half_day_costs_half(day_part):
    assert count_leave_days(MONDAY, MONDAY, day_part) == 0.5


@pytest.mark.parametrize("start, end", [(SATURDAY, SUNDAY), (SUNDAY, SUNDAY)])
def test_weekend_only_range_is_rejected(start, end):
    with pytest.raises(InvalidLeaveRequestError):
        count_leave_days(start, end)


def test_date_errors_can_be_caught_as_a_leavedesk_error():
    with pytest.raises(LeaveDeskError):
        count_leave_days(TUESDAY, MONDAY)


# --- requests_overlap -------------------------------------------------------


def test_same_dates_overlap():
    assert requests_overlap(make_request(), make_request(id="r2"))


def test_partially_shared_dates_overlap():
    first = make_request(start_date=MONDAY, end_date=TUESDAY)
    second = make_request(id="r2", start_date=TUESDAY, end_date=WEDNESDAY)

    assert requests_overlap(first, second)
    assert requests_overlap(second, first)


def test_range_inside_another_overlaps():
    outer = make_request(start_date=MONDAY, end_date=NEXT_FRIDAY)
    inner = make_request(id="r2", start_date=TUESDAY, end_date=WEDNESDAY)

    assert requests_overlap(outer, inner)
    assert requests_overlap(inner, outer)


def test_back_to_back_ranges_do_not_overlap():
    first = make_request(start_date=MONDAY, end_date=MONDAY)
    second = make_request(id="r2", start_date=TUESDAY, end_date=WEDNESDAY)

    assert not requests_overlap(first, second)
    assert not requests_overlap(second, first)


def test_am_and_pm_on_the_same_date_do_not_overlap():
    am = make_request(end_date=MONDAY, day_part=DayPart.AM)
    pm = make_request(id="r2", end_date=MONDAY, day_part=DayPart.PM)

    assert not requests_overlap(am, pm)
    assert not requests_overlap(pm, am)


@pytest.mark.parametrize("day_part", [DayPart.AM, DayPart.PM])
def test_same_half_on_the_same_date_overlaps(day_part):
    first = make_request(end_date=MONDAY, day_part=day_part)
    second = make_request(id="r2", end_date=MONDAY, day_part=day_part)

    assert requests_overlap(first, second)


@pytest.mark.parametrize("day_part", [DayPart.AM, DayPart.PM])
def test_half_day_overlaps_a_full_day_on_that_date(day_part):
    half = make_request(end_date=MONDAY, day_part=day_part)
    full = make_request(id="r2", start_date=MONDAY, end_date=TUESDAY)

    assert requests_overlap(half, full)
    assert requests_overlap(full, half)


# --- find_overlap -----------------------------------------------------------


def test_no_existing_requests_means_no_overlap():
    assert find_overlap(make_request(), []) is None


@pytest.mark.parametrize("status", [LeaveStatus.PENDING, LeaveStatus.APPROVED])
def test_active_request_is_found(status):
    existing = make_request(id="r2", status=status)

    assert find_overlap(make_request(), [existing]) is existing


@pytest.mark.parametrize(
    "status", [LeaveStatus.REJECTED, LeaveStatus.CANCELLED]
)
def test_rejected_and_cancelled_requests_are_ignored(status):
    existing = make_request(id="r2", status=status)

    assert find_overlap(make_request(), [existing]) is None


def test_other_employees_requests_are_ignored():
    existing = make_request(id="r2", employee_id="e2")

    assert find_overlap(make_request(), [existing]) is None


def test_request_does_not_clash_with_itself():
    request = make_request()

    assert find_overlap(request, [request]) is None


def test_non_overlapping_dates_are_ignored():
    existing = make_request(id="r2", start_date=WEDNESDAY, end_date=NEXT_FRIDAY)

    assert find_overlap(make_request(), [existing]) is None


def test_first_clashing_request_is_returned():
    ignored = make_request(id="r2", status=LeaveStatus.CANCELLED)
    first = make_request(id="r3")
    second = make_request(id="r4")

    assert find_overlap(make_request(), [ignored, first, second]) is first


def test_find_overlap_accepts_any_iterable():
    existing = make_request(id="r2")

    assert find_overlap(make_request(), (r for r in [existing])) is existing
