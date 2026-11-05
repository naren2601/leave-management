from datetime import date

import pytest
from pydantic import ValidationError

from leavedesk.domain.exceptions import InvalidTransitionError, LeaveDeskError
from leavedesk.domain.models import (
    DayPart,
    Employee,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Manager,
)

MONDAY = date(2026, 11, 9)
TUESDAY = date(2026, 11, 10)
SATURDAY = date(2026, 11, 14)


def make_employee(**changes):
    data = {
        "id": "e1",
        "name": "Asha",
        "email": "asha@example.com",
        "manager_id": "m1",
    }
    return Employee(**{**data, **changes})


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


def test_valid_employee_trims_name():
    assert make_employee(name="  Asha  ").name == "Asha"


def test_employee_may_have_no_manager():
    assert make_employee(manager_id=None).manager_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"email": "asha"},
        {"email": "asha@example"},
        {"email": "as ha@example.com"},
        {"manager_id": "e1"},
    ],
)
def test_invalid_employee_is_rejected(changes):
    with pytest.raises(ValidationError):
        make_employee(**changes)


def test_manager_is_an_employee_and_manages_direct_reports_only():
    manager = Manager(id="m1", name="Ravi", email="ravi@example.com")

    assert isinstance(manager, Employee)
    assert manager.manages(make_employee(manager_id="m1"))
    assert not manager.manages(make_employee(manager_id="m2"))


def test_new_request_defaults():
    request = make_request()

    assert request.status is LeaveStatus.PENDING
    assert request.day_part is DayPart.FULL


@pytest.mark.parametrize("reason", ["    ", "abc", " abcd ", "x" * 501])
def test_reason_length_is_checked_after_trimming(reason):
    with pytest.raises(ValidationError):
        make_request(reason=reason)


@pytest.mark.parametrize("reason", ["abcde", " abcde ", "x" * 500])
def test_reason_limits_are_accepted(reason):
    assert make_request(reason=reason).reason == reason.strip()


def test_end_date_before_start_date_is_rejected():
    with pytest.raises(ValidationError):
        make_request(start_date=TUESDAY, end_date=MONDAY)


def test_unknown_status_is_rejected():
    with pytest.raises(ValidationError):
        make_request(status="ON_HOLD")


def test_unknown_status_is_rejected_on_assignment():
    request = make_request()

    with pytest.raises(ValidationError):
        request.status = "ON_HOLD"


def test_half_day_on_one_weekday_is_accepted():
    request = make_request(end_date=MONDAY, day_part=DayPart.AM)

    assert request.day_part is DayPart.AM


def test_half_day_across_several_dates_is_rejected():
    with pytest.raises(ValidationError):
        make_request(day_part=DayPart.PM)


def test_half_day_on_a_weekend_is_rejected():
    with pytest.raises(ValidationError):
        make_request(
            start_date=SATURDAY,
            end_date=SATURDAY,
            day_part=DayPart.AM,
        )


@pytest.mark.parametrize(
    "new_status",
    [LeaveStatus.APPROVED, LeaveStatus.REJECTED, LeaveStatus.CANCELLED],
)
def test_pending_request_can_change_status(new_status):
    request = make_request()

    request.transition_to(new_status)

    assert request.status is new_status


@pytest.mark.parametrize(
    "start_status, new_status",
    [
        (LeaveStatus.PENDING, LeaveStatus.PENDING),
        (LeaveStatus.APPROVED, LeaveStatus.APPROVED),
        (LeaveStatus.APPROVED, LeaveStatus.REJECTED),
        (LeaveStatus.REJECTED, LeaveStatus.APPROVED),
        (LeaveStatus.REJECTED, LeaveStatus.CANCELLED),
        (LeaveStatus.CANCELLED, LeaveStatus.APPROVED),
    ],
)
def test_invalid_transition_raises_and_keeps_status(start_status, new_status):
    request = make_request(status=start_status)

    with pytest.raises(InvalidTransitionError):
        request.transition_to(new_status)

    assert request.status is start_status


def test_approved_request_can_be_cancelled_before_it_starts():
    request = make_request(status=LeaveStatus.APPROVED)

    request.transition_to(LeaveStatus.CANCELLED, today=date(2026, 11, 8))

    assert request.status is LeaveStatus.CANCELLED


@pytest.mark.parametrize("today", [MONDAY, TUESDAY])
def test_approved_request_cannot_be_cancelled_once_started(today):
    request = make_request(status=LeaveStatus.APPROVED)

    with pytest.raises(InvalidTransitionError):
        request.transition_to(LeaveStatus.CANCELLED, today=today)

    assert request.status is LeaveStatus.APPROVED


def test_invalid_transition_can_be_caught_as_a_leavedesk_error():
    request = make_request(status=LeaveStatus.REJECTED)

    with pytest.raises(LeaveDeskError):
        request.transition_to(LeaveStatus.APPROVED)
