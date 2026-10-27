# Lessons

Rules that stop a repeat. Short and imperative. Append only; nothing here
gets deleted because a rule stopped being fresh.

---

## Before debugging an import error, grep for stray imports

An editor's auto-import put `from pdb import pm` at line 1 of three
separate files. In two it shadowed a real import and broke it; in the
third it sat above a working import of the same name, so the tests
passed for the wrong reason.

```
Get-ChildItem apps -Recurse -Filter *.py | Select-String -Pattern "from pdb import|import pdb|breakpoint\(\)" -Encoding UTF8
```

A sweep that returns nothing is not proof — run it again after the edit
that triggered the auto-import.

---

## A file that looks unsaved may have saved somewhere else

A test class pasted "into tests.py" landed in `apps/jobs/tests.py`
instead of `apps/finance/tests.py`. Searching the intended file found
nothing, which read as a failed save. It only surfaced when a broader
suite ran and the duplicate failed.

Searching the file you expect proves absence there, not everywhere.
Search both candidates.

---

## Compare hashes before refactoring a file that looks familiar

`apps/finance/services/close_service.py` was byte-for-byte identical to
`apps/finance/monthly_close_engine.py` — 1,071 lines, imported by
nothing, sitting among real services. Editing the wrong one would have
passed every test and changed nothing in production.

```
docker-compose exec web python -c "import hashlib; print(hashlib.md5(open('<path>','rb').read()).hexdigest())"
```

---

## `manage.py check` proves nothing about a code path

Faults that passed `check` and only failed when the path ran:

- `quote.line_items` where the parameter was `proforma` — proforma
  conversion had never run once
- `self.canvas` against ReportLab's `self.canv` — the weekly PDF never
  rendered, and a broad `except` swallowed it every week
- `signed['variance']` referenced where `signed` was never assigned
- `outstanding_week` missing its last two lines
- a moved function's call site left with no import

Run the path. If it can't be run, write a test that runs it.

---

## After moving a function, check every call site for its import

Moving `_generate_weekly_pdf` out of `views.py` left the call behind
with no import. `check` passed. It would have raised `NameError` on the
first download, and the surrounding `except Exception` would have
reported "PDF generation failed" with no cause.

```
Select-String -Path <file> -Pattern "<function_name>" -Encoding UTF8
```

Two lines expected: the import and the call.

---

## A broad `except` around generation hides the bug for months

The weekly PDF raised on every render and nobody knew, because the
caller caught everything. Where a broad `except` is unavoidable, log the
exception with `exc_info=True` — and write a test that asserts real
bytes come out.

---

## Test fixtures that compute dates can collide on one weekday only

`make_sheet(days_ago)` counted calendar days then stepped back off
Sunday. On a Monday, `days_ago=2` and `days_ago=3` both landed on the
same Saturday: same branch, same date, unique constraint. It failed one
day in seven, which is worse than failing always — the first instinct on
a Monday is that you broke it.

Count trading days, not calendar days, when the fixture means trading
days.

---

## Knowledge written out by hand in many places will drift

Payment methods were declared in about twenty files. The greys in five
PDF builders all disagreed. Both were fixed by one source of truth:
`apps/finance/payment_methods.py` and `apps/core/pdf/base.py`.

When the same fact appears in a third file, stop and make a registry.

---

## An `if/elif` chain over data values drops what it does not recognise

`_snapshot_totals` sorted receipts by method with `if/elif` and no
`else`. An unrecognised method landed in no total at all — money gone
from the books with no error raised.

Every such chain needs an `else` that logs what it could not place.

---

## Naming fields by hand in `update_fields` defeats a registry

The totals were computed from the registry and then saved with a
hardcoded `update_fields` list, so `total_online` was calculated
correctly and discarded. Build the list from the same source as the
values.

---

## Pin behaviour with tests before a refactor, not after

Every migration onto the payment registry followed the same order: write
tests asserting what the code produces today, watch them pass, swap the
internals, watch the same tests still pass. The numbers never moved, and
we knew it rather than hoped it.

---

## A guard written for one case will refuse its opposite

