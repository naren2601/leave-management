import asyncio
from datetime import date

import pytest

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    InvalidTransitionError,
    NotAuthorizedError,
    NotFoundError,
    OverlappingLeaveError,
    PolicyViolationError,
)
from leavedesk.domain.models import (
    DayPart,
    Employee,
    LeaveStatus,
    LeaveType,
    Manager,
)
from leavedesk.domain.notifications import (
    InAppNotifier,
    Notification,
    NotificationEvent,
    Notifier,
)
from leavedesk.domain.repository import InMemoryLeaveRepository
from leavedesk.domain.service import LeaveService

TODAY = date(2026, 11, 9)  # a Monday
NEXT_MONDAY = date(2026, 11, 16)
NEXT_WEDNESDAY = date(2026, 11, 18)
NEXT_FRIDAY = date(2026, 11, 20)
NEXT_SATURDAY = date(2026, 11, 21)
NEXT_SUNDAY = date(2026, 11, 22)


def run(coroutine):
    return asyncio.run(coroutine)


class FailingNotifier(Notifier):
    async def send(self, notification: Notification) -> None:
        raise ConnectionError("mail server down")


@pytest.fixture
def repo():
    repo = InMemoryLeaveRepository()
    repo.add_employee(Manager(id="m1", name="Ravi", email="ravi@example.com"))
    repo.add_employee(Manager(id="m2", name="Meena", email="meena@example.com"))
    repo.add_employee(
        Employee(id="e1", name="Asha", email="asha@example.com", manager_id="m1")
    )
    repo.add_employee(
        Employee(id="e2", name="Kiran", email="kiran@example.com", manager_id="m2")
    )
    repo.add_employee(Employee(id="solo", name="Sam", email="sam@example.com"))
    return repo


@pytest.fixture
def inbox():
    return InAppNotifier()


@pytest.fixture
def service(repo, inbox):
    return LeaveService(repo, notifiers=[inbox], today=lambda: TODAY)


def apply(service, employee_id="e1", leave_type=LeaveType.ANNUAL,
          start=NEXT_MONDAY, end=NEXT_WEDNESDAY, reason="Family trip",
          day_part=DayPart.FULL):
    return run(
        service.apply(employee_id, leave_type, start, end, reason, day_part)
    )


def available(service, employee_id="e1", leave_type=LeaveType.ANNUAL):
    return service.get_balance(employee_id, leave_type).available


# FR-1 Apply


def test_apply_saves_pending_request_with_working_days(service, repo):
    request = apply(service)

    assert request.status is LeaveStatus.PENDING
    assert request.days == 3
    assert request.id == "LR-1"
    assert repo.get_request("LR-1") is request


@pytest.mark.parametrize("reason", ["abc", "x" * 501])
def test_invalid_reason_raises_and_saves_nothing(service, repo, reason):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, reason=reason)

    assert repo.requests_for("e1") == []
    assert available(service) == 18


def test_annual_leave_without_notice_breaks_policy(service):
    with pytest.raises(PolicyViolationError):
        apply(service, start=TODAY, end=TODAY)


def test_employee_without_manager_cannot_apply(service):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, employee_id="solo")


def test_unknown_employee_raises_not_found(service):
    with pytest.raises(NotFoundError):
        apply(service, employee_id="nobody")


def test_failed_apply_does_not_use_up_an_id(service):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, reason="no")

    assert apply(service).id == "LR-1"


# FR-2 and edge cases EC-1, EC-2, EC-5


def test_end_before_start_raises(service):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, start=NEXT_WEDNESDAY, end=NEXT_MONDAY)


def test_weekend_inside_range_is_not_charged(service):
    request = apply(service, start=NEXT_FRIDAY, end=date(2026, 11, 24))

    assert request.days == 3  # Friday, Monday, Tuesday


def test_weekend_only_request_raises(service):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, start=NEXT_SATURDAY, end=NEXT_SUNDAY)


def test_half_day_costs_half(service):
    request = apply(
        service, start=NEXT_MONDAY, end=NEXT_MONDAY, day_part=DayPart.AM
    )

    assert request.days == 0.5
    assert available(service) == 17.5


def test_half_day_over_several_days_raises(service):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, day_part=DayPart.PM)


# FR-3 Overlaps


def test_overlapping_request_raises(service):
    apply(service)

    with pytest.raises(OverlappingLeaveError):
        apply(service, start=NEXT_WEDNESDAY, end=NEXT_FRIDAY)


def test_dates_of_rejected_request_can_be_reused(service):
    first = apply(service)
    run(service.reject(first.id, "m1", "Team is short that week"))

    second = apply(service)

    assert second.status is LeaveStatus.PENDING


def test_am_and_pm_on_same_day_do_not_clash(service):
    apply(service, start=NEXT_MONDAY, end=NEXT_MONDAY, day_part=DayPart.AM)

    afternoon = apply(
        service, start=NEXT_MONDAY, end=NEXT_MONDAY, day_part=DayPart.PM
    )

    assert afternoon.days == 0.5


# FR-4 Balances, EC-4


def test_apply_reserves_pending_days(service):
    apply(service)

    balance = service.get_balance("e1", LeaveType.ANNUAL)
    assert (balance.pending, balance.available) == (3, 15)


def test_insufficient_balance_raises_and_changes_nothing(service, repo):
    with pytest.raises(InsufficientBalanceError):
        apply(service, leave_type=LeaveType.SICK,
              start=NEXT_MONDAY, end=date(2026, 12, 4))  # 15 working days

    assert available(service, leave_type=LeaveType.SICK) == 10
    assert repo.requests_for("e1") == []


