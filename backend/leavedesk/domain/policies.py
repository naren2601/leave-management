"""Leave balances and the rules for each leave type."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    PolicyViolationError,
)
from leavedesk.domain.models import LeaveRequest, LeaveType


@dataclass
class LeaveBalance:
    """How many days of one leave type an employee has.

    Pending days are reserved when a request is submitted, so two pending
    requests cannot spend the same days.
    """

    employee_id: str
    leave_type: LeaveType
    entitled: float
    used: float = 0
    pending: float = 0

    @property
    def available(self) -> float:
        return self.entitled - self.used - self.pending

    def reserve(self, days: float) -> None:
        """Hold days for a new PENDING request."""
        self._check_positive(days)
        if days > self.available:
            raise InsufficientBalanceError(
                f"requested {days} days but only {self.available} available"
            )
        self.pending += days

    def release_pending(self, days: float) -> None:
        """Give back days from a rejected or cancelled PENDING request."""
        self._check_positive(days)
        self.pending -= days

    def confirm(self, days: float) -> None:
        """Move days from pending to used when a request is approved."""
        self._check_positive(days)
        self.pending -= days
        self.used += days

    def restore_used(self, days: float) -> None:
        """Give back days from a cancelled APPROVED request."""
        self._check_positive(days)
        self.used -= days

    @staticmethod
    def _check_positive(days: float) -> None:
        if days <= 0:
            raise InvalidLeaveRequestError("days must be more than zero")


class LeavePolicy(ABC):
    """The rules for one leave type. Each subclass sets its own limits."""

    leave_type: LeaveType
    days_per_year: float

    def new_balance(self, employee_id: str) -> LeaveBalance:
        return LeaveBalance(employee_id, self.leave_type, self.days_per_year)

    def validate(self, request: LeaveRequest, today: date) -> None:
        """Raise PolicyViolationError if the request breaks a rule."""
        if request.leave_type is not self.leave_type:
            raise PolicyViolationError(
                f"{type(self).__name__} cannot check "
                f"{request.leave_type.value} leave"
            )
        self.check_rules(request, today)

    @abstractmethod
    def check_rules(self, request: LeaveRequest, today: date) -> None:
        """The rules specific to this leave type."""


class AnnualLeavePolicy(LeavePolicy):
    leave_type = LeaveType.ANNUAL
    days_per_year = 18
    notice_days = 3

    def check_rules(self, request: LeaveRequest, today: date) -> None:
        earliest_start = today + timedelta(days=self.notice_days)
        if request.start_date < earliest_start:
            raise PolicyViolationError(
                f"annual leave needs at least {self.notice_days} days' notice"
            )


class SickLeavePolicy(LeavePolicy):
    leave_type = LeaveType.SICK
    days_per_year = 10
    max_backdate_days = 7

    def check_rules(self, request: LeaveRequest, today: date) -> None:
        earliest_start = today - timedelta(days=self.max_backdate_days)
        if request.start_date < earliest_start:
            raise PolicyViolationError(
                f"sick leave can be backdated by at most "
                f"{self.max_backdate_days} days"
            )


class CasualLeavePolicy(LeavePolicy):
    leave_type = LeaveType.CASUAL
    days_per_year = 6
    max_days_per_request = 2

    def check_rules(self, request: LeaveRequest, today: date) -> None:
        if request.start_date < today:
            raise PolicyViolationError("casual leave cannot start in the past")
        # request.days must already be set by the service.
        if request.days > self.max_days_per_request:
            raise PolicyViolationError(
                f"casual leave is at most {self.max_days_per_request} "
                f"working days per request"
            )


def default_policies() -> dict[LeaveType, LeavePolicy]:
    """One policy per leave type, for LeaveService to use."""
    return {
        LeaveType.ANNUAL: AnnualLeavePolicy(),
        LeaveType.SICK: SickLeavePolicy(),
        LeaveType.CASUAL: CasualLeavePolicy(),
    }