- Recovery assumed a stranded sheet meant the cashier never signed. Both
  real cases were the reverse.
- Submission assumed a week is filed on its Saturday. A week that missed
  its Saturday could never be filed at all.

Write the rule for the case you have not thought of yet, or make it
flag rather than block.

---

## A warning that fires every time stops being read

The sign-off wizard warned about pending jobs every single evening, so
the warning was ticked rather than read, and a mis-click closed a day
with twelve jobs outstanding. The weekly filing's low-stock alert lists
seven machines every week for the same reason.

If a flag fires on a normal day, it is not a flag.

---

## PowerShell output is not the file

`Select-Object` strips blank lines and the console mangles box-drawing
characters, so find-blocks reconstructed from console output do not
match. Use `Select-String -Context` to read raw text, and never copy a
Find block out of a terminal.

---

## Prefer a new file over a third paste into a long one

A mid-file paste destroyed `MonthlyTab` entirely once. For large moves,
extract by line range in PowerShell rather than retyping:

```
$lines = Get-Content -Encoding UTF8 <file>
$body  = $lines[<start>..<end>]
```

Nothing retyped, nothing mistranscribed.

---

## Check where the data lives before debugging the code

`PredictionService` logged "gave up walking the calendar" locally and
worked correctly on Railway. The home database has no branch and no
users, so anything needing real data cannot be reproduced there.

---

## Measure before building

Three of the v3 prediction proposal's investigations were measured in an
afternoon; two came back negative. Ask "if this signal worked perfectly,
how much would it improve?" before building it.

---

## Two unpushed commits look exactly like a broken feature

Twice a "missing feature" was working code that had never been deployed.
`git status` on both repos before concluding anything is broken.

# Lessons — additions, 29 September 2026

Append these to `tasks/lessons.md`. Existing entries stay as they are.

---

## A test that depends on when it runs will fail when you are not looking

Two in one day:

- `make_sheet` counted calendar days then stepped back off Sunday, so on
  a Monday `days_ago=2` and `days_ago=3` landed on the same Saturday and
  collided on a unique constraint. One day in seven.
- `DeriveJobTypeTests` called `save_draft`, which refuses after the shift
  ends. Green all afternoon, red at 19:30.

Freeze the clock or patch the gate. A suite that fails at certain hours
teaches you to distrust it, and the first instinct on a Monday morning is
that you broke something.

```python
@patch('apps.finance.sheet_engine.SheetEngine.get_branch_lock_status',
       return_value={'can_create_jobs': True, 'lock_reason': ''})
```

A class-level patch passes the mock to every test method, so each one
needs an extra parameter. Miss one and it errors with "takes 1 positional
argument but 2 were given".

---

## A paste can delete the function above it

`square_feet` vanished when the block meant to sit above it replaced it
instead. The tests then failed on an import error that looked like the
new code was wrong.

After any large paste, list what is actually in the file before
debugging what it does:

```
Select-String -Path <file> -Pattern "^def |^class " -Encoding UTF8
```

---

## The same calculation in two languages will drift

`NewJobModal.jsx` reimplemented the pricing engine in JavaScript for
speed. By the time anyone looked, it was missing the piece count on area
services and knew nothing about the minimum price, so a small banner
quoted at 3.25 on screen and cost 10.00 on the server.

Every price now comes from the server. The 400ms debounce means one call
per pause, not per keystroke.

---

## Hardcoding a service's fields invites the next one

Binding's ring size and passport's output mode were each written by hand
into the modal's state, the modal's render, the price endpoint and the
payload. Four places, twice over. A third service would have been twelve.

`spec_template` existed the whole time and nothing rendered it.

---

## A field nobody renders is not a working feature

`spec_template` was written by two seed commands, exposed in a
serializer, and read by no UI at all. The Production tab showed services
with no way to enter their specifications.

Before building on a field, grep for something that reads it.

---

## Clamp input on blur, not on every keystroke

`Math.max(min, parseInt(value))` in an `onChange` turned the first digit
of 168 into a 6, so no three-digit number could be typed at all. Keep the
raw value while typing; correct it when the field loses focus.

---

## An if/elif over units will silently drop one of them

