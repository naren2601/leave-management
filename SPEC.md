# LeaveDesk REST API: Specification

Capstone 2. This API puts the Day 1 domain package (`leavedesk/domain/`) behind FastAPI.
Storage stays in memory behind `LeaveRepository`, so Day 3 can swap in PostgreSQL
without changing the API.

**Status:** draft for trainer approval. No code is written until this is approved.

## 1. Conventions

- Base URL: `http://localhost:8000`. Swagger docs at `/docs`.
- Bodies are JSON. Dates are ISO `YYYY-MM-DD`. Leave types are `ANNUAL`, `SICK`, `CASUAL`.
  Day parts are `FULL`, `AM`, `PM`. Statuses are `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`.
- Every route except `POST /auth/login` and `GET /health` needs
  `Authorization: Bearer <token>`.
- Every response has an `X-Request-ID` header. If the client sends one, it is reused.
- Lists are paginated with `limit` (1 to 100, default 20) and `offset` (default 0) and return:

```json
{ "items": [ ... ], "total": 42, "limit": 20, "offset": 0 }
```

## 2. Authentication

- `POST /auth/login` returns a JWT access token signed with HS256. The secret comes from
  the `JWT_SECRET` environment variable and is never committed.
- Token claims: `sub` (employee id), `role` (`employee` or `manager`), `exp` (30 minutes).
- Passwords are stored as Argon2id hashes. Plaintext is never stored or logged.
- A wrong email and a wrong password return the **same** 401 message, so the API does not
  reveal which emails exist.
- `GET /notifications/stream` also accepts `?access_token=<token>`, because the browser's
  `EventSource` cannot send headers. This is the only route that accepts a query token.
- Out of scope today: refresh tokens and account lockout (lockout is Day 3, Part D).

## 3. Endpoints

### Auth and health

| Method | Path | Who | Request | Response | Status codes |
|---|---|---|---|---|---|
| GET | `/health` | Anyone | — | `{"status": "ok"}` | 200 |
| POST | `/auth/login` | Anyone | `{email, password}` | `{access_token, token_type: "bearer", expires_in}` | 200, 401, 422 |

### Leave

| Method | Path | Who | Request | Response | Status codes |
|---|---|---|---|---|---|
| GET | `/employees/{id}/balance` | Self, or that employee's manager | — | List of `Balance` | 200, 401, 403, 404 |
| POST | `/leave-requests` | Employee (applies for self) | `ApplyLeave` | `LeaveRequest` | 201, 401, 409, 422 |
| GET | `/leave-requests` | Employee or manager | Query: `status`, `employee_id`, `sort`, `limit`, `offset` | Page of `LeaveRequest` | 200, 401, 403, 422 |
| GET | `/leave-requests/{id}` | Owner or their manager | — | `LeaveRequest` | 200, 401, 404 |
| POST | `/leave-requests/{id}/approve` | The owner's manager | — | `LeaveRequest` | 200, 401, 403, 404, 409 |
| POST | `/leave-requests/{id}/reject` | The owner's manager | `{reason}` | `LeaveRequest` | 200, 401, 403, 404, 409, 422 |
| DELETE | `/leave-requests/{id}` | Owner | — | `LeaveRequest` (now `CANCELLED`) | 200, 401, 403, 404, 409 |

Rules:
- **List visibility:** an employee sees only their own requests. A manager sees their own
  and their direct reports'. Filtering by an `employee_id` you cannot see returns 403.
- **Sorting:** `sort` is `start_date` (default) or `-start_date`.
- **Get by id:** a request you cannot see returns **404, not 403**, so ids of other
  people's requests are not revealed.
- **Cancel:** the API cancels `PENDING` requests only, as the workshop plan says. Cancelling
  any other status returns 409. (The domain can also cancel approved leave before it
  starts; the API does not expose that today.)
- **DELETE returns 200 with the request**, not 204, so the client sees the new status.

### Notifications

| Method | Path | Who | Request | Response | Status codes |
|---|---|---|---|---|---|
| GET | `/notifications` | Self | Query: `unread`, `limit`, `offset` | Page of `Notification`, unread first, then newest first | 200, 401, 422 |
| POST | `/notifications/{id}/read` | Owner | — | `Notification` | 200, 401, 404 |
| POST | `/notifications/read-all` | Self | — | `{"updated": 3}` | 200, 401 |
| GET | `/notifications/stream` | Self | Query: `access_token` | `text/event-stream` | 200, 401 |

- `POST /notifications/{id}/read` on someone else's notification returns 404.
- The stream sends one `event: notification` per new notification, with the
  `Notification` JSON as `data`. It sends a `: keep-alive` comment every 15 seconds.

### Background notifications

Submit, approve, reject and cancel save the change, then queue the Day 1 notifier with
FastAPI `BackgroundTasks`. The response is sent **before** notifications go out.
A failed notification never changes the response or undoes the action.

## 4. Schemas

```text
ApplyLeave    { leave_type, start_date, end_date, day_part = "FULL", reason }
LeaveRequest  { id, employee_id, leave_type, start_date, end_date, day_part,
                reason, status, days, decision_note }
Balance       { leave_type, entitled, used, pending, available }
Notification  { id, recipient, event, message, read, created_at }
```

`Notification` gains `id` and `created_at` (ISO date-time) compared with Day 1, so it can be
addressed by URL and sorted. `SPEC.md` will be updated to match.

## 5. Error contract

Every error, from 400 to 422, has the same JSON shape:

```json
{
  "error": {
    "code": "OVERLAPPING_LEAVE",
    "message": "these dates overlap request LR-1 (2026-11-16 to 2026-11-18, APPROVED)",
    "request_id": "6f1c2a9e-...",
    "details": []
  }
}
```

`details` lists field problems for 422 validation errors, for example
`[{"field": "end_date", "problem": "end date cannot be before start date"}]`.
It is empty otherwise.

| Status | `code` | When |
|---|---|---|
| 400 | `BAD_REQUEST` | The body is not valid JSON |
| 401 | `UNAUTHORIZED` | Missing, invalid or expired token; wrong email or password |
| 403 | `FORBIDDEN` | `NotAuthorizedError`, or an employee calls a manager-only route |
| 404 | `NOT_FOUND` | `NotFoundError`, or a resource you are not allowed to see |
| 409 | `OVERLAPPING_LEAVE` | `OverlappingLeaveError` |
| 409 | `INVALID_TRANSITION` | `InvalidTransitionError`, for example approving twice |
| 422 | `VALIDATION_ERROR` | A missing or badly typed field, or `InvalidLeaveRequestError` |
| 422 | `POLICY_VIOLATION` | `PolicyViolationError`, for example too little notice |
| 422 | `INSUFFICIENT_BALANCE` | `InsufficientBalanceError` |
| 500 | `INTERNAL_ERROR` | Anything unexpected. The message is generic; details go to the log only |

## 6. Acceptance criteria

Each one becomes at least one pytest test using FastAPI's `TestClient`.

| ID | Given / When | Then |
|---|---|---|
| API-1 | Correct email and password, `POST /auth/login` | 200 with a token whose `sub` is the employee id |
| API-2 | Wrong password, or an unknown email | 401 with the same message for both |
| API-3 | No token, or an expired token, on any protected route | 401 `UNAUTHORIZED` |
| API-4 | Valid request, `POST /leave-requests` | 201, status `PENDING`, `days` counted without weekends |
| API-5 | Dates overlap an active request | 409 `OVERLAPPING_LEAVE` |
| API-6 | End date before start date, or a weekend-only range | 422 `VALIDATION_ERROR` with `details` |
| API-7 | More days than available | 422 `INSUFFICIENT_BALANCE` |
| API-8 | Annual leave starting tomorrow | 422 `POLICY_VIOLATION` |
| API-9 | Employee lists requests | Only their own are returned |
| API-10 | Manager lists with `status=PENDING` | Only their reports' pending requests, sorted by start date |
| API-11 | Employee filters by another employee's id | 403 |
| API-12 | `limit=2&offset=2` | The right page, with the correct `total` |
| API-13 | Get a request that belongs to someone else | 404 |
| API-14 | Owner's manager approves a pending request | 200 `APPROVED`; balance moves from pending to used |
| API-15 | An employee, or a different manager, approves | 403, status unchanged |
| API-16 | Approve a request that is not pending | 409 `INVALID_TRANSITION` |
| API-17 | Reject with an empty reason | 422; status stays `PENDING` |
| API-18 | Owner cancels a pending request | 200 `CANCELLED`; days return to available |
| API-19 | Cancel an approved request, or someone else's | 409, or 403 |
| API-20 | Self or manager reads a balance; someone else does | 200 with all three types; or 403 |
| API-21 | Submit, approve, reject or cancel succeeds | A notification task was queued (notifier mocked) |
| API-22 | `GET /notifications?unread=true` | Only unread, newest first |
| API-23 | Mark someone else's notification read | 404 |
| API-24 | `POST /notifications/read-all` | Every notification is read; `updated` is the count |
| API-25 | Open the stream, then submit a request | A `notification` event arrives on the stream |
| API-26 | Any request | Response has `X-Request-ID`; the log line has method, path, status and duration |
| API-27 | An unexpected error inside a route | 500 `INTERNAL_ERROR` with no stack trace in the body |

## 7. Implementation plan

| # | Task | Files | Covers |
|---|---|---|---|
| 1 | App factory, settings from env with `pydantic-settings`, `.env.example`, `/health` | `api/main.py`, `api/settings.py` | — |
| 2 | Error contract: handlers for domain errors and validation errors | `api/errors.py` | API-6, 7, 8, 27 |
| 3 | Request-ID and logging middleware | `api/middleware.py` | API-26 |
| 4 | Users with Argon2id hashes, JWT, `current_user` and `require_manager` dependencies, login | `api/auth.py`, `api/routes/auth.py` | API-1, 2, 3 |
| 5 | Domain change: service returns notifications instead of sending them; notifications get `id` and `created_at` | `domain/service.py`, `domain/notifications.py` | API-21 |
| 6 | Leave and balance routes | `api/routes/leave.py`, `api/schemas.py` | API-4 to API-20 |
| 7 | Notification routes and SSE stream | `api/routes/notifications.py` | API-22 to API-25 |
| 8 | Tests with fixtures for an authenticated client and a mocked notifier | `tests/api/` | All |
| 9 | Ruff: `ruff check` and `ruff format --check` pass | `pyproject.toml` | — |
| 10 | Dockerfile and `docker-compose.yml` with `api` and `db` services | `Dockerfile`, `docker-compose.yml` | — |
| 11 | `AI_NOTES.md`, README and `SPEC.md` updates | docs | — |

**Done when:** every acceptance criterion above has a passing test, and
`docker compose up` serves Swagger at `/docs` on a clean machine.
