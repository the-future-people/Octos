# Continuity — state of play

Rewritten each session. This is where things stand, not how they got here;
for that see `docs/decisions.md`.

Last updated: 9 October 2026.

---

## Where the work is

| | |
|---|---|
| Backend | `Octos-1` — Django 5, DRF, PostgreSQL, Docker |
| Staff frontend | `octos-web/octos-web` — Vite, port 5173 |
| Storefront | `print-octos` — Vite, port 5180, its own repo |
| Live backend | Railway |
| Live staff app | Vercel |

Test command, 275 tests:

```
docker-compose --env-file .env.docker exec web python manage.py test \
  apps.finance.tests apps.jobs.tests apps.analytics.tests \
  apps.storefront.tests apps.production.tests \
  apps.production.tests_capability -v 1 --keepdb
```

---

## Print Octos — the online storefront

The customer-facing shop. Unauthenticated by design: a stranger pricing a
banner has no account and should not need one.

**Complete, end to end on the backend:**

1. Browse the catalogue
2. Specify — dimensions and quantity, priced by the server
3. Upload artwork — measured and judged against the size ordered
4. Identify — phone and first name
5. Customer code — 5% once, over GHS 100
6. Choose a branch — from those that can actually make it
7. Pay — Paystack hosted page
8. Webhook — signed, idempotent, records the fee and the net

**Frontend built:** landing, specify, checkout. All three work against the
live backend.

**Not built:**

- Conversion. A paid order never becomes a `Job`. This is the last gap in
  the chain and nothing downstream happens without it.
- The tracking page. `/paid` is referenced as a callback and does not exist.
- Search. The box on the landing page does nothing.
- "Browse all" — there is no full catalogue page.

---

## The floor

`seed_floor` now holds the whole production floor in version control:
5 stations, 6 machine types, 49 service routes with their timings. All of
that previously existed on the production database and nowhere else.

**Machines Farhat is buying:** Extreme E1902 (1900mm) and E3202 (3200mm),
both i3200 dual head, plus the ET/ETC680 vinyl cutter at 680mm and a wider
cutter still to be specified.

Speeds at the pass counts in use — 4 pass for flexy, 6 pass for SAV:

| | 4 pass | 6 pass |
|---|---|---|
| E1902 (6ft) | 39 m²/h | 32 m²/h |
| E3202 (10ft) | 30 m²/h | 24 m²/h |

The 10ft is slower per square metre. It is for work too wide for the 6ft,
not for work in a hurry.

---

## Ready times

`PredictionService` computes them: setup and per-unit from `ServiceStation`,
the queue ahead divided by the people at each station, walked through the
branch's trading hours with Sunday skipped, plus a 30% buffer.

It prefers measured timings over seeded ones where a station has been
observed, and reports its own confidence.

`BranchStation` holds how many people work a station at a branch. A missing
row means one person.

Nothing has yet been measured — Westland is all instant work, which leaves
no gap to observe. Every current estimate is seeded rather than measured.

---

## Open, in rough order of cost

### Blocks the storefront going live

- **Conversion** — a paid order never becomes a job
- **The tracking page** — `/paid` does not exist
- **Paystack keys** — test keys never set; no real payment has run

### Blocks real counter work

- Payment modal has no credit option
- `deposit_percentage` accepts only 70 or 100
- `balance_due` ignores partial credit (job 4910)
- Attendant cannot attach a file at intake for WhatsApp jobs

### Catalogue

- **Business cards are priced per card and should be per box** — quoted
  GHS 3,000 for 100 at checkout. Real price is GHS 120–250 per 100.
- Business cards have no floor route, so they cannot be ordered online
- Seven services exist on production and not locally
- Three service codes are truncated at 20 characters
- Small sticker tier bands unknown; one point only (100 × 3×3in at GHS 280)

### Known faults

- `RoutingEngine` scores on deprecated job statuses and never checks
  machines, despite `ServiceStation`'s help text claiming it does
- The storefront's first-name field shows what was typed, not the name on
  file, for a returning customer
- The branch card is clipped by the fixed pay bar on checkout
- Weekly filing low-stock alert fires on 7 machines every week
- Branch Manager Notes renders `--` when empty
- September monthly close still SUBMITTED in error
- `power cut` missing from `JobHalt.Reason`
- Machine down/up has no UI
- `PER_LINEAR_M` missing from `UNIT_CHOICES`
- Receipt numbering has the same race as proforma
- PDF images nested in form XObjects skipped by the resolution reader

### Queued

- Can-Do Sandbox — photo to job type, cost, capability
- Coordinator sign-off
- Catalogue batches — 70 services, 8 sections
- Customer location, so branch distance means something
- UI pass across the storefront — next session