`calculate` multiplied area services by the area and ignored `pages`
entirely, so four banners priced as one. The branch looked complete and
had been there since the engine was written.

Any branch that handles some inputs differently needs a test per branch,
not per function.

# Lessons — additions, 1 October 2026

Append to `tasks/lessons.md`.

---

## A value that lives in two places will be read from the wrong one

`pages` existed as a column on the line item and, once the spec form
arrived, inside `specifications`. The form sent it to the spec; pricing
read the column, which stayed at 1. Ten copies of a two-page document
were billed as ten single sheets.

Three jobs went out undercharged in a single morning, and it was only
caught because the cashier's figure was lower than the one recorded.

Reconciled in the model's `save`, not in the four places a line item is
created, because the fifth would have been missed too.

**When a form starts collecting something the model already had a column
for, one of them has to win, explicitly.**

---

## A fallback nothing has ever used is not working code

`PricingRule` has always fallen back to a company-wide rule when no
branch rule exists. The storefront was the first caller to ask for a
price with no branch, and it crashed three times in a row on three
different lines — the cache key, the result dict, the error message —
each assuming a branch was there.

The path existed in the data model, in the query, and in nobody's
execution.

---

## Seeded data that looks real will be trusted

127 branch pricing rules were seeded at some point for six branches,
five of which do not trade. 91 were identical copies of the company
rule. One was not: A3 Binding at Westland had no ring-size tiers, so
every binding charged 20 regardless of spine thickness, where the
company rule would have charged 25 and 35 for the larger sizes.

Nobody wrote that rule deliberately. It was a seed command being
helpful.

**Before building on reference data, check how much of it was typed by a
person.**

---

## Tests that share a unique value interfere with each other

Three tests in one class used the same default phone number against a
model with `unique=True` on it. Each passed alone and two failed in the
class, depending on what ran first.

**A fixture default on a unique field is a collision waiting for a
second test.**

---

## Throttle counters live in the cache and do not roll back

The storefront is the first unauthenticated surface in Octos, so it was
the first thing to meet the global 20-per-minute anonymous limit. Fifteen
tests in a row tripped it, and every test afterwards failed with errors
that looked nothing like rate limiting.

`cache.clear()` in `setUp` for any class that calls a throttled endpoint.

And the discovery mattered more than the fix: 20 a minute would have
locked a real customer out halfway through specifying a banner, since
every change of width, height or quantity is a request.

---

## `from X import X` is not `import X`

The editor auto-imported `from random import random`, so `random.choice`
did not exist. Same family as the `from pdb import pm` entries above —
an auto-import that is plausible, wrong, and only fails when the line
runs.

---

## PowerShell eats nested quotes

`c.execute(\"SELECT …\")` inside a double-quoted `-c` argument is a
parser error. Use single quotes inside, or pass the value as a
parameter:

```
c.execute('SELECT to_regclass(%s)', ['sequence_name'])
```

---

## `manage.py shell` cannot exercise views

`APIClient` sends the host `testserver`, which real settings reject with
`DisallowedHost`. Django adds it automatically inside the test runner and
nowhere else.

**A view check belongs in a test, not in a shell session.**

---

## Reading the maximum and adding one is a race

`ProformaInvoice.generate_proforma_number` and
`Receipt.generate_receipt_number` both read the highest number so far and
add one. The docstring says to call it in a transaction, which makes the
second caller fail cleanly rather than corrupt — it does not make it
succeed.

Safe when one member of staff creates one document at a time. Not safe
on a public website, where two strangers can click in the same
millisecond. The storefront uses a Postgres sequence instead.

Receipts become a real risk the day two cashiers work one branch.

# Lessons — 8 and 9 October 2026

Append to `tasks/lessons.md`.

---

## Search for the thing by what it does, not by what you would call it

A ready-time engine was written from scratch while `PredictionService`
already existed, was already wired to the coordinator board, and was better
than the replacement.

Searching for "estimate" found nothing. Searching for "ready", "predict" or
"when will it be done" would have found it in seconds.

Before building anything that sounds like it might already exist, search for
the **behaviour** across several words, and check whether anything calls it.
This is the second time — `close_service.py` was the first.

