# Octos — Continuity

**Current as of 29 September 2026, end of day.**

Paste this at the start of a session. It gets rewritten as things change,
not appended to — history lives in git, reasoning lives in
`docs/decisions.md`, and rules that stop repeats live in
`tasks/lessons.md`.

---

## Where things stand

**Two machines.** Work: `OneDrive\Documents\The Future People\Octos-1`
and the doubled `octos-web\octos-web`. Home:
`Desktop\The_Future_People_Explorations\Octos` and `octos-web`.

**Home database is empty of usable data** — no branch, no users. Tests
run fine there (Django builds its own test database); anything needing
real data does not. Hand-seed or restore a production dump: still open.

**Production:** Railway (backend), Vercel (frontend). Westland is the
only live branch.

**Tests:** 145 across finance, jobs and analytics.

```
docker-compose --env-file .env.docker exec web python manage.py test apps.finance.tests apps.jobs.tests apps.analytics.tests -v 1 --keepdb
```

`apps/` has no `__init__.py`, so `test apps.finance` fails discovery —
always name the module.

---

## Shipped 28–29 September

### Payment method registry

`apps/finance/payment_methods.py` is the single source of truth. Every
consumer that computes or validates reads it: sheet totals, revenue
breakdown, cashier summary, live revenue, EOD summary,
`total_collected` on both sheet and weekly report, three serializers,
and the credit and receipt engines.

**`ONLINE` is registered and live**, migration `0031` adding
`total_online` to `DailySalesSheet` and `WeeklyReport`. Nothing writes an
online receipt yet — there is no payment integration — but the accounting
is ready.

### Cashier queue split

Instant and processed as separate tabs, filtered server-side by
`job_type` with counts for both. Live.

`derive_job_type()` decides a job's type from its services at every
creation path. Design services are refused at intake.

### PDFs

Five builders, all plain functions in `pdf/` folders, all on one palette
(`apps/core/pdf/base.py`), all with render tests. `views.py` went from
4,126 lines to 3,464. `close_service.py` — 1,071 lines, byte-identical to
`monthly_close_engine.py`, imported by nothing — was deleted.

### Large-format pricing — the first correctly priced production work

- `square_feet()` and `quote_line()` in `apps/jobs/pricing_engine.py`
- `minimum_price` on `PricingRule`, migration `jobs.0030`
- **Flexy Banner** at GHS 3.25/sq ft and **SAV Sticker** at 2.80, both
  minimum GHS 10 per piece, seeded at Westland via
  `manage.py seed_large_format`
- The placeholder Banner Printing (flat GHS 50, never used) deleted with
  its six pricing rules
- `PriceCalculateView` quotes through `quote_line` and accepts any spec
  field
- `NewJobModal` renders `spec_template` and prices through the server

Verified on production: 168 × 150 flexy quotes at GHS 568.75.

### Fixes

- **Credit signal double-count** — `settled_today` subtracted from a
  balance that already excluded it
- **Area services ignored the piece count** — four banners priced as one
- **Two pricing implementations** — the browser had its own, already
  drifted
- **`make_sheet`** collided with itself on Mondays
- **`DeriveJobTypeTests`** failed after 19:30
- **`from pdb import pm`** removed from three files
- **Michael Dwumfour's job 4910** recorded by hand: 200 cash, 309 to
  credit account 5

---

## Outstanding

### Decisions needed before more building

- **A job has one `job_type`**, so a customer wanting photocopies and a
  banner together cannot have one job. The cart in `NewJobModal` empties
  when the tab changes, which is the symptom. Two jobs, or one job that
  waits for its slowest line?
- **The post-closing entry point** should probably replace the New Job
  modal after hours rather than sit beside it. Carries a required reason
  and produces `INTAKE_HELD`, so the after-hours version must say so.
  Trigger on the lock status, not a clock.
- **Small sticker tier bands.** The catalogue gives one point: 100 at
  GHS 280. Needs 1, 10, 50 and 500 to have a shape.

### Blocks real work

- **The payment modal has no credit option at all.** The backend has
  handled full and partial credit since the tests were written; the
  counter has never had a way to send it. This forced a manual shell
  entry on 24 September.
- **`deposit_percentage` accepts only 70 or 100**, so an arbitrary
  part-payment (200 of 509) cannot be entered from the counter.
- **`balance_due` ignores partial credit** — job 4910 reads 309 owing
  while the same 309 sits on the credit account.

### Known gaps

- **Creating a credit account has no portal flow.** Every one lands in
  the shell with no approval trail.
- **The weekly filing's low-stock alert lists seven machines every
  week** — printers and monitors are in inventory as consumables with
  opening 0. It buries the two real ones.
- **Branch Manager Notes renders `--`** when empty.
- **September's monthly close** is still SUBMITTED in error. Reset
  written, never run.
