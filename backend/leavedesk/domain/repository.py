"""Storage for LeaveDesk.

LeaveService only talks to the abstract LeaveRepository, so the in-memory
version can later be swapped for a database without changing the service.
"""

from abc import ABC, abstractmethod
from itertools import count
from typing import Optional

from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.models import Employee, LeaveRequest, LeaveType
from leavedesk.domain.policies import LeaveBalance


class LeaveRepository(ABC):
    @abstractmethod
    def add_employee(self, employee: Employee) -> None: ...

    @abstractmethod
    def get_employee(self, employee_id: str) -> Employee: ...

    @abstractmethod
    def next_request_id(self) -> str: ...

    @abstractmethod
    def save_request(self, request: LeaveRequest) -> None: ...

    @abstractmethod
    def get_request(self, request_id: str) -> LeaveRequest: ...

    @abstractmethod
    def requests_for(self, employee_id: str) -> list[LeaveRequest]: ...

    @abstractmethod
    def find_balance(
        self, employee_id: str, leave_type: LeaveType
    ) -> Optional[LeaveBalance]: ...

    @abstractmethod
    def save_balance(self, balance: LeaveBalance) -> None: ...


class InMemoryLeaveRepository(LeaveRepository):
    """Keeps everything in dictionaries. Data is lost when the program ends."""

    def __init__(self) -> None:
        self._employees: dict[str, Employee] = {}
        self._requests: dict[str, LeaveRequest] = {}
        self._balances: dict[tuple[str, LeaveType], LeaveBalance] = {}
        self._ids = count(1)

    def add_employee(self, employee: Employee) -> None:
        self._employees[employee.id] = employee

    def get_employee(self, employee_id: str) -> Employee:
        try:
            return self._employees[employee_id]
        except KeyError:
            raise NotFoundError(f"no employee with id {employee_id}") from None

    def next_request_id(self) -> str:
        return f"LR-{next(self._ids)}"

    def save_request(self, request: LeaveRequest) -> None:
        self._requests[request.id] = request

    def get_request(self, request_id: str) -> LeaveRequest:
        try:
            return self._requests[request_id]
        except KeyError:
            raise NotFoundError(f"no leave request with id {request_id}") from None

    def requests_for(self, employee_id: str) -> list[LeaveRequest]:
        return [
            request
            for request in self._requests.values()
            if request.employee_id == employee_id
        ]

    def find_balance(
        self, employee_id: str, leave_type: LeaveType
    ) -> Optional[LeaveBalance]:
        return self._balances.get((employee_id, leave_type))

    def save_balance(self, balance: LeaveBalance) -> None:
        self._balances[(balance.employee_id, balance.leave_type)] = balance