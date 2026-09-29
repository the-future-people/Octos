# Decisions

Why things are the way they are. Written so settled questions are not
re-litigated. Each entry says what was decided, and the reasoning that
made it the answer — the reasoning matters more than the conclusion,
because it is what tells you whether a new case is covered.

---

## Payments

### Payment methods live in one registry

`apps/finance/payment_methods.py` declares each method once, with what
the rest of the system asks about it: is it in the till, did the branch
collect it, which sheet column it feeds, can it be a split leg, can it
settle a credit account, what reference it requires.

Before it, that knowledge was written out by hand in about twenty files.
They mostly agreed because they were copied from each other.

### Split and wallet are deliberately not in the registry

SPLIT is a container for legs that are themselves methods — the money is
already counted as cash or momo through the legs, so giving split its own
total would double-count it. WALLET is customer credit the branch holds,
with a cap and a consent rule; it is not a way money arrives.

Both still work exactly as before. They are appended where a serializer
needs them, so the registry stays a list you can trust without checking.

### Online is earned revenue that never touches the till

`ONLINE` is `collected=True`, `in_till=False`. The branch does the work
and the money lands in an HQ-controlled account.

That pair is the whole point: it counts toward branch revenue and
`total_collected`, and it can never reach a cashier's variance. She can
only be held to what she can count.

### Online cannot be split, and cannot settle a credit account

An online payment is all or nothing, not one leg of a counter split.

A credit account belongs to someone the branch has traded with for a
long time, who settles by cash, momo or bank. Online settlement is a
different flow that does not exist.

### Each method gets a real column, not a JSON blob

`total_online` is a migration. So is every future method.

A JSON breakdown would need no migration, but these are frozen financial
records: a column carries a type and a constraint, and the weekly and
monthly aggregates can `Sum()` it directly. Given this system's history
of numbers going quietly wrong, a migration per method is a fair price.
New methods are rare.

---

## Online orders (Print Octos)

Settled 28 September 2026. Nothing is built yet; there is no payment
integration.

### Revenue appears on the branch sheet, separately from the till

The BM should see the full picture of the day. But "in your till" and
"paid online" must be two lines, or the first variance investigation
chases money that was never in the building.

### Capacity is held, not checked

A branch that can take the job at 14:02 may not be able to at 14:09, and
the customer is paying in between. So routing reserves capacity while
the customer pays, and releases it if payment does not land.

A check says "it looked fine when we asked." A hold says "this slot is
yours."

### Three file checks, before payment, all must pass

1. Can it be opened, and is the format accepted — PDF, JPEG, PNG, TIFF,
   WEBP
2. Is the resolution sufficient at the ordered output size
3. Do pages and dimensions match what was ordered

These three are factual and the customer can act on them. Colour mode
and blank last page stay as warnings, because both are often deliberate,
and the acceptance is recorded so the coordinator sees the customer was
told. The coordinator still inspects by hand; these reduce what reaches
him.

### A reroute moves attribution, never money

The money sits in the HQ ledger throughout. The coordinator's reroute
changes who it belongs to, nothing else.

### Attribution posts forward, never backwards

A reroute writes a transfer on today's sheets — minus at the origin,
plus at the destination — and never edits the original sheet, even when
it is still open.

A job paid Monday and rerouted Wednesday sits inside a closed sheet, a
filed week, possibly a submitted month. Editing it would silently change
figures the BM signed and Finance reviewed.

One rule that works on day one and day thirty beats a rule with a
boundary in it. Same-day reroutes land on the same sheets anyway, so it
costs nothing — and it makes the reroute a visible event rather than a
figure that quietly differs from what was filed.

### Consumed cost stays with the origin branch

If work had started, the origin spent the materials. It keeps that cost.

### The 24-hour reroute expectation is flagged, not enforced

The business expectation is that no job is ever rerouted past 24 hours.
That is not compiled into a guard: a job that genuinely needs moving on
day three must be movable, or someone is stuck with a job nobody can
process. Past 24 hours it is flagged in the monthly close review, like a
till variance.

Every guard that has refused reality in this system started as a
confident statement about how the business works.

### Received and fulfilled are two different counts

Received is the branch that took the order; fulfilled is the branch that
did the work. Identical on a normal day. When they differ, something
happened and it can be seen — and branch performance, the prediction
engine and the monthly close agree with each other instead of quietly
disagreeing.

---

## The cashier's queue

### The queue splits by job type, decided on the server

