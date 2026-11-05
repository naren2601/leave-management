"""Custom exceptions for LeaveDesk.

Every error inherits from LeaveDeskError, so callers can catch one specific
error or all LeaveDesk errors at once.
"""


class LeaveDeskError(Exception):
    """Base class for every LeaveDesk error."""


class InvalidLeaveRequestError(LeaveDeskError):
    """The request data is invalid, such as bad dates or a short reason."""


class PolicyViolationError(LeaveDeskError):
    """The request breaks a rule of its leave type."""


class InsufficientBalanceError(LeaveDeskError):
    """The employee does not have enough leave available."""


class OverlappingLeaveError(LeaveDeskError):
    """The dates clash with a PENDING or APPROVED request."""


class InvalidTransitionError(LeaveDeskError):
    """The status change is not allowed."""


class NotAuthorizedError(LeaveDeskError):
    """The user is not allowed to perform this action."""


class NotFoundError(LeaveDeskError):
    """The employee or request id does not exist."""