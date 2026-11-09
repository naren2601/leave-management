"""LeaveDesk demo: the happy path and the five edge cases from the spec.

Run it from the backend folder:

    python -m leavedesk.demo            short output
    python -m leavedesk.demo --verbose  also shows every audit log line
"""

import asyncio
import logging
import sys
from datetime import date

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    OverlappingLeaveError,
)
from leavedesk.domain.instrumentation import timed
from leavedesk.domain.models import DayPart, Employee, LeaveType, Manager
from leavedesk.domain.notifications import EmailNotifier, InAppNotifier
from leavedesk.domain.repository import InMemoryLeaveRepository
from leavedesk.domain.service import LeaveService

# A fixed "today" so the demo prints the same result on any day.
TODAY = date(2026, 11, 9)  # Monday


def heading(text: str) -> None:
    print()
    print("=" * 64)
    print(text)
    print("=" * 64)


def show_balance(service: LeaveService, employee_id: str, leave_type: LeaveType) -> None:
    b = service.get_balance(employee_id, leave_type)
    print(
        f"   {leave_type.value} balance: entitled {b.entitled:g}, used {b.used:g}, "
        f"pending {b.pending:g}, available {b.available:g}"
    )


def show_inbox(inbox: InAppNotifier, user_id: str, name: str) -> None:
    messages = inbox.inbox(user_id)
    print(f"   {name}'s inbox ({inbox.unread_count(user_id)} unread):")
    for n in messages:
        print(f"     - [{n.event.value}] {n.message}")


def build_service() -> tuple[LeaveService, InAppNotifier, EmailNotifier]:
    repo = InMemoryLeaveRepository()
    repo.add_employee(Manager(id="m1", name="Ravi", email="ravi@example.com"))
    repo.add_employee(
        Employee(id="e1", name="Asha", email="asha@example.com", manager_id="m1")
    )
    inbox, email = InAppNotifier(), EmailNotifier()
    service = LeaveService(repo, notifiers=[email, inbox], today=lambda: TODAY)
    return service, inbox, email


async def happy_path(service: LeaveService, inbox: InAppNotifier, email: EmailNotifier) -> None:
    heading("HAPPY PATH")
    print(f"Today is {TODAY:%A %d %b %Y}. Asha (e1) reports to Ravi (m1).")

    print("\n1. Asha applies for annual leave, Mon 16 to Wed 18 Nov")
    annual = await service.apply(
        "e1", LeaveType.ANNUAL, date(2026, 11, 16), date(2026, 11, 18), "Family trip"
    )
    print(f"   {annual.id} is {annual.status.value}, costs {annual.days:g} days")
    show_balance(service, "e1", LeaveType.ANNUAL)

    print("\n2. Ravi approves it")
    await service.approve(annual.id, "m1")
    print(f"   {annual.id} is {annual.status.value}")
    show_balance(service, "e1", LeaveType.ANNUAL)

    print("\n3. Asha applies for sick leave, Fri 20 to Tue 24 Nov (weekend inside)")
    sick = await service.apply(
        "e1", LeaveType.SICK, date(2026, 11, 20), date(2026, 11, 24), "Doctor's advice"
    )
    print(f"   {sick.id} costs {sick.days:g} days, because Sat and Sun are not charged")

    print("\n4. Ravi rejects it with a reason")
    await service.reject(sick.id, "m1", "Please send a medical certificate")
    print(f"   {sick.id} is {sick.status.value}: {sick.decision_note}")
    show_balance(service, "e1", LeaveType.SICK)

    print("\n5. Asha applies for a casual half-day (morning), Wed 25 Nov")
    half = await service.apply(
        "e1", LeaveType.CASUAL, date(2026, 11, 25), date(2026, 11, 25),
        "Bank work", DayPart.AM,
    )
    print(f"   {half.id} costs {half.days:g} days")
    show_balance(service, "e1", LeaveType.CASUAL)

    print("\n6. Asha cancels the half-day")
    await service.cancel(half.id, "e1")
    print(f"   {half.id} is {half.status.value}")
    show_balance(service, "e1", LeaveType.CASUAL)

    print("\n7. Notifications (sent to every channel at once with asyncio.gather)")
    show_inbox(inbox, "e1", "Asha")
    show_inbox(inbox, "m1", "Ravi")
    print(f"   Emails sent by the stub: {len(email.sent)}")

    print("\n8. Asha reads her first notification")
    inbox.inbox("e1")[0].mark_read()
    print(f"   Asha now has {inbox.unread_count('e1')} unread")


async def edge_cases(service: LeaveService) -> int:
    """Run each edge case and check it raises the right error. Returns failures."""
    heading("EDGE CASES")

    # Asha already has approved annual leave on 16 to 18 Nov from the happy path.
    cases = [
        (
            "EC-1 End date before start date",
            InvalidLeaveRequestError,
            service.apply("e1", LeaveType.ANNUAL, date(2026, 12, 4),
                          date(2026, 12, 1), "Wrong dates"),
        ),
        (
            "EC-2 Only weekend days (Sat 28 to Sun 29 Nov)",
            InvalidLeaveRequestError,
            service.apply("e1", LeaveType.ANNUAL, date(2026, 11, 28),
                          date(2026, 11, 29), "Weekend trip"),
        ),
        (
            "EC-3 Overlaps the approved leave on 16 to 18 Nov",
            OverlappingLeaveError,
            service.apply("e1", LeaveType.ANNUAL, date(2026, 11, 17),
                          date(2026, 11, 19), "Extend my trip"),
        ),
        (
            "EC-4 Annual leave for 20 working days with 15 left",
            InsufficientBalanceError,
            service.apply("e1", LeaveType.ANNUAL, date(2026, 12, 1),
                          date(2026, 12, 28), "Long holiday"),
        ),
        (
            "EC-5 Half-day spanning two dates",
            InvalidLeaveRequestError,
            service.apply("e1", LeaveType.CASUAL, date(2026, 11, 26),
                          date(2026, 11, 27), "Two half-days", DayPart.PM),
        ),
    ]

    failures = 0
    for title, expected, call in cases:
        print(f"\n{title}")
        print(f"   Expected: {expected.__name__}")
        try:
            await call
        except expected as error:
            print(f"   PASS  raised {type(error).__name__}: {error}")
        except Exception as error:
            failures += 1
            print(f"   FAIL  raised {type(error).__name__} instead: {error}")
        else:
            failures += 1
            print("   FAIL  no error was raised")

    show_balance(service, "e1", LeaveType.ANNUAL)
    print("   (unchanged: failed requests never touch the balance)")
    return failures


async def run_demo() -> int:
    service, inbox, email = build_service()
    with timed("full demo") as timer:
        await happy_path(service, inbox, email)
        failures = await edge_cases(service)

    heading("RESULT")
    if failures:
        print(f"{failures} of 5 edge cases did NOT behave as expected.")
    else:
        print("Happy path completed and all 5 edge cases raised the right exception.")
    print(f"Total time: {timer.elapsed_ms:.1f} ms")
    return failures


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    verbose = "--verbose" in argv or "-v" in argv
    logging.basicConfig(
        level=logging.INFO if verbose else logging.ERROR,
        format="   [log] %(message)s",
    )
    failures = asyncio.run(run_demo())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())