---

## A dependency used only inside a mocked function is untested

`requests` was never in `requirements.txt`. Every payment test mocked
`paystack.initialise`, so the module's import line never ran, and the first
real payment in production would have failed.

Any module that reaches the outside world needs one test that simply
imports it and checks its functions exist.

---

## A test can pass on two zeros

`assertAlmostEqual(together, alone / 2)` holds when both are zero. Asserting
that the thing being measured is non-zero first is what makes the comparison
mean anything.

Same shape as the "unknown payment method" test that stopped meaning
anything once `ONLINE` existed.

---

## A test appended to a long file joins whichever class is last

Three times now, a test meant for one class landed in another, where its
helpers do not exist. Pasting into open space at the end of a file is the
cause.

Attach new tests by editing a method that is already in the right class —
find its last test, and add after it in the same change.

---

## Django in Docker does not always reload `urls.py`

An HTML 404 rather than DRF's JSON means the view was never reached. A
registered route that still 404s is a container serving stale code:
`docker-compose restart web`.

---

## A shared API client's content type breaks file uploads

The storefront client sets `Content-Type: application/json` globally.
A `FormData` body sent through it arrives with no fields at all — no token,
so the order is not found, and the error is a 404 that looks like a missing
route.

Uploads bypass the shared client entirely.

---

## A file input does not fire when the same file is chosen twice

`onChange` fires on change, and picking the same file is not one. Clearing
`e.target.value` immediately after reading the file makes every pick count —
without it, a customer who re-exports their artwork under the same name taps
and nothing happens.

---

## A fixture with two helpers needs both fixing

Adding a rule that payment requires a branch broke six tests. Fixing
`_order_for` left `_order` untouched, and three stayed broken through
another round.

When a new requirement breaks tests, fix every helper that builds the
object, not the first one found.

---

## Reading the catalogue is reading the business

The machine catalogue gave real figures — 39 m²/h at 4 pass, not the 62.9
headline, and a vinyl cutter that stops at 680mm so banners are hand-cut.
Guessing those numbers would have produced plausible estimates that were
wrong in a way nobody would have caught until customers complained.

When a figure can be looked up, look it up.

# Lessons

Rules that stop a repeat. Short and imperative. Append only; nothing here
gets deleted because a rule stopped being fresh.

---

## Before debugging an import error, grep for stray imports

An editor's auto-import put `from pdb import pm` at line 1 of three
separate files. In two it shadowed a real import and broke it; in the
third it sat above a working import of the same name, so the tests
passed for the wrong reason.

```
Get-ChildItem apps -Recurse -Filter *.py | Select-String -Pattern "from pdb import|import pdb|breakpoint\(\)" -Encoding UTF8
```

A sweep that returns nothing is not proof — run it again after the edit
that triggered the auto-import.

---

## A file that looks unsaved may have saved somewhere else

A test class pasted "into tests.py" landed in `apps/jobs/tests.py`
instead of `apps/finance/tests.py`. Searching the intended file found
nothing, which read as a failed save. It only surfaced when a broader
suite ran and the duplicate failed.

Searching the file you expect proves absence there, not everywhere.
Search both candidates.

---

## Compare hashes before refactoring a file that looks familiar

`apps/finance/services/close_service.py` was byte-for-byte identical to
`apps/finance/monthly_close_engine.py` — 1,071 lines, imported by
nothing, sitting among real services. Editing the wrong one would have
passed every test and changed nothing in production.

```
docker-compose exec web python -c "import hashlib; print(hashlib.md5(open('<path>','rb').read()).hexdigest())"
```

---

## `manage.py check` proves nothing about a code path

Faults that passed `check` and only failed when the path ran:

- `quote.line_items` where the parameter was `proforma` — proforma
  conversion had never run once
- `self.canvas` against ReportLab's `self.canv` — the weekly PDF never
  rendered, and a broad `except` swallowed it every week
- `signed['variance']` referenced where `signed` was never assigned
- `outstanding_week` missing its last two lines
- a moved function's call site left with no import

Run the path. If it can't be run, write a test that runs it.

---

