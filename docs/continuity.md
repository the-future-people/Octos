# Octos — Continuity

**Current as of 29 September 2026.**

This is the state-of-play document. Paste it at the start of a session.
It gets rewritten as things change, not appended to forever — history
lives in git, reasoning lives in `docs/decisions.md`, and rules that
stop repeats live in `tasks/lessons.md`.

---

## Where things stand

**Two machines.** Work: `OneDrive\Documents\The Future People\Octos-1`
and the doubled `octos-web\octos-web`. Home:
`Desktop\The_Future_People_Explorations\Octos` and `octos-web`.

**Home database is empty of usable data** — no branch, no users. Seed
created permissions and roles only. Tests run fine there (Django builds
its own test database); anything needing real data does not. The
decision between hand-seeding and restoring a production dump is still
open.

**Production:** Railway (backend), Vercel (frontend). Westland is the
only live branch. Every job in the database is INSTANT; no production or
design job has ever run.

**Tests:** 135 across finance, jobs and analytics. Run them with

```
docker-compose --env-file .env.docker exec web python manage.py test apps.finance.tests apps.jobs.tests apps.analytics.tests -v 1 --keepdb
```

`apps/` has no `__init__.py`, so `test apps.finance` fails discovery —
always name the module (`apps.finance.tests`).

---

## Shipped in the 28–29 September sessions

### Payment method registry

`apps/finance/payment_methods.py` is the single source of truth for what
a payment method is. Migrated onto it, each with tests pinning the
numbers before and after:

- `SheetEngine._snapshot_totals` — frozen sheet totals
- `get_revenue_breakdown`, `get_cashier_summary` — revenue selectors
- `SheetSummaryService._live_revenue` — the live portal figures
- `EODService.get_summary` — end-of-day summary
- `DailySalesSheet.total_collected`, `WeeklyReport.total_collected`
- `CashierPaymentSerializer`, `CreditSettleSerializer`,
  `CreditSettlementSerializer` — choices and reference validation
- `CreditEngine.settle`, `ReceiptEngine.issue` — engine validation

**`ONLINE` is registered and live in production.** Migration `0031` adds
`total_online` to `DailySalesSheet` and `WeeklyReport`. Nothing writes an
online receipt yet — there is no payment integration — but the
accounting is ready.

### Cashier queue split

Instant and processed as separate tabs, filtered server-side by
`job_type` with counts for both, filled-active toggle with bolt and
printer icons. Live.

`derive_job_type()` now decides a job's type from its services at every
creation path: `save_draft`, the late-job path, `proforma_engine`, and
the API serializer (where `job_type` became read-only). Design services
are refused at intake.

### PDFs

All five builders are now plain functions in `pdf/` folders, on one
palette (`apps/core/pdf/base.py`), each with a render test:

| Document | Where it lives |
|---|---|
| Day sheet | `finance/pdf/sheet_pdf.py` |
| Weekly filing | `finance/pdf/weekly_report_pdf.py` |
| Invoice | `finance/pdf/invoice_pdf.py` |
| Branch statement | `finance/pdf/branch_statement_pdf.py` |
| Proforma | `jobs/pdf/proforma_pdf.py` |
| Monthly close | still inside `monthly_close_engine.py` |

`views.py` went from 4,126 lines to 3,464. `close_service.py` — 1,071
lines, byte-identical to `monthly_close_engine.py`, imported by nothing
— was deleted.

### Fixes

- **Credit signal double-count.** `_credit_signal` subtracted
  `settled_today` from a `current_balance` that already excluded it.
  Fixed, with regression tests.
- **`make_sheet` test fixture** counted calendar days then stepped off
  Sunday, so two values collided on Mondays only.
- **`from pdb import pm`** removed from three files.
- **Michael Dwumfour's job 4910** recorded by hand: 200 cash, 309 to
  credit account 5, all axes settled.

---

## Outstanding

### Blocks real work

- **The payment modal has no credit option at all.** The backend has
  handled full and partial credit since the tests were written; the
  counter has never had a way to send it. This is what forced a manual
  shell entry on 24 September.
- **`deposit_percentage` accepts only 70 or 100**, so an arbitrary
  part-payment (200 of 509) cannot be entered from the counter.
- **`balance_due` ignores partial credit** — job 4910 reads 309 owing
  while the same 309 sits on the credit account. The debt shows twice.

### Known gaps

- **Creating a credit account has no portal flow.** Every one lands in
  the shell with no approval trail, despite `nominated_by` and
  `approved_by` existing.
- **The weekly filing's low-stock alert lists seven machines every
  week** — printers and monitors are in inventory as consumables with
  opening 0. A flag that fires every week is not a flag, and it buries
  the two real ones.
- **Branch Manager Notes renders `--`** when empty instead of being
  omitted.
- **September's monthly close** is still SUBMITTED in error, submitted
  on the 5th with 25 days of the month to come. The reset was written,
  never run.
- **`power cut` missing from `JobHalt.Reason`.**
- **Machine down/up has an API, a service and no UI.**
- **Info strip shows em-dashes** for ON THE FLOOR and MACHINES.
- **No UI to file a past week.**
- **Generic serializer contract test** — walk every `ModelSerializer`
  and build it. The declared-but-missing fault has happened five times.
- **`agreed_terms` choices** were inferred, never confirmed.
- **`FLOW_COORDINATOR` and the six finance roles** exist only in
  production, not in version control.
- **Monthly close PDF** is the last builder still inside its engine.
- **`pypdf`** is used for sheet PDF encryption despite the standing note
  against it.

### Carried forward

Postgres password rotation; no way to undo a proforma acceptance; Sunday
block bypassed in `SheetEngine.get_or_open_today()`; S3-compatible
storage (Cloudflare R2), which the signed-URL work made a configuration
change rather than a rewrite.

---

## Next

**Print Octos — the customer-facing online ordering workflow.** The
design is settled in `docs/decisions.md`; nothing is built. Open
questions that block it:

- Which sheet a payment at 23:40 or on a Sunday lands on
- Fees and settlement — ~1.95%, gross with fees separate, batch payouts
  reconciled against receipts, with no owner yet
- Refunds and chargebacks after a monthly close
- A deposit paid online and a balance paid in branch, on different
  sheets
- Webhook idempotency — the webhook marks a job paid, not the customer
  returning to the page
- **A job that belongs to nobody** — every job today is created at a
  branch by a member of staff. An online order arrives owned by no one
  and only becomes a branch's job once routing and payment settle. That
  is a new state ahead of `RECEIVED`, and the foundation the rest sits
  on.

**Also queued:** the coordinator's own sign-off, splitting
`FLOW_COORDINATOR` into incoming and outgoing with a shift end time for
each, and the prediction engine's Phase 1 (forecast logging, the two
deletions, the corrected variance analysis).

---

## Session close — not optional

All three documents get updated before a session ends:

- **`docs/continuity.md`** — this file, where things stand
- **`tasks/lessons.md`** — rules that stop repeats (append only)
- **`docs/decisions.md`** — why things are the way they are

`tasks/` is gitignored except for `lessons.md`, which is un-ignored so
it travels between machines. That gitignore line is why the lessons file
went unwritten for weeks.