def test_pending_days_count_against_new_requests(service):
    # Sick leave has 10 days. Reserve 5, then ask for 6 more.
    apply(service, leave_type=LeaveType.SICK,
          start=NEXT_MONDAY, end=NEXT_FRIDAY)

    with pytest.raises(InsufficientBalanceError):
        apply(service, leave_type=LeaveType.SICK,
              start=date(2026, 11, 23), end=date(2026, 11, 30))


# FR-5 Approve


def test_manager_approves_and_days_become_used(service):
    request = apply(service)

    run(service.approve(request.id, "m1"))

    balance = service.get_balance("e1", LeaveType.ANNUAL)
    assert request.status is LeaveStatus.APPROVED
    assert (balance.pending, balance.used, balance.available) == (0, 3, 15)


@pytest.mark.parametrize("approver", ["m2", "e2", "e1"])
def test_only_own_manager_can_approve(service, approver):
    request = apply(service)

    with pytest.raises(NotAuthorizedError):
        run(service.approve(request.id, approver))

    assert request.status is LeaveStatus.PENDING


def test_approving_twice_raises(service):
    request = apply(service)
    run(service.approve(request.id, "m1"))

    with pytest.raises(InvalidTransitionError):
        run(service.approve(request.id, "m1"))


def test_unknown_request_raises_not_found(service):
    with pytest.raises(NotFoundError):
        run(service.approve("LR-99", "m1"))


# FR-6 Reject


def test_reject_stores_note_and_returns_days(service):
    request = apply(service)

    run(service.reject(request.id, "m1", "  Team is short that week  "))

    assert request.status is LeaveStatus.REJECTED
    assert request.decision_note == "Team is short that week"
    assert available(service) == 18


@pytest.mark.parametrize("note", ["", "   "])
def test_reject_needs_a_note(service, note):
    request = apply(service)

    with pytest.raises(InvalidLeaveRequestError):
        run(service.reject(request.id, "m1", note))

    assert request.status is LeaveStatus.PENDING


def test_rejecting_approved_request_raises(service):
    request = apply(service)
    run(service.approve(request.id, "m1"))

    with pytest.raises(InvalidTransitionError):
        run(service.reject(request.id, "m1", "Changed my mind"))


# FR-7 Cancel


def test_cancel_pending_request_returns_days(service):
    request = apply(service)

    run(service.cancel(request.id, "e1"))

    assert request.status is LeaveStatus.CANCELLED
    assert available(service) == 18


def test_cancel_approved_request_before_start_returns_days(service):
    request = apply(service)
    run(service.approve(request.id, "m1"))

    run(service.cancel(request.id, "e1"))

    balance = service.get_balance("e1", LeaveType.ANNUAL)
    assert request.status is LeaveStatus.CANCELLED
    assert (balance.used, balance.available) == (0, 18)


def test_cancel_approved_request_after_start_raises(repo, inbox):
    early = LeaveService(repo, notifiers=[inbox], today=lambda: TODAY)
    request = apply(early)
    run(early.approve(request.id, "m1"))

    late = LeaveService(repo, notifiers=[inbox], today=lambda: NEXT_WEDNESDAY)
    with pytest.raises(InvalidTransitionError):
        run(late.cancel(request.id, "e1"))

    assert request.status is LeaveStatus.APPROVED


def test_only_owner_can_cancel(service):
    request = apply(service)

    with pytest.raises(NotAuthorizedError):
        run(service.cancel(request.id, "e2"))


def test_cancelling_twice_raises(service):
    request = apply(service)
    run(service.cancel(request.id, "e1"))

    with pytest.raises(InvalidTransitionError):
        run(service.cancel(request.id, "e1"))


# FR-8 Notifications from the service


def test_submit_notifies_employee_and_manager(service, inbox):
    apply(service)

    assert inbox.unread_count("e1") == 1
    assert inbox.unread_count("m1") == 1
    assert inbox.inbox("m1")[0].event is NotificationEvent.SUBMITTED


def test_approve_and_reject_notify_employee_only(service, inbox):
    first = apply(service)
    second = apply(service, start=date(2026, 11, 23), end=date(2026, 11, 24))

    run(service.approve(first.id, "m1"))
    run(service.reject(second.id, "m1", "Team is short that week"))

    events_for_employee = [n.event for n in inbox.inbox("e1")]
    events_for_manager = [n.event for n in inbox.inbox("m1")]
    assert NotificationEvent.APPROVED in events_for_employee
    assert NotificationEvent.REJECTED in events_for_employee
    assert events_for_manager == [NotificationEvent.SUBMITTED] * 2


def test_cancel_notifies_employee_and_manager(service, inbox):
    request = apply(service)

    run(service.cancel(request.id, "e1"))

    assert inbox.inbox("e1")[-1].event is NotificationEvent.CANCELLED
    assert inbox.inbox("m1")[-1].event is NotificationEvent.CANCELLED


def test_failed_notification_does_not_undo_the_action(repo, inbox):
    service = LeaveService(
        repo, notifiers=[FailingNotifier(), inbox], today=lambda: TODAY
    )

    request = apply(service)

    assert repo.get_request(request.id).status is LeaveStatus.PENDING
    assert inbox.unread_count("e1") == 1


def test_failed_action_sends_no_notification(service, inbox):
    with pytest.raises(InvalidLeaveRequestError):
        apply(service, reason="no")

    assert inbox.inbox("e1") == []