- **`power cut` missing from `JobHalt.Reason`.**
- **Machine down/up has an API, a service and no UI.**
- **Info strip shows em-dashes** for ON THE FLOOR and MACHINES.
- **No UI to file a past week.**
- **Generic serializer contract test** — walk every `ModelSerializer`.
- **`agreed_terms` choices** were inferred, never confirmed.
- **`FLOW_COORDINATOR` and the six finance roles** exist only in
  production.
- **Monthly close PDF** is the last builder still inside its engine.
- **`pypdf`** used for sheet PDF encryption despite the note against it.
- **`PER_LINEAR_M`** missing from `UNIT_CHOICES`; DTF film supply needs it.

### Carried forward

Postgres password rotation; no way to undo a proforma acceptance; Sunday
block bypassed in `SheetEngine.get_or_open_today()`; Cloudflare R2
storage, now a configuration change rather than a rewrite.

---

## Next

**The catalogue, in batches.** Flexy and SAV are done and prove the
pattern. The service catalogue drafted for the new building has roughly
seventy more across eight sections, most with prices still marked as
estimates. Add them in groups as each group's numbers firm up, starting
with what sells most. Three pricing shapes are still missing:
`PER_LINEAR_M`, a separate line for embroidery digitizing, and laser
engraving priced by machine minutes.

**Print Octos.** Design settled in `docs/decisions.md`, nothing built.
The build order:

1. Catalogue can describe a processed job — **done for flexy and SAV**
2. One quoting function — **done: `quote_line`**
3. `OnlineOrder` and lead identity, in `apps/storefront`
4. File checks
5. Routing, capacity hold, promised date
6. Payment and webhook — blocked on Hubtel vs Paystack and the HQ
   account structure
7. Conversion to a `Job` at a branch
8. Tracking, suspension, replacement uploads

Still unanswered from the design: which sheet a payment at 23:40 or on a
Sunday lands on; fees and settlement reconciliation; refunds after a
monthly close; a deposit online and a balance in branch on different
sheets; webhook idempotency.

**Also queued:** the coordinator's own sign-off and splitting
`FLOW_COORDINATOR` into incoming and outgoing; the prediction engine's
Phase 1 (forecast logging, the two deletions, the corrected variance
analysis); the Can-Do Sandbox.

---

## Session close — not optional

All three documents get updated before a session ends:

- **`docs/continuity.md`** — this file, where things stand
- **`tasks/lessons.md`** — rules that stop repeats (append only)
- **`docs/decisions.md`** — why things are the way they are

`tasks/` is gitignored except `lessons.md`. Note the gitignore shape:
`tasks/*` then `!tasks/lessons.md`. Ignoring the directory itself means
git never looks inside and the exception cannot apply.

# Octos — Continuity

**Current as of 1 October 2026, evening.**

Paste this at the start of a session. It gets rewritten as things change,
not appended to — history lives in git, reasoning lives in
`docs/decisions.md`, rules that stop repeats live in `tasks/lessons.md`.

---

## Where things stand

**Two machines.** Work: `OneDrive\Documents\The Future People\Octos-1`
and the doubled `octos-web\octos-web`. Home:
`Desktop\The_Future_People_Explorations\Octos` and `octos-web`.

**Home database is empty of usable data** — no branch, no users. Tests
run fine there; anything needing real data does not. Hand-seed or restore
a production dump: still open.

**Production:** Railway (backend), Vercel (frontend). Westland is the
only live branch.

**Tests: 201**, now across four apps. The storefront is easy to leave
out:

```
docker-compose --env-file .env.docker exec web python manage.py test apps.finance.tests apps.jobs.tests apps.analytics.tests apps.storefront.tests -v 1 --keepdb
```

---

## Print Octos — the build

1. **Catalogue can describe a processed job** — done for flexy and SAV
2. **One quoting function** — done: `quote_line`
3. **`OnlineOrder`, ordering API, identity** — done
4. **File checks** — done
5. **Routing and capacity hold** — not started
6. **Payment and webhook** — next. Paystack live since 29 September
7. **Conversion to a Job** — not started
8. **Tracking and suspension** — not started

### What exists now

`apps/storefront`, the first unauthenticated surface in Octos.

- `GET /api/v1/storefront/catalogue/` — services with spec templates
- `POST /orders/` — starts one, returns a number and a token
- `GET|PATCH /orders/<number>/` — read and build, priced server-side
- `POST /orders/<number>/identify/` — phone and first name
- `POST /orders/<number>/code/` — sets a code, applies the 5%

`OnlineOrder` numbers itself from a Postgres sequence. `Lead` holds a
hashed code. Order numbers are guessable so a random token is what opens
an order. Storefront throttle scopes: 90/min general, 6/min for identify.

`apps/storefront/services/sms.py` wraps mNotify behind one function —
account is set up, the call is written, not yet configured with a key.