## After moving a function, check every call site for its import

Moving `_generate_weekly_pdf` out of `views.py` left the call behind
with no import. `check` passed. It would have raised `NameError` on the
first download, and the surrounding `except Exception` would have
reported "PDF generation failed" with no cause.

```
Select-String -Path <file> -Pattern "<function_name>" -Encoding UTF8
```

Two lines expected: the import and the call.

---

## A broad `except` around generation hides the bug for months

The weekly PDF raised on every render and nobody knew, because the
caller caught everything. Where a broad `except` is unavoidable, log the
exception with `exc_info=True` — and write a test that asserts real
bytes come out.

---

## Test fixtures that compute dates can collide on one weekday only

`make_sheet(days_ago)` counted calendar days then stepped back off
Sunday. On a Monday, `days_ago=2` and `days_ago=3` both landed on the
same Saturday: same branch, same date, unique constraint. It failed one
day in seven, which is worse than failing always — the first instinct on
a Monday is that you broke it.

Count trading days, not calendar days, when the fixture means trading
days.

---

## Knowledge written out by hand in many places will drift

Payment methods were declared in about twenty files. The greys in five
PDF builders all disagreed. Both were fixed by one source of truth:
`apps/finance/payment_methods.py` and `apps/core/pdf/base.py`.

When the same fact appears in a third file, stop and make a registry.

---

## An `if/elif` chain over data values drops what it does not recognise

`_snapshot_totals` sorted receipts by method with `if/elif` and no
`else`. An unrecognised method landed in no total at all — money gone
from the books with no error raised.

Every such chain needs an `else` that logs what it could not place.

---

## Naming fields by hand in `update_fields` defeats a registry

The totals were computed from the registry and then saved with a
hardcoded `update_fields` list, so `total_online` was calculated
correctly and discarded. Build the list from the same source as the
values.

---

## Pin behaviour with tests before a refactor, not after

Every migration onto the payment registry followed the same order: write
tests asserting what the code produces today, watch them pass, swap the
internals, watch the same tests still pass. The numbers never moved, and
we knew it rather than hoped it.

---

## A guard written for one case will refuse its opposite

- Recovery assumed a stranded sheet meant the cashier never signed. Both
  real cases were the reverse.
- Submission assumed a week is filed on its Saturday. A week that missed
  its Saturday could never be filed at all.

Write the rule for the case you have not thought of yet, or make it
flag rather than block.

---

## A warning that fires every time stops being read

The sign-off wizard warned about pending jobs every single evening, so
the warning was ticked rather than read, and a mis-click closed a day
with twelve jobs outstanding. The weekly filing's low-stock alert lists
seven machines every week for the same reason.

If a flag fires on a normal day, it is not a flag.

---

## PowerShell output is not the file

`Select-Object` strips blank lines and the console mangles box-drawing
characters, so find-blocks reconstructed from console output do not
match. Use `Select-String -Context` to read raw text, and never copy a
Find block out of a terminal.

---

## Prefer a new file over a third paste into a long one

A mid-file paste destroyed `MonthlyTab` entirely once. For large moves,
extract by line range in PowerShell rather than retyping:

```
$lines = Get-Content -Encoding UTF8 <file>
$body  = $lines[<start>..<end>]
```

Nothing retyped, nothing mistranscribed.

---

## Check where the data lives before debugging the code

`PredictionService` logged "gave up walking the calendar" locally and
worked correctly on Railway. The home database has no branch and no
users, so anything needing real data cannot be reproduced there.

---

## Measure before building

Three of the v3 prediction proposal's investigations were measured in an
afternoon; two came back negative. Ask "if this signal worked perfectly,
how much would it improve?" before building it.

---

## Two unpushed commits look exactly like a broken feature

Twice a "missing feature" was working code that had never been deployed.
`git status` on both repos before concluding anything is broken.

---

## A command in the Railway shell uses Railway's copy of the file

Writing a management command locally and running it remotely does
nothing until the push has deployed. This cost four separate rounds in
one evening before anyone said it out loud.

The same applies to a seed: `seed_floor` run on Railway seeds from
Railway's `seed_floor.py`, not the one just edited on the laptop.

