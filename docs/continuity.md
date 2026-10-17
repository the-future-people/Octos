# Octos — where things stand

Updated 17 October 2026, afternoon. Four days of work since the last
update: the coordinator portal rebuilt and live, the floor tracked
machine by machine, a final check before anything reaches a customer,
and the first three batches of the Westland catalogue loaded.

Paste this at the start of a new session to pick up without
re-explaining.

---

## The short version

A customer orders online, pays, and watches the job move: inspected,
printed on a named machine, finished at the bench, checked against what
was ordered, ready. Each stage tells them how long it has left. Nothing
reaches them without a person comparing what was made with what was
ordered.

The catalogue is being rebuilt one agreed batch at a time. Everyday
prints, flyers, business cards, flexy and SAV are live, with finishing
the customer chooses: lamination, binding, envelopes, cutting, eyelets.

Close to version 1. What remains is additions and polish, not
foundations.

619 backend tests green.

---

## How an online order flows now

1. **Storefront.** The customer picks a product (one tile per print,
   sides chosen on it), uploads the file, chooses finishing. Pages are
   counted from the file, never typed. The server prices everything.
2. **Payment.** Paystack; a full-screen "Taking you to Paystack" message
   covers the hand-off.
3. **Conversion** (worker). Job created PAID, SETTLED, RECEIVED, ONLINE.
   Each order line becomes a job line; each add-on becomes its own
   priced line attached to its piece (`JobLineItem.parent`).
4. **Arrived.** Strict queue, soonest promise first. The coordinator
   claims the head job, inspects it in the wide modal (artwork, order,
   specification, checks), corrects a specification with the customer's
   say-so if needed, and clears it.
5. **Clearing builds the steps.** Each piece's route, merged with its
   add-ons' routes in station order, becomes `JobStep`s: print on a
   named machine, laminate, bind, then the Cutting / finishing bench.
   Each step goes to a machine of the right type that is up, wide
   enough and least loaded.
6. **In press and Finishing** show each machine as a lane: the job on
   it, its progress, the jobs waiting with minutes until each is done.
   Done moves a piece to its next machine.
7. **The final check.** Done on a piece's last step opens it: ordered
   against made. Everything matches: the piece is finished, and when
   every piece is, the job is DONE and the customer is texted. Anything
   differs: the piece goes back to its print step on its own machine,
   and the estimate grows by itself.
8. **Collection** by the attendant.

The customer's tracking page has `stage_estimate` available ("In press,
about 15 minutes"), worked out fresh on every read. The tracking page
itself does not show it yet.

---

## What was built, 14–17 October