### Still unanswered from the design

Which sheet a payment at 23:40 or on a Sunday lands on; fees and
settlement reconciliation; refunds after a monthly close; a deposit
online and a balance in branch on different sheets; webhook idempotency;
the HQ account structure and whether branches get sub-accounts.

---

## Shipped 28 September – 1 October

### Payment registry and ONLINE

`apps/finance/payment_methods.py` is the single source of truth. Every
consumer reads it. `ONLINE` is live with `total_online` on both the day
sheet and the weekly report. Nothing writes one yet.

### Large-format pricing

`square_feet()` and `quote_line()`; `minimum_price` on `PricingRule`.
**Flexy Banner** GHS 3.25/sq ft and **SAV Sticker** 2.80, minimum GHS 10
per piece, seeded company-wide. The placeholder Banner Printing (flat
GHS 50, never used) deleted.

`NewJobModal` renders `spec_template` and prices through the server. The
browser no longer calculates prices at all.

### File measurement and checks

PDFs now report the effective resolution of each image they contain,
with `dpi` holding the worst of those covering enough of the page to
matter, and nothing at all for vector art.

`apps/jobs/services/file_checks.py` turns measurements into fine, warn or
refuse against what was ordered. Thresholds follow the output size: 250
dpi fine on a card, 72 on a banner.

### The coordinator sees only paid work

Both the production board and the verification queue exclude UNPAID. The
engine already refused to start an unpaid job, but refusing at the Start
button meant he had already opened it.

### Pricing cleanup — 1 October

127 branch rules deleted, 20 company rules created to replace the ones
that only existed per branch. **A3 Binding had been charging 20 for every
spine size** because a branch rule without tiers was overriding the
company rule that had them.

### PDFs

Five builders in `pdf/` folders, one palette, render tests. `views.py`
4,126 → 3,464 lines. `close_service.py` (1,071 lines, byte-identical
duplicate) deleted.

---

## Outstanding

### Costing money

- **Three jobs undercharged on 1 October** — 04996, 05000, 05001, about
  GHS 82 — by the page-count bug. COMPLETE with receipts issued. Absorb
  or call the customers?
- **The payment modal has no credit option.** The backend has handled
  full and partial credit since the tests were written; the counter has
  never had a way to send it.
- **`deposit_percentage` accepts only 70 or 100**, so an arbitrary
  part-payment cannot be entered.
- **`balance_due` ignores partial credit** — job 4910 shows 309 owing
  while the same 309 sits on the credit account.

### Decisions waiting

- **A job has one `job_type`**, so photocopies and a banner together
  cannot be one job. The cart empties when the tab changes. Two jobs, or
  one that waits for its slowest line?
- **The post-closing entry point** should replace the New Job modal after
  hours rather than sit beside it. Trigger on lock status, not a clock.
- **Small sticker tier bands.** One known point: 100 at GHS 280.
- **The attendant cannot attach a file at intake**, so a WhatsApp job
  reaches the coordinator with nothing to open. The same file checks
  should run there as online.

### Known gaps

- Creating a credit account has no portal flow
- The weekly filing's low-stock alert lists seven machines every week
- Branch Manager Notes renders `--` when empty
- September's monthly close is still SUBMITTED in error
- `power cut` missing from `JobHalt.Reason`
- Machine down/up has an API, a service and no UI
- Info strip shows em-dashes for ON THE FLOOR and MACHINES
- No UI to file a past week
- Generic serializer contract test
- `agreed_terms` choices were inferred, never confirmed
- `FLOW_COORDINATOR` and the six finance roles exist only in production
- Monthly close PDF is the last builder still inside its engine
- `PER_LINEAR_M` missing from `UNIT_CHOICES`; DTF film needs it
- Receipt numbering has the same race as the proforma
- Images nested in form XObjects are skipped by the PDF reader

### Carried forward

Postgres password rotation; no way to undo a proforma acceptance; Sunday
block bypassed in `SheetEngine.get_or_open_today()`; Cloudflare R2.

---

## Also queued

The catalogue in batches — seventy services across eight sections, most
with prices still marked as estimates. Three pricing shapes missing:
`PER_LINEAR_M`, embroidery digitizing as its own line, laser engraving by
machine minutes.

The coordinator's own sign-off, and splitting `FLOW_COORDINATOR` into
incoming and outgoing. The prediction engine's Phase 1. The Can-Do
Sandbox.

---

## Session close — not optional

- **`docs/continuity.md`** — this file
- **`tasks/lessons.md`** — rules that stop repeats (append only)
- **`docs/decisions.md`** — why things are the way they are

`tasks/` is gitignored except `lessons.md`: `tasks/*` then
`!tasks/lessons.md`. Ignoring the directory itself means git never looks
inside and the exception cannot apply.