---

## Migrations run in the Dockerfile, so a bad one takes production down

The container's CMD is `migrate --noinput && daphne ...`. A migration
that exits non-zero means daphne never starts, the healthcheck fails,
`railway.toml` restarts three times, and there is no shell to get into
because no container is running.

The deploy logs of that specific deployment are the only way in. The
service-wide log stream shows the *old* container being stopped, which
looks like something else entirely.

---

## A unique column cannot be added to a populated table with a blank default

Every existing row shares the empty value and Postgres refuses to build
the index. Three steps:

1. `AddField` without the constraint — and without `db_index`
2. `RunPython` filling every row
3. `AlterField` adding `unique=True`

`db_index=True` on step 1 makes Postgres create the same index twice and
refuse the duplicate — which reads as a leftover index and sends you
dropping things that were never the problem.

It passes locally on a near-empty table and fails on production. Test
schema changes against data.

---

## Railway scopes environment variables per service

A key set on the web service is invisible to the Celery worker. Payment
texts logged "SMS not sent (no API key)" while manual sends from the web
shell worked perfectly — same code, same key name, different container.

Use shared project-level variables.

---

## A setting read with `getattr(settings, 'X', '')` never fails loudly

`MNOTIFY_API_KEY` was absent from `settings.py` entirely. Every SMS was
logged instead of sent, for weeks, and nothing anywhere said so.

A default that means "do nothing" is worse than a crash.

---

## Celery's explicit `autodiscover_tasks` list silently drops what is missing

`apps.storefront` was absent, so the webhook queued `convert_order`, the
worker found nothing registered, and the message was discarded with a
FAILURE carrying no traceback.

The comment above that list predicted this exact failure and it happened
anyway. A bare `autodiscover_tasks()` scanning `INSTALLED_APPS` cannot
forget an app.

---

## A masked field copies its mask

Paystack's secret key shows as bullets until revealed. Copying it gave
48 bullet characters, which failed as a latin-1 encoding error on an
HTTP header — an error naming nothing about the real cause.

Reveal, then copy.

---

## A test helper that discards the status code hides every failure

`return response.data` on a 404 gives `None`, and the error surfaces
later as "NoneType is not subscriptable" with no hint of what went
wrong. Assert 200 inside the helper.

---

## Swallowing a database error inside `transaction.atomic()` rescues nothing

Postgres refuses every subsequent query in that transaction, so the
failure resurfaces somewhere more confusing. Either let it raise, or do
the fallible work outside the block.

Django's `TestCase` wraps each test in its own transaction, so "outside
the atomic block" in application code is still inside the test's one.

---

## A model built around one channel encodes that channel in its required fields

`Job.intake_by`, `Receipt.cashier`, `Receipt.daily_sheet` and
`JobFile.uploaded_by` all assumed a person at a counter. An online order
has none of them, and each surfaced one at a time as an IntegrityError
over an hour.

When adding a second channel, read the first channel's required fields
before writing anything.

---

## Railway volumes attach to one service

The web container's uploads are invisible to the worker, so conversion
copied artwork that was not there. Media moved to Cloudflare R2.

---

## Run `npm run build` before pushing the frontend

A route referencing a component with no import blanked the entire
storefront in production. The build catches it in under a second.

Three separate crashes came from a new import sitting beside the old one
rather than replacing it: `Identifier 'X' has already been declared`.

---

## A paste that stops partway leaves a function with no return

`_lines_with_artwork` ended at `lines = []` and returned `None`, which
surfaced as a 200 response with a null body. The symptom was nowhere
near the cause, and four rounds went into database archaeology first.

When a function returns `None` unexpectedly, read the function before
theorising.

---

## Don't move people automatically

An auto-redirect on the payment confirmation page went wrong three
different ways: stranded on reload, hung waiting for cleared storage,
and gone before anyone could copy the link.

The page is the destination.

---

## Don't put anything load-bearing in browser storage

A cleared cart, a second device, or a reload an hour later all have to
work. Ask the server, with something from the URL.

---

## Never tell someone a payment failed when it might not have

They will pay again. Say it is being confirmed, and let the text catch
up.

