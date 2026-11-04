# Todo

Updated 17 October 2026.

## Coordinator portal ✅ (live)
- [x] Phase 1: clearing puts a job in press; stage moves reach tracking; ready text
- [x] Phase 2: strict queue by promise; claims; board flags
- [x] Phase 3: stepper, arrivals queue, inspection modal, ready modal, stage lists
- [x] Specification corrections during inspection, with the customer's words
- [x] Machine lanes for In press and Finishing (steps, queues, Done, Move)
- [x] Final check of ordered against made at each piece's last step
- [x] PDFs preview inside the inspection modal
- [x] Add-ons shown under their piece
- [ ] Info strip: real "On the floor" and "Machines" numbers
- [ ] Remove the old `deadline`-as-promised display wherever it is left

## The floor ✅ (live)
- [x] `JobStep`, machine assignment, per-machine queues, by-hand steps, one bench
- [x] Machine down affects only its own work
- [x] Live estimate per stage (`stage_estimate` on tracking)
- [ ] Show `stage_estimate` on the customer's tracking page (print-octos `Track.jsx`)
- [ ] Info strip numbers come from the floor payload
- [ ] Operator extension: technicians tap Done themselves

## Catalogue
- [x] Batch 1: everyday prints online, add-ons, business cards by the box
- [x] Batch 2: one product per print, sides as a choice
- [x] Batch 3: line minimum, SAV cutting, free eyelets, flyers 10+, sizes as typed
- [ ] Clear bag price (then it switches on by itself)
- [ ] Envelope capacity: does a large one-for-all order need more than one envelope?
- [ ] Next batches from the master spreadsheet, one service at a time (cards and stationery, apparel, engraving, ID cards, books)
- [ ] Normalise units (`sheet`, `PER_PAGE`, `PER_COPY`, `piece`, `flat` for one idea)
- [ ] Hide add-on-only services (Cut to shape, Eyelets) from the counter list
- [ ] When the ET680 arrives: add the machine, set `SAV_CUT_BY_HAND = False`, re-run the seed
- [ ] Quieter seed output: report what changed, not everything it set

## Storefront
- [x] Business cards per box
- [x] Paystack hand-off message
- [ ] Checkout: keep the server's sheet count; ignore the browser's on re-price
- [ ] Every online order converts with a promise (05399 had none)
- [ ] Em-dashes mangled to `???` in catalogue descriptions
- [ ] Checkout first-name field shows the server's value
- [ ] Downloadable receipt (button exists, disabled)
- [ ] Photos for document printing (A4, A3)
- [ ] Restore the unconditional Sunday block in `SheetEngine.get_or_open_today()` before go-live

## Lateness (Phase 4)
- [ ] Every job gets a promise at intake, counter jobs included
- [ ] Revised promises: keep the original, record revision, who, why, customer told
- [ ] At-risk and late detection; branch manager and customer told

## Counter
- [ ] Processed counter jobs join the coordinator's queue after the deposit, with a promise on the receipt (agreed, parked)
- [ ] Coordinator day sign-off

## Housekeeping
- [ ] `PaymentTextTests.test_it_fits_in_one_message` has no body
- [ ] `apps.inventory.tests` needs `__init__.py` to run by label
- [ ] `original_filename` stores the device's name

## Done (18–20 October 2026)
- [x] App redesign: Home, Categories, product page, Cart, Orders (groups, History chain), Order details, Account, Notifications
- [x] Notifications grouped by order, with product and payment
- [x] Silent nudges on every stage move; refresh on resume; watch by moment
- [x] In-app directions (map, route, turn banner, by car / on foot)
- [x] Collection at the counter: PIN, QR, attendant Collect, hand over, Collected flowing back
- [x] Service photos in the public R2 bucket; storefront and app prefer them
- [x] BM catalogue: company prices read (all pages) and set; services list refreshes on any change; duplicates answer plainly
- [x] Mangled dashes in descriptions mended

## Next
- [ ] Waiting-area board (TV): Being made / Ready to collect, short numbers only
- [ ] Google Play: developer account, signed release build, listing, 14-day closed test with 12+ testers
- [ ] Buy printoctos.com (privacy policy, store listings, images.printoctos.com for photos)
- [ ] Apple developer account (iPhone app via TestFlight), when ready

## Tidy-ups
- [ ] Clock-dependent tests that fail on Sundays and evenings: pin the dates
- [ ] Rebuild the local web and worker images (`docker-compose build web worker`) so google-auth is baked in
- [ ] Clear Bag has no price
- [ ] Review the envelope services (four of them) and Photo Printing vs Photo Printing (Full Photo)
- [ ] Photos for envelopes and scanning
- [ ] The View button on a customer's own file (needs a short-lived private link)
- [ ] Shelf location when marking an order ready (optional)
- [ ] `promised_for` sometimes empty on converted orders (05399)

## 27 Oct 2026 — counter New Job (finishing, files, one job per attempt)

