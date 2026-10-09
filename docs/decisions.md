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

# Decisions — additions, 29 September 2026

Append these to `docs/decisions.md` under the sections named. Where a
section already exists, these entries join it.

---

## Payments — addition

### Online orders are paid in full

The 70% deposit exists because the customer is standing in front of you
and is known. A stranger on the internet is not. Online orders pay 100%
before the job is made.

The deposit tiers stay as they are for counter and proforma work.

---

## Online orders — additions

### The storefront leads with processed work

Banners, business cards, ID cards, stickers. Instant services — photocopy,
typing, lamination — are reachable by search but not promoted.

Nobody goes online to order a photocopy; they walk in. Online earns its
place on jobs worth planning ahead for, where the customer wants to know
the price and the turnaround before leaving the house. The front page
shows a turnaround rather than a price for each category, because "2
days" is the question the customer actually has and the price depends on
size anyway.

### The specification screen collects facts, nothing else

Service name, dimensions, quantity, price. No preset sizes, no "what's it
for" framing.

The "this is what you're printing" step already answers whether the
customer has chosen the right thing. Asking the same question twice, in
two different shapes, would make both weaker.

### There is a separate model for an order that belongs to nobody

`Job` is branch-shaped throughout: a branch, a daily sheet, a
branch-scoped job number, a place in branch queues. An online order has
none of those until routing and payment settle, and a `Job` with a null
branch would leak into every queue and every sheet total.

So an online order is its own model, converted into a `Job` when it lands
at a branch. The precedent is `ProformaInvoice`, which is exactly this
shape already: a customer-facing record that becomes a job on a trigger.

### The storefront is its own app

`apps/storefront`, importing from `jobs`, `customers` and `finance` with
nothing importing back.

It will grow lead identity, payment webhooks, file checks and a public
authentication model that have nothing to do with staff JWTs. A proforma
is created by staff for staff; an online order is created by a stranger
on the internet. That is a different trust boundary and deserves its own
wall.

---

## Pricing

### Large format is priced by area, from inches

`(width" × height") ÷ 144 × rate`. Dimensions are taken in inches because
that is what the customer gives and what the machine cuts. The area is
never rounded; only the money is, at the end.

- **Flexy banner:** GHS 3.25 per sq ft
- **SAV sticker:** GHS 2.80 per sq ft

The service catalogue drafted for the new building proposes 5.20, which
is high against local market rates. 3.25 stands until supplier quotes
land.

### The minimum is GHS 10 per piece, before quantity

A small banner costs the same in file prep, cutting and packing as a
large one. Three 12 × 12 pieces are three minimums, not one — each is a
piece of material and a piece of work.

It lives on `PricingRule` as `minimum_price`, defaulting to 0, so any
service can set one. The catalogue's proposed 80–120 minimum on all
large-format work is deferred: it may be right for the new building, it
is not what the shop charges today.

### Small stickers are tiered per piece, not priced by area

Area pricing badly under-prices small work: 100 × 3×3in stickers area-price
at about GHS 50 and are worth GHS 280. They are a separate service using
`pricing_tiers`, which the engine already supports. Bands still to be set.

### One quote path: `quote_line`

Service, specification, quantity in; price, area and breakdown out. The
counter, the storefront, the price endpoint and any future assessment all
call it.

It carries every spec key the service declares through to the engine as a
condition, so binding's ring size and passport's output mode work without
being named anywhere. Naming them was how they ended up hardcoded in four
places.

### An area service with no dimensions is refused, not priced as zero

`specifications` is free-form JSON and nothing enforces its contents.
Pricing a missing width as zero area is how a banner gets sold for
nothing.

### The browser does no pricing arithmetic

Every price comes from the server. `NewJobModal` used to calculate simple
services locally for speed, which meant two implementations that had
already drifted.

The 400ms debounce means one network call per pause. If it proves slow at
the counter, the answer is a faster endpoint, not a second engine.

### The form is built from `spec_template`

Field descriptors on the service declare what to collect: `key`, `label`,
`type`, `required`, `default`, plus `min`/`max`/`unit` for numbers and
`options` for selects. Services without one keep the old Sheets and
Copies inputs.

The field existed and nothing rendered it. Meanwhile two services had
their fields hardcoded into the modal instead.

---

## Still open

Raised today, not settled.

- **A job has one `job_type`, so a customer wanting photocopies and a
  banner together cannot have one job.** Either two jobs at their own
  paces, or one job that cannot complete until the slowest line does —
  and the customer cannot collect the fast part. The handover rules
  point towards two jobs.
- **The post-closing entry point should probably replace the New Job
  modal rather than sit beside it**, so the BM cannot pick the wrong one
  after hours. It carries a required reason and produces `INTAKE_HELD`
  rather than `PENDING_PAYMENT`, so the after-hours version must say so
  plainly. The trigger should follow the same lock status the portal
  already reads, not a clock: a job taken at 19:00 after the cashier has
  signed off still cannot reach her.