---

## A refusal should name what the person can do about it

Six lines of "Madina Branch has no large format printer" tells a
customer nothing. "SAV Sticker isn't something we can make right now —
remove it, or call us" does.

Internal detail belongs in the log, not on the screen.

## 13 October 2026

- Assert against model constants (`Job.Payment.SETTLED`), never string literals. A literal test pins whatever the code wrote.
- `choices` are not enforced on `create()` or `.update()`. Check any new writer to a state field against the enum.
- Correct data by what it is linked to (`OnlineOrder`), not by a label that may itself be wrong (`intake_channel`).
- After a push, confirm the worker's active deploy, not just the web service's. Conversion and the ready text run in the worker.
- Check `git log origin/main` before testing a deploy. A pasted commit block can silently not run, and a push can fail on the network.
- Load test objects the way the views load them. Views prefetch; a fresh object hides stale-cache bugs.
- See a regression test fail without the fix before trusting it.
- Rebuild `$labels` before every full test run; a stale list silently skips new test files.

## 14 to 17 October 2026

### Files and editing

- **After a commit, read `git status` before moving on.** The `JobStep`
  model and its migration were left out of the commit that depended on
  them; a push would have broken the deploy. An untracked file the
  commit needed is a broken commit.
- **Confirm a pasted file landed in the right file.** The floor views
  were pasted into `steps.py`, and the API file into `MachineLanes.jsx`.
  A `Select-String` count of the class or function in each file catches
  it before anything runs.
- **Give whole files when an edit touches several places.** Several
  Find/Change blocks in one file is where pastes go wrong.
- **Two different files never share a name in one delivery.** The model
  and the service were both `final_check.py`; the model went in both
  places. Name them so they cannot be confused.
- **File names must match their imports exactly, capitals included.**
  `Finalcheckmodal.jsx` worked on Windows, which ignores case, and would
  have failed on Vercel's Linux build. Renaming only the capitals takes
  two steps on Windows.
- **Watch for editor auto-imports.** VS Code added
  `from django.template.backends import django` to a migration, and
  `django.db...` then failed. Prefer `models.SET_NULL` over the long path.
- **PowerShell's `-Path apps\**\*.py` does not recurse.** Use
  `Get-ChildItem -Recurse`, or name the file.
- **Line numbers move; search by name.** Reading "lines 1278–1385" after
  a day of edits caught the wrong code. Find the `class` or `def` first.

### Django and the database

- **`select_for_update()` cannot lock the nullable side of a join.**
  With `select_related` over a nullable foreign key, PostgreSQL refuses.
  Use `select_for_update(of=('self',))`.
- **Help text is part of a migration.** Rewording a field's help text
  made Django want a new migration. After a hand-written migration, run
  `makemigrations --check --dry-run`; it must say "No changes detected".
- **A test's rollback restores the database, not the cache.** Prices
  cached in one test leaked into the next. Tests that price anything
  clear the cache in `setUp`.
- **A cache needs invalidating where the data changes.** The pricing
  rule cache held a changed price for five minutes; a signal on save and
  delete clears it. Queryset `.update()` skips signals, so prices are
  changed by saving.
- **A new boolean with `default=False` empties whatever filters on it**
  until data sets it. `Service.online` emptied the storefront catalogue
  between the deploy and the seed. Plan the seed straight after.
- **Run a data change only once the code that reads it is deployed.**
  A GHS 30 minimum meant "per line" only under the new engine; under the
  old one it would have been GHS 30 a piece.
- **A test run that finds the test database "in use"** has a stuck
  connection from an earlier run. Restart the web container.

### Pricing

- **Read how the engine uses a value before passing it.** Tier flat
  prices are multiplied by `pages`, so passing a page count to an
  envelope multiplied its price. Pass only what selects a tier.
- **Look at the live rules before designing around them.** Binding was
  priced by ring size, not sheet count; the tiers in production said so.

### The frontend

- **A fresh `[]` fallback in a hook's dependencies re-runs it forever.**
  `service?.addons || []` made a new list each render and would have
  re-asked for the price in a loop. Hold it with `useMemo`.
