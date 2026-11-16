"""Working-day calculation and overlap detection for LeaveDesk."""

from datetime import date, timedelta
from typing import Iterable, Optional

from leavedesk.domain.exceptions import InvalidLeaveRequestError
from leavedesk.domain.models import DayPart, LeaveRequest, LeaveStatus

SATURDAY = 5  # date.weekday(): Monday is 0 and Sunday is 6
HALF_DAY = 0.5

# Only these requests block new dates. REJECTED and CANCELLED do not.
ACTIVE_STATUSES = {LeaveStatus.PENDING, LeaveStatus.APPROVED}


def is_weekend(day: date) -> bool:
    return day.weekday() >= SATURDAY


def working_days(start: date, end: date) -> int:
    """Count Monday-to-Friday dates from start to end, including both."""
    if end < start:
        raise InvalidLeaveRequestError("end date cannot be before start date")

    count = 0
    day = start
    while day <= end:
        if not is_weekend(day):
            count += 1
        day += timedelta(days=1)
    return count


def count_leave_days(
    start: date, end: date, day_part: DayPart = DayPart.FULL
) -> float:
    """Return how many days a request costs: 0.5 for a half-day.

    Raises InvalidLeaveRequestError if the range has no working days,
    such as a request for only a Saturday and Sunday.
    """
    days = working_days(start, end)
    if days == 0:
        raise InvalidLeaveRequestError(
            "the dates contain no working days, only a weekend"
        )

    if day_part is DayPart.FULL:
        return float(days)
    return HALF_DAY


def requests_overlap(first: LeaveRequest, second: LeaveRequest) -> bool:
    """Return True if the two requests use any of the same time."""
    dates_touch = (
        first.start_date <= second.end_date
        and second.start_date <= first.end_date
    )
    if not dates_touch:
        return False

    # AM and PM on the same date do not clash. Any other mix does.
    both_half_days = (
        first.day_part is not DayPart.FULL
        and second.day_part is not DayPart.FULL
    )
    if both_half_days and first.day_part is not second.day_part:
        return False

    return True


def find_overlap(
    new_request: LeaveRequest, existing: Iterable[LeaveRequest]
) -> Optional[LeaveRequest]:
    """Return the first active request by the same employee that clashes."""
    for other in existing:
        if other.id == new_request.id:
            continue
        if other.employee_id != new_request.employee_id:
            continue
        if other.status not in ACTIVE_STATUSES:
            continue
        if requests_overlap(new_request, other):
            return other
    return None