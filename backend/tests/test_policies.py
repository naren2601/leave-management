from datetime import date, timedelta

import pytest

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    PolicyViolationError,
)
from leavedesk.domain.models import LeaveRequest, LeaveType
from leavedesk.domain.policies import (
    AnnualLeavePolicy,
    CasualLeavePolicy,
    LeaveBalance,
    LeavePolicy,
    SickLeavePolicy,
    default_policies,
)

TODAY = date(2026, 11, 9)  # a Monday


def days_from_today(n):
    return TODAY + timedelta(days=n)


def make_request(leave_type, start, end=None, days=1):
    return LeaveRequest(
        id="r1",
        employee_id="e1",
        leave_type=leave_type,
        start_date=start,
        end_date=end or start,
        reason="Personal work",
        days=days,
    )


# LeaveBalance (FR-4, EC-4)


def make_balance(entitled=18):
    return LeaveBalance("e1", LeaveType.ANNUAL, entitled)


def test_new_balance_is_fully_available():
    assert make_balance().available == 18


def test_reserve_moves_days_to_pending():
    balance = make_balance()

    balance.reserve(3)

    assert balance.pending == 3
    assert balance.available == 15


def test_reserve_more_than_available_raises_and_changes_nothing():
    balance = make_balance(entitled=2)

    with pytest.raises(InsufficientBalanceError):
        balance.reserve(3)

    assert balance.pending == 0
    assert balance.available == 2


def test_pending_days_are_already_reserved():
    balance = make_balance(entitled=5)
    balance.reserve(3)

    with pytest.raises(InsufficientBalanceError):
        balance.reserve(3)


def test_reserving_exactly_what_is_left_is_allowed():
    balance = make_balance(entitled=3)

    balance.reserve(3)

    assert balance.available == 0


def test_half_day_can_be_reserved():
    balance = make_balance(entitled=1)

    balance.reserve(0.5)

    assert balance.available == 0.5


def test_confirm_moves_pending_to_used():
    balance = make_balance()
    balance.reserve(3)

    balance.confirm(3)

    assert (balance.pending, balance.used, balance.available) == (0, 3, 15)


def test_release_pending_returns_days():
    balance = make_balance()
    balance.reserve(3)

    balance.release_pending(3)

    assert balance.available == 18


def test_restore_used_returns_days():
    balance = make_balance()
    balance.reserve(3)
    balance.confirm(3)

    balance.restore_used(3)

    assert balance.available == 18


@pytest.mark.parametrize("days", [0, -1])
def test_days_must_be_positive(days):
    with pytest.raises(InvalidLeaveRequestError):
        make_balance().reserve(days)


# Policies


def test_leave_policy_cannot_be_created_directly():
    with pytest.raises(TypeError):
        LeavePolicy()


@pytest.mark.parametrize(
    "policy, leave_type, days",
    [
        (AnnualLeavePolicy(), LeaveType.ANNUAL, 18),
        (SickLeavePolicy(), LeaveType.SICK, 10),
        (CasualLeavePolicy(), LeaveType.CASUAL, 6),
    ],
)
def test_each_policy_creates_its_balance(policy, leave_type, days):
    balance = policy.new_balance("e1")

    assert balance.leave_type is leave_type
    assert balance.entitled == days


def test_default_policies_cover_every_leave_type():
    policies = default_policies()

    assert set(policies) == set(LeaveType)
    for leave_type, policy in policies.items():
        assert policy.leave_type is leave_type


def test_policy_rejects_the_wrong_leave_type():
    request = make_request(LeaveType.SICK, days_from_today(5))

    with pytest.raises(PolicyViolationError):
        AnnualLeavePolicy().validate(request, TODAY)


@pytest.mark.parametrize("offset", [3, 30])
def test_annual_leave_with_enough_notice_is_allowed(offset):
    request = make_request(LeaveType.ANNUAL, days_from_today(offset))

    AnnualLeavePolicy().validate(request, TODAY)


@pytest.mark.parametrize("offset", [-1, 0, 2])
def test_annual_leave_without_enough_notice_is_rejected(offset):
    request = make_request(LeaveType.ANNUAL, days_from_today(offset))

    with pytest.raises(PolicyViolationError):
        AnnualLeavePolicy().validate(request, TODAY)


@pytest.mark.parametrize("offset", [-7, 0, 5])
def test_sick_leave_within_backdate_limit_is_allowed(offset):
    request = make_request(LeaveType.SICK, days_from_today(offset))

    SickLeavePolicy().validate(request, TODAY)


def test_sick_leave_backdated_too_far_is_rejected():
    request = make_request(LeaveType.SICK, days_from_today(-8))

    with pytest.raises(PolicyViolationError):
        SickLeavePolicy().validate(request, TODAY)


@pytest.mark.parametrize("days", [0.5, 1, 2])
def test_casual_leave_up_to_two_days_is_allowed(days):
    request = make_request(LeaveType.CASUAL, TODAY, days=days)

    CasualLeavePolicy().validate(request, TODAY)


def test_casual_leave_over_two_days_is_rejected():
    request = make_request(
        LeaveType.CASUAL, TODAY, days_from_today(2), days=3
    )

    with pytest.raises(PolicyViolationError):
        CasualLeavePolicy().validate(request, TODAY)


def test_casual_leave_in_the_past_is_rejected():
    request = make_request(LeaveType.CASUAL, days_from_today(-1))

    with pytest.raises(PolicyViolationError):
        CasualLeavePolicy().validate(request, TODAY)
