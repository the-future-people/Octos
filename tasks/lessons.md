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