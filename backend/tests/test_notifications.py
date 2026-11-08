import asyncio
from datetime import date

import pytest

from leavedesk.domain.models import Employee, LeaveRequest, LeaveType
from leavedesk.domain.notifications import (
    EmailNotifier,
    InAppNotifier,
    Notification,
    NotificationEvent,
    Notifier,
    build_notifications,
    dispatch,
)

EMPLOYEE = Employee(id="e1", name="Asha", email="asha@example.com", manager_id="m1")
MANAGER = Employee(id="m1", name="Ravi", email="ravi@example.com")
REQUEST = LeaveRequest(
    id="LR-1",
    employee_id="e1",
    leave_type=LeaveType.ANNUAL,
    start_date=date(2026, 11, 16),
    end_date=date(2026, 11, 18),
    reason="Family trip",
    decision_note="Team is short",
)


def run(coroutine):
    return asyncio.run(coroutine)


def recipients(event):
    notifications = build_notifications(event, REQUEST, EMPLOYEE, MANAGER)
    return [n.recipient for n in notifications]


# Who is notified (section 2 of the spec)


@pytest.mark.parametrize(
    "event, expected",
    [
        (NotificationEvent.SUBMITTED, ["e1", "m1"]),
        (NotificationEvent.APPROVED, ["e1"]),
        (NotificationEvent.REJECTED, ["e1"]),
        (NotificationEvent.CANCELLED, ["e1", "m1"]),
    ],
)
def test_recipients_follow_the_spec(event, expected):
    assert recipients(event) == expected


def test_rejection_message_includes_the_reason():
    [notification] = build_notifications(
        NotificationEvent.REJECTED, REQUEST, EMPLOYEE, MANAGER
    )

    assert "Team is short" in notification.message


def test_new_notification_is_unread():
    assert Notification("e1", NotificationEvent.APPROVED, "Hi").read is False


# Notifiers


def test_notifier_is_abstract():
    with pytest.raises(TypeError):
        Notifier()


def test_email_notifier_records_what_it_would_send():
    email = EmailNotifier()
    notification = Notification("e1", NotificationEvent.APPROVED, "Approved")

    run(email.send(notification))

    assert email.sent == [notification]


def test_in_app_mark_read_lowers_unread_count():
    in_app = InAppNotifier()
    run(in_app.send(Notification("e1", NotificationEvent.APPROVED, "One")))
    run(in_app.send(Notification("e1", NotificationEvent.REJECTED, "Two")))

    in_app.inbox("e1")[0].mark_read()

    assert in_app.unread_count("e1") == 1


def test_empty_inbox():
    assert InAppNotifier().inbox("nobody") == []
    assert InAppNotifier().unread_count("nobody") == 0


# Dispatch with asyncio.gather


class SlowNotifier(Notifier):
    """Records when each delivery starts and finishes."""

    def __init__(self, log):
        self.log = log

    async def send(self, notification):
        self.log.append(("start", notification.recipient))
        await asyncio.sleep(0.01)
        self.log.append(("end", notification.recipient))


class FailingNotifier(Notifier):
    async def send(self, notification):
        raise ConnectionError("mail server down")


def test_dispatch_sends_every_notification_on_every_channel():
    email, in_app = EmailNotifier(), InAppNotifier()
    notifications = build_notifications(
        NotificationEvent.SUBMITTED, REQUEST, EMPLOYEE, MANAGER
    )

    run(dispatch([email, in_app], notifications))

    assert len(email.sent) == 2
    assert in_app.unread_count("e1") == 1
    assert in_app.unread_count("m1") == 1


def test_dispatch_runs_deliveries_concurrently():
    log = []
    notifications = build_notifications(
        NotificationEvent.SUBMITTED, REQUEST, EMPLOYEE, MANAGER
    )

    run(dispatch([SlowNotifier(log)], notifications))

    # Both deliveries start before either finishes.
    assert [step for step, _ in log[:2]] == ["start", "start"]


def test_one_failing_channel_does_not_stop_the_others():
    in_app = InAppNotifier()
    notifications = build_notifications(
        NotificationEvent.SUBMITTED, REQUEST, EMPLOYEE, MANAGER
    )

    failures = run(dispatch([FailingNotifier(), in_app], notifications))

    assert len(failures) == 2
    assert in_app.unread_count("e1") == 1
    assert in_app.unread_count("m1") == 1
