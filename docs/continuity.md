# Octos — where things stand

Updated 13 October 2026, end of day. The storefront ran end to end on
real money this morning; the afternoon fixed what that exposed and built
the backend for a new coordinator portal.

Paste this at the start of a new session to pick up without
re-explaining.

---

## The short version

A customer can order printing online, pay, and watch it being made. The
money reaches the books, the job reaches the floor already paid, and the
customer is texted twice: when they pay, and when their order is ready.

The coordinator portal is being rebuilt. The design is locked, the
backend for it is live, and the page itself is next.

511 backend tests green.

---

## What changed today

**Online jobs are born paid** (`afa60b6`). Conversion wrote the legacy
`status` as `PENDING_PAYMENT`, which put every paid online job in the
cashier's queue, held day sheets open as debts, and counted them as owed
in EOD, weekly and monthly close. Now `status=PAID`, `job_type=PRODUCTION`
for every online job.

**Online jobs are SETTLED** on the payment axis. Conversion wrote
`payment_state='PAID'`, which is not a value on that axis (`UNPAID`,
`DEPOSIT_PAID`, `SETTLED`). Choices are not enforced on `create()`, so it
went in silently, and an attendant cannot release a job that is not
SETTLED. Every online customer would have been turned away at collection.
Migrations 0036 and 0037 corrected existing rows.

**Clearing a job puts it in press** (`f3de464`, fixed in `9d77608`).
`verify()` only recorded a verification, so a cleared job sat at
RECEIVED ("Waiting") with a second Start to press, and the customer's
tracking still said "inspecting". Now `verify()` moves a paid production
job to IN_PRODUCTION through `move_work`, so the status log, tracking and
timing all see it. Unpaid remote jobs and instant work stay at RECEIVED.
The first version failed in production: views prefetch verifications, so
`is_verified` answered from a stale list. Fixed with
`refresh_from_db(fields=['verifications'])`.

**The ready text** (`8cef6c1`). Reaching DONE queues
`tell_customer_ready` on commit, through the worker. Online orders only.

**The strict arrivals queue and inspection claims** (`5da17fb`,
`b1808c1`). See the coordinator portal section.

**Data corrected in production:** 14 online jobs settled and moved out
of the cashier's queue (5 of them pre-dated the ONLINE channel and were
labelled WALK_IN), 12 test jobs finished, and FP-WLB-2026-05309 cancelled
as entered in error.

---

## How an online order flows

1. Customer specifies, checks artwork, pays through Paystack.
2. The webhook verifies, records a `PaystackEvent`, marks the order paid
   and queues `convert_order`.
3. Conversion in the worker creates the Job: PRODUCTION, `status=PAID`,
   `payment_state=SETTLED`, `work_state=RECEIVED`, `intake_channel=ONLINE`,
   `estimated_ready_at` from the storefront's promise. Writes the receipt,
   attaches to today's sheet, texts the customer.
4. The job appears in the coordinator's arrivals queue.
5. The coordinator takes it (claim), inspects, clears: it goes straight
   to IN_PRODUCTION and the customer's tracking moves to press.
6. Finishing, then quality check, then DONE: the customer gets the ready
   text.
7. The attendant releases it at collection (it is SETTLED, so allowed).

The cashier has no part in online jobs.

---

## The coordinator portal

**Design (locked, mocked and agreed):**

- Existing frame kept: header, info strip, sidebar.
- A named dot stepper across the top: Arrived → In press → Finishing →
  Ready, with Held apart (dashed, off the line). The selected stage rolls
  out into a dark pill; only its jobs show. Late and at-risk shown by dot
  colour.
- Arrived is a strict queue: the head job is sharp with Inspect; jobs
  behind are blurred and faded with up-arrows; clearing slides the head
  out toward In press and the rest glide up. Nobody chooses; they take
  what is next.
- Inspection is a wide modal, file-led (about 60% width): preview with
  zoom, the order, the customer's words, promised vs floor, four checks
  (size and resolution automatic, quantity/finishing and content ticked
  by hand). Clear refuses until all four are ticked.