Instant and processed are separate kinds of work. The split is a filter
on `job_type` in `CashierQueueView`, with counts for both tabs riding
along in the response.

If the frontend decided what counts as instant, the RM view, the BM view
and every future branch would each get their own opinion, and they would
drift.

### A job's type follows the services on it

`derive_job_type()` in `job_service.py`: a job is instant only if every
service is instant. One production line means the work has to be made,
whatever else is on the ticket.

This rule already existed in `proforma_engine`, proven on real
conversions. The counter path was hardcoding `INSTANT` regardless, so a
banner booked at the counter travelled the instant path and never
reached the floor.

### Design jobs are refused at intake

Logo Design is active in the catalogue and the DESIGN path has never
run. Refusing is honest and visible; letting it through would make the
first real customer the test.

### Processed jobs enter the cashier's queue when marked ready

Not on a promised date. The coordinator passes the work after quality
control, the customer is notified, and the job appears in her queue.

A promised date is a guess. "Coordinator marked it ready" is a fact,
made by the person who physically checked the work. Early, on time or
late, the path is identical — she never has to search for it.

### Her evening list holds only finished work waiting for a customer

Each such job gets one answer at sign-off, saved in one transaction with
the float, never blocking. The chips for processed jobs are deferred
until real processed jobs exist — there are none in the database, and
designing an evening ritual around a job type that has never appeared
would be guessing at volume, at reasons, at everything.

### The cashier's "not ready" tap notifies nobody

It is an internal note that records a likely date. She may be recording
something half-heard at the end of a long day, and a message to the
customer would make it a promise nobody on the floor actually made.
Being explicit in that note is a training and appraisal matter.

### Sign-off can be deferred, not skipped

`should_lock` stays true all evening, so the wizard reopened the instant
it was closed. Now a cashier with jobs still pending can put it off for
15 minutes. The shift reminder keeps firing every five minutes
throughout, so sign-off can be postponed but not forgotten.

### The coordinator needs a sign-off of their own

Every other role closes its day. The coordinator — the one role holding
every customer promise — closes nothing, which is why a missed promise
can pass silently. Not yet built.

Never blocked, always recorded: he can close with promises unmet, he
cannot close with them unmentioned.

---

## Documents

### One palette, warm rather than cool

`apps/core/pdf/base.py`. Brand red `#E31E24` and gold `#F5A623` are
fixed. The greys are warm (`#1a1a1a`, `#555555`, `#999999`, `#e0ddd8`,
`#f7f6f3`) rather than the zinc scale the portals use.

These are printed documents from a printing press. The customer sees
them on paper, not beside the software, so matching the portal buys
nothing while warm greys sit better against off-white stock and survive
photocopying. It was already the day sheet's palette, and the day sheet
is the document produced most often.

### The base module owns the look, each builder owns its content

Page setup, palette, table style, `money()`, `style()` are shared. A day
sheet, a weekly filing, a monthly close and a proforma answer different
questions for different readers; forcing them through one generator
would end in a function taking fifteen flags.

### Every PDF builder is a plain function in a pdf/ folder

`finance/pdf/`, `jobs/pdf/`, with `core/pdf/base.py` above both. The
sheet builder was reachable only through `call_command`, and two others
lived inside `views.py`. A builder that cannot be called cannot be
tested, and the weekly PDF was broken for months because of exactly
that.

---

## Prediction engine

### The forecast is for awareness, and that is the honest answer

The BM looks at it to see how the day is going. No staffing, cash or
order decision depends on it. Planned for RM and CEO views later.

That changes what "good enough" means: the BM can see when the forecast
is wrong, a remote viewer cannot. So the interval and the confidence
score must be checked before it reaches them.

### Week-of-month is removed, not backtested

It explained ~1% while carrying 20% of the blend. Noise with a weight on
it.

### `confidence_pct` is a score, not a probability

Renamed to `forecast_confidence_score`. Nothing has established that 80
means 80%. The UI must not imply it either.

### Month is logged, not modelled

The recomputed variance analysis puts month at roughly 10%, which is not
negligible. But six months of data cannot separate a seasonal pattern
from the shop growing, from school terms, or from the rainy season.
Revisit after a full year.

### Forecasts are recorded on a schedule, not on request

An hourly task records a forecast whether or not anyone opens the
dashboard. Weekly filings previously ran only when someone opened the
tab, and weeks nobody visited were never filed. It also gives the 95%
completeness criterion a denominator.