- **Can-Do Sandbox.** Staff upload a photo or short video of what a
  customer brought in; the system identifies the job, what it takes, the
  cost, the time, and whether the branch can do it. The value is in the
  can-do answer grounded in Octos's own catalogue, machines and stock —
  not in the photo recognition, which should be allowed to say it does
  not know. It answers the same question routing asks before holding
  capacity, so it should be built on a capability model rather than as a
  one-off.

# Decisions — additions, 1 October 2026

Append to `docs/decisions.md` under the sections named. The Pricing
section already exists; Identity and Customer codes are new.

---

## Pricing — additions

### Prices are company-wide. Branch rules do not exist.

One price per service, set once, applying everywhere. If prices ever
differ it will be regional or zonal, not per branch.

`PricingRule` still has a branch field and `_get_rule` still prefers a
branch rule over the company one. That is the mechanism for regional
pricing later. Nothing uses it today, and nothing should: the 127 branch
rules that existed were seeded rather than written, 91 were exact copies
of the company rule, and the one that differed had been quietly
undercharging every large binding for months.

**A new service gets a company rule and no branch rule.**

---

## Identity

### Identity is asked for late

A stranger pricing a banner should know what it costs before being asked
who they are. Anything that gates browsing or pricing loses the
customer.

So the order is built first, identity comes at checkout, and payment
after that.

### A first visit creates a lead, not a customer

Phone number and first name, nothing more. Most first visits never come
back, and writing every one into `CustomerProfile` would fill the
customer table with people the shop has met once.

A lead becomes a customer when the order converts to a job, not when
they identify — someone who identifies and then abandons is not a
customer.

### An order is reached by a token, not by its number

`ORD-2026-00001` is one guess away from `00002`, so the number can never
be what proves an order is yours. A random token is returned once at
creation and required on every request afterwards. It is also what the
tracking link carries, so a customer reaches their own order with no
account at all.

A wrong token and a wrong number give the same 404: neither tells a
stranger whether an order exists.

---

## Customer codes

### A code, not a PIN, and it buys something

A returning customer is offered a code that brings up their past orders.
Calling it a PIN makes it sound like a chore; calling it a coupon would
promise money off that is not there.

So it does both honestly: it protects their history **and** takes 5% off
the order they set it on.

### 5%, once per person, on orders over GHS 100

A cedi off a photocopy delights nobody. Thirty off a banner is a reason
to come back.

Once, not every time: a standing 5% for anyone who typed a code is a
price cut, not loyalty. Held against the person rather than the code, so
clearing a code and setting another earns nothing new.

Rounded to the nearest cedi — pesewas off a discount read as arithmetic
rather than as a gift.

### Three figures are stored, not one

`full_total` is what the work is worth, `discount_amount` is what came
off, and `total` is what the customer actually pays — and what the
receipt, the day sheet and every report count.

Storing only what was charged would make the scheme invisible the moment
it had run: there would be no way to answer what a month of codes cost.

### The code is generated, hashed, and never readable again

Generated rather than chosen, because it is sent by text and a code the
customer picks is one they will tell someone. Shaped as `AMA-4K2` — three
letters from their name — so it reads as theirs and is worth
remembering. No I, O, 1 or 0: a code read off a screen should not turn on
a glyph.

Hashed on the way in. Losing it means being sent a new one, which is the
same experience for the customer and leaves nothing in the database worth
stealing. Nobody, including staff, can read a customer's code.

### A code is offered, never demanded

A returning customer who never set one is not challenged. Being stopped
at the door on the visit you came back is the wrong moment, and nothing
is protected yet anyway — which is their own choice.

---

## The public surface

### The storefront is the first unauthenticated API in Octos

Everything else requires a staff token. These endpoints do not, by
design.

That has consequences the rest of the system never had: rate limits that
matter, an order that can be created by anyone, and prices that can never
be taken from the request. A total arriving from a browser is a
suggestion from a stranger; every line is quoted again server-side
through the same function the counter uses.

### Storefront requests get their own throttle rate

The global anonymous limit is 20 a minute, which is right for an API with
no public face and wrong for a shop. Specifying a banner reprices on
every change — width, height, quantity, each a request — so a real
customer would be locked out halfway through their own order.

90 a minute for the storefront, 6 a minute for the endpoint that checks
codes, since guessing a code is the one thing worth slowing down.

### Order numbers come from a database sequence

Not from the highest number so far, which is what the proforma and the
receipt do. That is safe when one member of staff creates one document at
a time, and not safe when two strangers can click in the same
millisecond.

---

## Still open