- **A browser will not frame another site's page** that sets
  `X-Frame-Options`. Fetch the file and frame a local copy.
- **When the frontend and backend must change together,** push the
  backend, wait for the deploy, push the frontend straight after, and
  expect the old page to meet the new rules for a minute.
- **Vercel deploys the frontend, Railway the backend.** "Is it deployed"
  is two questions, asked in two places.

### Reading the floor

- **A rule written from one example breaks on the next.** "A station
  with no machine types is a bench" held for hand finishing and broke on
  cutting, which has machines for other work. Decide from the specific
  route step, not the general station.

  ## 18–20 October 2026

### Testing
- **Name test files, never folders.** `apps` is a namespace package, so `manage.py test apps.jobs` fails with "expected str … not NoneType". Build the labels from the files (the `$labels` loop) and pass those.
- **A test that counts queued on-commit callbacks breaks when a new callback joins.** When adding one (the silent nudge), make the test check each callback by name rather than raising the number.
- **Pasted test methods need their 4-space indent.** An unindented `def` leaves the class and gives "unindent does not match any outer indentation level". Show lines with `[ ]` brackets and `→` for tabs to see it.

### Windows, OneDrive, PowerShell
- **OneDrive placeholders hide folders from recursive searches** (mode `l`, e.g. `dar--l`). Go into the folder directly rather than searching from above.
- **The Desktop lives in OneDrive** (`OneDrive\Desktop`); `$HOME\Desktop` does not exist. Save scratch files in the project and delete them before committing.
- **`mkdir` with braces is literal in PowerShell**: `{api,components}` makes a folder with that name. Remove with `Remove-Item -LiteralPath … -Recurse`.
- **`git add` with one missing path adds nothing at all**, so the commit and push that follow are empty. Check `git status` after adding.

### Where a change shows
- **The preview shows this machine; the website shows GitHub; the phone shows the last APK.** A change reaches the website when pushed, and the phone when the APK is rebuilt and reinstalled.
- **The app preview needs `?app`**, remembered in localStorage until `?web`. `npx vite --mode app` talks to Railway; plain `npx vite` to local Docker.

### Server
- **A cached list must be cleared whenever its source changes**, not only on create. The services list was cached 30 minutes and only creating a service cleared it, so photos and descriptions seemed to "need time to sync". A post_save/post_delete signal on Service now clears it.
- **Paged responses must be followed to the end.** The BM catalogue read only page one of prices (20), so every later service looked unpriced. Lists a screen needs whole: `pagination_class = None`, and the front end follows `next` anyway.
- **Company-wide prices are read with `?company=1`.** Reading by branch found nothing once branch prices were removed, and setting a branch price silently overrode the company one.
- **A service function that raises ValueError needs its view to catch it**, or a duplicate name is a 500 and the form says only "Failed".
- **R2 API keys are scoped per bucket.** A new bucket needs adding to the token, or every request is a 403 (HeadObject: Forbidden).
- **Catalogue photos are public; customer files are private.** Never serve a catalogue photo through MEDIA_URL (it checks who is asking); never put customer artwork in the public bucket.
- **Photos straight from a generator or phone are 2–6 MB.** Convert to ~1200×800 JPG (about 150 KB) before they go anywhere near the app or a bucket.

### App behaviour
- **Watch by moment, not by stage.** A ready order is the one being collected right now, so it is checked every 3 seconds; one being made every 15; a collected one not at all.
- **Silent nudges keep screens current.** Every stage move sends a data-only push after commit; the app also refreshes when it comes back to the front, because a nudge sent while it was in the background is not heard.
- Run a suite by its module (`apps.jobs.tests`), not its app (`apps.jobs`): `apps` has no `__init__.py`, so discovery crashes before any test runs.
- Read `git status` before committing, not just run it. An untracked file under `apps/` means that feature isn't in production, however green the tests are.
- Run a suite by its module (`apps.jobs.tests`), not its app (`apps.jobs`): `apps` has no `__init__.py`, so discovery crashes before any test runs.
- Read `git status` before committing, not just run it. An untracked file under `apps/` means that feature isn't in production, however green the tests are.