**Coordinator portal** (live). Dot stepper, strict arrivals queue with
claims, inspection modal with editable specifications (`JobSpecChange`,
customer's words required), machine lanes for In press and Finishing,
final check modal. PDFs preview from a fetched local copy (framing the
backend directly was refused by the browser). Add-ons show under their
piece, not as items of their own.

**The floor** (live). `JobStep` (0040), by-hand steps (0041), one shared
Cutting / finishing bench, machine assignment, per-machine queues that
start the next job by themselves. A machine going down halts only its
own job and moves its queue. Cancelled jobs leave every queue, and the
floor fills any free machine each time it is read. The printers are
named **6ft Large Format** and **10ft Large Format**.

**Live estimates.** `apps/jobs/services/estimates.py`: queue time ahead
plus the step's own work, rounded up, walked through opening hours,
running-over and held-up flagged.

**Final check** (0042). Ordered against made at each piece's last step,
recorded every time, mismatch sends the piece back.

**Catalogue, batches 1–3** (`seed_catalogue`, re-runnable):

- *Batch 1.* 13 services online. Business cards GHS 150 a box of 100.
  Add-ons: A4/A3 lamination, A4/A3 ring binding, brown envelope
  (GHS 2), clear bag (no price yet, so unavailable).
- *Batch 2.* One product per print: A4 colour, A4 black and white, A3
  colour, A4 flyers, A5 flyers, each with Front only / Front and back.
- *Batch 3.* Flexy and SAV: at least GHS 30 an order line, any size
  from 1in. SAV *Cut to shape* GHS 3 a sq ft (by hand until the
  plotter). Flexy *Eyelets* free. Flyers ten or more, guillotine-cut as
  part of the job.

**Pricing.** The minimum is per order line, and quotes say how many
pieces it covers. A saved price applies at once (the rule cache is
cleared on save). Add-ons are counted by rule: lamination every sheet
of every copy; binding per copy at the ring size its sheets need;
packing one for all copies or one per copy, as the customer says;
cutting by the piece's area.

**Reliability.** The worker reconnects to Redis by itself, and the
confirmation page converts a paid order the worker missed.

---

## Where the code lives

**Backend (`Octos-1`)**

- `apps/jobs/services/steps.py`: routes to steps, machines, queues, done, move
- `apps/jobs/services/floor.py`: the floor payload for the lanes
- `apps/jobs/services/estimates.py`: time left per stage
- `apps/jobs/services/final_check.py`: ordered against made
- `apps/jobs/services/availability.py`: can it be made, add-on pricing, sheets from a file
- `apps/jobs/services/inspection.py`, `spec_changes.py`: arrivals and corrections
- `apps/jobs/pricing_engine.py`: `quote_line`, the one price path
- `apps/jobs/management/commands/seed_catalogue.py`: the agreed catalogue
- `apps/production/services/machine_service.py`: machine down and up
- `apps/storefront/views.py`, `services/conversion.py`
- Tests: `tests_steps`, `tests_floor`, `tests_final_check`, `tests_catalogue`

**Coordinator portal (`octos-web`)** `src/components/coordinator/`:
`ProductionBoard`, `MachineLanes`, `InspectionModal`, `FinalCheckModal`,
`ArrivalQueue`, `StageFlow`, `StageList`, `ReadyModal`, `shared`.

**Storefront (`print-octos`)** `src/pages/`: `Landing`, `Specify`,
`Checkout`, `Paid`, `Track`.

**Master catalogue spreadsheet:** `Farhat_Westland_Catalogue_Master.xlsx`
(91 services, availability looked up from a Machines tab). Batches are
taken from it one agreed service at a time.

---

## Running the tests

`apps` is a namespace package; build the labels fresh every time:

    $root = (Get-Location).Path + '\'
    $labels = Get-ChildItem -Recurse -Path apps -Include test*.py,tests*.py |
      ForEach-Object { $_.FullName.Replace($root, '').Replace('.py', '').Replace('\', '.') } |
      Where-Object { $_ -ne 'apps.inventory.tests' }
    docker-compose --env-file .env.docker exec -T web python manage.py test @labels --noinput

A test run that says the test database "is being accessed by other
users": `docker-compose --env-file .env.docker restart web`, then run
again.

---

## What's wrong right now

- **Checkout can re-price a line from what the browser sends back.**
  Changing a quantity resends each line's details, page count included,
  and the server trusts them. It should keep the sheet count it worked
  out from the file.
- **Some online orders convert with no promise** (FP-WLB-2026-05399
  showed "No promise"). No lateness, no place in promise order.
- **The tracking page does not show the live estimate** the backend
  already returns.
- **Add-on-only services** (Cut to shape, Eyelets) may appear in the
  counter's service list.
- **Promises only exist for online orders.** Counter jobs never show as
  late.
- **Jobs cleared before steps existed** sit in "From before machine
  tracking" with the old buttons until they finish.
- **The info strip** ("On the floor", "Machines") shows dashes.
- **Em-dashes mangled to `???`** in catalogue descriptions.
- **`original_filename`** is the device's name.

---

## Decisions worth not relitigating

All in `docs/decisions.md`. The ones most likely to be questioned:
by-hand belongs to the step, not the station; one bench; the final check
is the only way a last step finishes and a mismatch is never handed
over; availability is worked out, never switched; one product per print
with each side keeping its own price; pages come from the file; the
minimum is per line and offers the pieces it covers; guillotine cutting
is part of the job, SAV cutting is a choice.