- Mark ready opens a confirmation in the same pattern with the count
  check. Opening it moves FINISHING → QUALITY_CHECK; confirming moves to
  DONE. The quality check is the modal.

**Backend (live):**

- `apps/jobs/services/inspection.py` is the single source of truth:
  `current_promise()`, `arrival_queue()` (soonest promise first, ties to
  first arrival, unpromised last, held out), `next_up()`, `claim()`,
  `release()`. Claims lapse after 10 minutes.
- `Job.inspecting_by`, `Job.inspecting_since` (migration 0038).
- `GET coordinator/verification-queue/`: each job has `is_next`,
  `inspecting_by_name`, `inspecting_is_me`, `promise`, `late`, `at_risk`.
- `POST jobs/<pk>/inspect/` claims or refreshes (409 if held by someone
  else or out of turn). `POST jobs/<pk>/inspect/release/` frees your own.
- Clearing and suspending release the claim.
- `GET coordinator/board/` gains a `READY` column and promise flags. Old
  keys are unchanged so the current page keeps working.

**Frontend (next):** see `tasks/todo.md`, Phase 3.

---

## Where the code lives

**Backend**

- `apps/storefront/` — views, `services/conversion.py`,
  `services/messages.py`, `tasks.py` (`convert_order`,
  `tell_customer_ready`), `tests_conversion.py`, `tests_ready.py`
- `apps/jobs/status_engine.py` — `verify()`, `move_work()`, `_move_axis()`
  (DONE queues the ready text)
- `apps/jobs/services/inspection.py` — the queue and claims
- `apps/jobs/api/coordinator_views.py` — queue, board, claim, release,
  verify, suspend
- `apps/jobs/tests_inspection.py`, `apps/jobs/tests_coordinator_api.py`

**Frontend** — `octos-web` repo: `src/components/coordinator/ProductionBoard.jsx`
(being replaced), `src/pages/coordinator/CoordinatorPortal.jsx`,
`src/api/coordinator.js`. Storefront is the `print-octos` repo.

---

## Running the tests

`apps` is a namespace package, so Django cannot discover from it. Build
the labels fresh before every full run (a stale list silently skips new
test files), and leave out `apps.inventory.tests`, which is a folder:

    $root = (Get-Location).Path + '\'
    $labels = Get-ChildItem -Recurse -Path apps -Include test*.py,tests*.py |
      ForEach-Object { $_.FullName.Replace($root, '').Replace('.py', '').Replace('\', '.') } |
      Where-Object { $_ -ne 'apps.inventory.tests' }
    docker-compose --env-file .env.docker exec -T web python manage.py test @labels --noinput

---

## What's wrong right now

- **Promises only exist for online orders.** Counter jobs get no
  `estimated_ready_at`, so they can never show as late.
- **Print timings will drift long.** Clearing now means "in press", so
  queue time behind a running job counts as printing until operators
  mark the real start.
- **The current workspace reads `deadline` as "Promised".** That is the
  customer's wish, not Octos's promise. The new page reads
  `estimated_ready_at`.
- **Business cards are priced per card** — GHS 3,000 for 100.
- **Em-dashes are mangled to `???`** in catalogue descriptions.
- **`full_total` is never set at commit** — checkout shows "Items: GHS 0.00".
- **`original_filename` stores the device's name** (an iPhone UUID).
- **The first-name field on checkout** shows what was typed, not what the
  server returned.
- **`apps.inventory.tests`** cannot be run by label (folder without
  `__init__.py`).

---

## Decisions worth not relitigating

Earlier ones still stand (nothing reaches the server until Continue; the
confirmation page is the destination; nothing load-bearing in browser
storage; `intake_by` and `cashier` empty on online work; quality check
folds into finishing for the customer; each payment attempt gets its own
reference; media on R2). Today's are in `docs/decisions.md`.