- **The three undercharged jobs** from 1 October — 04996, 05000 and
  05001, about GHS 82 across three customers — are COMPLETE with receipts
  issued. Absorb or call the customers: not yet decided.
- **Receipt numbering has the same race** as the proforma. Not urgent,
  but it becomes real the day two cashiers work one branch.
- **Images nested inside a form XObject are skipped** by the PDF
  resolution reader, so some files report fewer images than they contain.
  Better than a wrong number, but it means `dpi` can be absent on a file
  that does have raster content.

# Decisions — 8 and 9 October 2026

Append to `docs/decisions.md`.

---

## The floor lives in a seed command, not only in production

5 stations, 6 machine types and 49 service routes with their timings existed
on the production database and nowhere else — set up by hand, in no
migration and no command. A rebuilt database would have lost all of it, and
the local database never had any of it, so nothing touching the floor could
be exercised outside production.

`seed_floor` now holds it. `--prune` is off by default: a route added on the
floor and not yet written down should not be destroyed by a careless run.

Same class of problem as the six finance roles and `FLOW_COORDINATOR`.

---

## Capacity is people, not machines

`BranchStation` holds how many people work a station at a branch. Two
trained operators at the printer means two jobs run at once; a second
machine with nobody to run it adds nothing.

A missing row means one person. The common case should not need a row to
say so, and zero would make the queue divide by nothing.

Rejected: deriving it from who is clocked in. Truer, but it needs every
member of staff tagged with the stations they work and the floor keeping
that current — a habit nobody has yet. A number someone changes when they
train a second operator is honest and is exercised from the first day.

---

## Width belongs to the machine, not the machine type

First attempt put `max_width_mm` on `MachineType`, which forced a 6ft and a
10ft printer to be different types. A service route then had to name each
width separately, and a route saying "large format" ruled out a 10ft machine
that could do the work perfectly well.

Both are large format. The width is a fact about the individual machine.

---

## A banner is measured by its shorter side

A 168 × 36 banner needs 36 inches of roll width, not 168 — it is fed with
the short side across the roll and the length running off it. Reading the
larger number would refuse nearly every banner Farhat sells.

---

## Branch choice belongs to the customer

Octos narrows to the branches that can genuinely do the work today, and the
customer picks among them. Two branches — one ready at four across town, one
tomorrow round the corner — and only they know which matters.

Like a rider choosing between a cheap car ten minutes away and a nearer one
that costs more.

A branch appears only when it can do the work: it has the machine, the
machine is available, the material fits, and the branch is active. Not a low
score — absent.

There is no "we are not taking orders" switch. A branch that can do the work
should not be able to quietly decline it; the refusal comes from Octos
reading the floor.

---

## Refusals are sentences, and they are said once

"Westland can print up to 1900mm wide. This job needs 2400mm" tells a
customer what to change. An empty list tells them nothing.

A service with no floor route is a fact about the service, not about any
branch, so it is said once rather than once per branch — seven branches
each saying the same thing reads as a system fault.

---

## The chosen branch is checked again on the way in

The options were right when they were drawn, and a machine can go down
between seeing the list and tapping it. Trusting the id alone would let an
order land on a floor that cannot make it.

Changing the size clears the chosen branch: a branch that could make a
36-inch banner may not be able to make a 90-inch one.

---

## Payment refuses an order with no branch

A job has to be made somewhere. Taking the money first means an order that
belongs to no floor and a customer already charged.

---

## The promise is frozen, not recomputed

`Job.estimated_ready_at` is stored at the moment it is made. Recomputing it
on each read would make it agree with the current queue forever, and the
question worth answering later is whether the promise was kept.

`Job.work_started_at` records when someone actually began. An estimate
missed because the job queued for a day is a different failure from one
missed because the work took longer than thought, and only both timestamps
tell them apart. Set once — a job reaching finishing has not started twice,
and a resumed job began when it began.

---

## i3200 heads, 4 pass for flexy and 6 for SAV

More passes means more ink layers, less banding, proportionally slower.
A flexy banner read from across a road does not need 6 pass, and running it
there would halve throughput for quality nobody sees. SAV ends up on a
window or a vehicle at arm's length, so it gets 6.

The manufacturer's figures assume a machine that never pauses. Real
throughput is lower, which is what the setup minutes carry.

---

## `estimate.py` was deleted the day it was written

A whole ready-time engine was built before anyone looked for
`PredictionService`, which already existed, was already called from the
coordinator board, and was better: it reads measured timings in preference
to seeded ones, reports confidence, and takes the busiest station rather
than the sum of all of them.

The new one summed stations, which overstates the wait.

Deleted. What survived from that morning was real: `BranchStation`,
`max_width_mm`, the floor seed, and the flexy and SAV routes that had never
existed.