- Paste tests and the commit separately. If any step is red, stop: don't commit.
- Put the mixin first: `class X(Mixin, Base)`, never `class X(Base, Mixin)`.
- A field declared on a serializer must also be listed in `fields`.
- If an input-only serializer field has the same name as a model field, make it `write_only=True` (`addons` on JobLineItem caused a 500).
- When a file has been replaced several times, check for something only the newest copy contains, and check the file name (NewJob vs NewCustomer).
- In a React component, define each part before anything that uses it.
- Names alone can't tell a person from their company. Compare the record kind too, and keep merges undoable.

# WhatsApp webhook (Step 1) — 4 Nov 2026

## Goal
Meta can verify our endpoint, and every inbound message and delivery/read status
reaches Octos, is checked as genuinely from Meta, and is stored without loss or duplication.

## Plan
- [ ] Settings: read WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, WHATSAPP_API_VERSION
      explicitly in settings.py (the mNotify lesson: getattr silently returned '')
- [ ] Model `WhatsAppEvent`: raw payload (JSON), received_at, processed_at, error.
      Every POST is stored before anything else happens.
- [ ] Model `InboundMessage`: wamid (unique), wa_phone, profile_name, type, text,
      sent_at, customer (nullable FK, matched by phone), event FK
- [ ] Service `signature.py`: HMAC-SHA256 of the raw body with the app secret,
      hmac.compare_digest against X-Hub-Signature-256
- [ ] Service `inbound.py`: parse an event into InboundMessages + status log lines;
      idempotent on wamid (Meta re-delivers)
- [ ] View (plain Django View, csrf_exempt, no JWT):
      GET  → hub.mode=subscribe + token match → echo hub.challenge, else 403
      POST → signature fails → 403; empty secret → 403 + logged error (never accept unsigned);
             else store WhatsAppEvent → dispatch Celery task → 200 immediately
- [ ] Celery task `process_whatsapp_event(event_id)`: runs inbound.py, sets processed_at / error
- [ ] URL: /api/v1/whatsapp/webhook/
- [ ] Management command `whatsapp_subscribe`: POST /{WABA}/subscribed_apps, prints the result
      (verifiable, repeatable, no hand-typed curl)
- [ ] Tests: GET good/bad token; POST bad/missing signature → 403; good signature → 200 +
      event stored; same wamid twice → one InboundMessage; status payload parsed
- [ ] Railway: APP_SECRET + VERIFY_TOKEN as shared variables (web + worker)
- [ ] Brother pastes URL + verify token in WhatsApp → Configuration, subscribes to `messages`
- [ ] Run whatsapp_subscribe in the Railway shell (after the deploy is live)
- [ ] Prove it: send a message to +233 55 196 9777 → InboundMessage row appears

## Out of scope (later steps)
Status updates on the text log (Step 3), inbox UI (Step 4), templates (Step 2)

## Review
(filled in when done)

## Step 5: Octos answers (the point of all of this)

### Goal
A customer who writes when nobody is watching feels heard, by name, in
their own register, with real answers from the floor. Clearly Octos,
Farhat's assistant; never stiff, never a menu, never a wall of text.

### Principles (locked)
- Introduces itself once per conversation ("Octos here, Farhat's assistant")
- Short: one idea per message, the way people text. Mirrors the greeting.
  Emoji and "hmm" / "oops" where a person would use them
- Grounded: every fact comes from the floor (jobs, promises, catalogue,
  branch availability, prices, hours). Nothing invented
- Never commits the floor: times only from the promise engine
- Doesn't know → hands to the team and says when they'll pick it up
- Steps back the moment a staff member joins; staff can take over any time
- Asks which branch only when it physically matters (a pickup) and
  nothing (recent jobs, wall QR) already says
- Files sent on WhatsApp become draft jobs on that branch's counter screen

### Shape (to design properly before building)
- Language model reads the message: intent, job code, quantities,
  service, branch, files
- Octos's own services fetch the facts
- Model writes the reply from those facts only, in the house voice
- A check before sending: every time, price, code and status in the reply
  must appear in the facts, or the reply is not sent
- Voice guide in Khofi's voice with real examples, shared with the Step 2
  templates so automatic and template messages sound like one person
- Test library of real customer messages ("please are you around",
  "boss is my job ready", file + "I'll be there in 10 minutes"),
  each with the expected behaviour, run before any change goes live
- Kill switch, per-conversation limits, every reply logged and reviewable

### Rollout
- [ ] 5a Draft: Octos writes, staff approve in the inbox. Builds the
      voice and the test library from real conversations
- [ ] 5b Answer: autonomous for intents proven safe in 5a
      (job status, hours, "do you do X")
- [ ] 5c Intake: files and quantities become draft jobs at the counter

### Depends on
Step 1 (receive), Step 3 (send), Step 4 (inbox + media download within
WhatsApp's ~30 days), catalogue availability, promise engine