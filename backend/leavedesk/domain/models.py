"""Domain models."""
"""Pydantic models for LeaveDesk.

Validators raise ValueError, which Pydantic reports as a ValidationError.
LeaveService.apply will convert that into InvalidLeaveRequestError.
"""

import re
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leavedesk.domain.exceptions import InvalidTransitionError

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_REASON_LENGTH = 5
MAX_REASON_LENGTH = 500
SATURDAY = 5  # date.weekday(): Monday is 0 and Sunday is 6


class LeaveType(str, Enum):
    ANNUAL = "ANNUAL"
    SICK = "SICK"
    CASUAL = "CASUAL"


class LeaveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DayPart(str, Enum):
    FULL = "FULL"
    AM = "AM"
    PM = "PM"


# The status changes allowed by section 2 of the spec.
ALLOWED_TRANSITIONS = {
    LeaveStatus.PENDING: {
        LeaveStatus.APPROVED,
        LeaveStatus.REJECTED,
        LeaveStatus.CANCELLED,
    },
    LeaveStatus.APPROVED: {LeaveStatus.CANCELLED},
    LeaveStatus.REJECTED: set(),
    LeaveStatus.CANCELLED: set(),
}


class Employee(BaseModel):
    # Run validators again when a field is changed after creation.
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(min_length=1)
    name: str
    email: str
    manager_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def email_looks_valid(cls, value: str) -> str:
        value = value.strip()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("email must look like name@domain.tld")
        return value

    @model_validator(mode="after")
    def employee_is_not_own_manager(self) -> "Employee":
        if self.manager_id == self.id:
            raise ValueError("an employee cannot be their own manager")
        return self


class Manager(Employee):
    """A Manager is an Employee who can act on direct reports' requests."""

    def manages(self, employee: Employee) -> bool:
        return employee.manager_id == self.id


class LeaveRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    leave_type: LeaveType
    start_date: date
    end_date: date
    day_part: DayPart = DayPart.FULL
    reason: str
    status: LeaveStatus = LeaveStatus.PENDING
    days: float = Field(default=0, ge=0)
    decision_note: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def reason_has_valid_length(cls, value: str) -> str:
        value = value.strip()
        if not MIN_REASON_LENGTH <= len(value) <= MAX_REASON_LENGTH:
            raise ValueError(
                f"reason must be {MIN_REASON_LENGTH} to "
                f"{MAX_REASON_LENGTH} characters"
            )
        return value

    @model_validator(mode="after")
    def dates_are_valid(self) -> "LeaveRequest":
        if self.end_date < self.start_date:
            raise ValueError("end date cannot be before start date")

        if self.day_part is not DayPart.FULL:
            if self.start_date != self.end_date:
                raise ValueError("a half-day must be a single date")
            if self.start_date.weekday() >= SATURDAY:
                raise ValueError("a half-day must be on a weekday")

        return self

    def transition_to(
        self, new_status: LeaveStatus, today: Optional[date] = None
    ) -> None:
        """Change status, or raise InvalidTransitionError if not allowed.

        Tests can pass today so the result does not depend on the real date.
        """
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"cannot change {self.status.value} to {new_status.value}"
            )

        today = today or date.today()
        leave_has_started = today >= self.start_date
        if (
            self.status is LeaveStatus.APPROVED
            and new_status is LeaveStatus.CANCELLED
            and leave_has_started
        ):
            raise InvalidTransitionError(
                "approved leave cannot be cancelled after it has started"
            )

        self.status = new_status