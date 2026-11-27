# Farhat Trade Partners (B2B portal)

Started 23 Nov 2026. Interview, mocks (phone, tablet, desktop centred like the
staff portals) and every decision agreed the same day; full list in the
claude.ai project doc "B2B partner programme". Sign-ups stay closed
(PARTNER_SIGNUPS_OPEN off, invite codes only) until the machines have run 90 days.

## be20a: accounts, applications, verification, approval
- [x] 1. `apps/partners`: Partner (area+code ID, status, shop, location, contacts,
         services from our catalogue, photo, logo, terms, consent) and PartnerRep
- [x] 2. IDs: MAD-K7Q2 from the town picked, random, never reused, shown MAD·K7Q2
- [x] 3. Codes: one check shared with app sign-in (accounts.check_code); primary
         contact and rep phone both confirmed before an application is taken
- [x] 4. The switch: PARTNER_SIGNUPS_OPEN, PARTNER_INVITE_CODES
- [x] 5. Apply API: validation, duplicates (number, name+area), history as a customer
- [x] 6. Owner line: card with the shop photo, Approve / Ask for more / Decline;
         "Ask" takes his next message as the question; approve makes the business
         customer and welcomes them with the ID and 10% off the first job
- [x] 7. Unanswered "Ask for more" closes after 14 days (daily task)
- [x] 8. Tests

## be20b: trade price, rewards, partner orders
- [x] 9. 6% off every job, server-side; 10% on the first job and one in every 20;
         never on a line already at its minimum charge; rewards replace, never stack
- [x] 10. Paystack fee as its own line, paid by the partner
- [x] 11. Partner orders through the storefront's own upload and pay; no customer code
          discount on top; paid orders become jobs for the partner's business
- [x] 12. Job: trade_partner, partner_reference (plain packaging, label, board tag)
- [x] 13. Rewards progress: wrap at 15, next 10% at every 20 (paid jobs of GHS 30+)
- [x] 14. Tests

## po: Print Octos screens (desktop centred max-w-6xl, tablet tabs, phone)
- [ ] 15. Apply (4 steps) and status; sign-in by code
- [ ] 16. Dashboard, new job, jobs, rewards, shop profile

## ow: octos-web
- [ ] 17. "Trade, plain packaging" tag and the packing label (partner ID, their
          reference, job number) on the board and at collection

## Verify
- [ ] 18. Full suite; screenshots at 1440, 1024 and 390; one end-to-end test order

## Review
(filled in when done)

---

# Front-desk jobs go straight to the attendants (Phase 1)

Started 14 Nov 2026. Design agreed 13 Nov (arrival modal mock), plan approved 14 Nov.

## Decisions
- Front-desk work = a job whose every line is an INSTANT-category service. Khofi's
  list (14 Nov) covers every INSTANT service: photocopies, document printing,
  scanning, lamination, binding, passport photos, envelopes, clear bags, flyers,
  certificates, Zeta paper, DL envelopes, typing, forms and filing. So no new
  catalogue flag: the category already says it. Add one only if an instant
  service ever needs the coordinator.
- Mixed orders (any PRODUCTION or DESIGN line) go to the coordinator whole.
- `Job.front_desk` is decided once, at conversion, never recomputed.
- Phase 1 = paid remote orders through `convert()` (Print Octos, Octos on WhatsApp).
  Phase 2 = walk-in leave-behinds, jobs staff record from a WhatsApp chat.
- Front-desk work path: RECEIVED -> IN_PRODUCTION -> DONE. No machine steps.
- Rights by the job, not the role: the attendant who took it may check, start,
  hold, resume and finish it. Nothing else, and never the money.
- First to "Take it" owns it (atomic). Re-alert at 5 min is on screen; the BM is
  told once at 10 min unclaimed, counted in opening hours.

## Backend
- [ ] 1. `Job`: front_desk, desk_taken_by, desk_taken_at, desk_escalated_at + migration
- [ ] 2. Status engine: front-desk work map, `_desk_may_move`, verify skips machine steps
- [ ] 3. `jobs/services/front_desk.py`: is_front_desk_work, route, queue, take, escalate
- [ ] 4. `convert()` routes; arrivals, board and suspended lists leave front-desk jobs out
- [ ] 5. API `jobs/api/desk_views.py`: queue, take, start (two checks), done, problem, resume
- [ ] 6. Escalation task + beat entry (every minute)
- [ ] 7. Tests `jobs/tests_front_desk.py`

## Frontend (octos-web)
- [ ] 8. Work tab: waiting / mine / held, check -> start -> done, problem
- [ ] 9. Arrival modal: full when idle, bar when busy, "Take it" only, sound, louder at 5 min

## Verify
- [ ] 10. Full test run; a real Print Octos test order for photocopies lands on the
          attendant, not the coordinator; a flyer + banner order still goes to the coordinator

## Review
(filled in when done)

---

# Pay at the counter (24 Nov 2026)

Customers who'd rather send the file on WhatsApp and pay when they collect. Octos
takes the order either way; nothing reaches the floor unless it's paid or agreed.

## Decisions (Khofi, 24 Nov 2026)
- Octos accepts "I'll pay at the counter" warmly; it never pushes the link again.
- Only front-desk work (every line instant). Anything for the coordinator still
  needs its deposit first.
- Printed ahead: a known customer (a customer record, which covers anyone who has
  paid us, or a chat at least a month old), never a no-show, total up to GHS 50.
- Everyone else: prepared (file checked, priced) and printed when they arrive.
- A 4-digit pickup code, never given twice (unique for ever; 5 digits once 4 run out).
- Not collected by close of the same day: onto the Waiting for collection shelf.
  Seven days on the shelf: Octos cancels it (not an employee), deletes the file and
  records the no-show, which ends printing ahead for that customer.
- Username chats can't order without a number, so they never reach this.

## Backend
- [x] 1. Job: status AWAITING_ARRIVAL ("Pays at counter"), counter_code (unique),
         print_ahead, arrived_at, shelved_at, no_show + migration;
         OnlineOrder status COUNTER + migration
- [x] 2. Status engine: AWAITING_ARRIVAL -> PENDING_PAYMENT | CANCELLED; axis moves leave it alone
- [x] 3. jobs/services/counter_orders.py: new_code, may_print_ahead, reserve(order),
         here(job), send_to_cashier(job), shelve_due, tidy (shelve + cancel)
- [x] 4. front_desk: queue keeps waiting counter jobs (even printed), leaves shelved ones
         out; escalation skips print-on-arrival jobs nobody has come for;
         finish tells a print-ahead customer it's ready with their code
- [x] 5. Octos: pay_at_counter tool + prompt; counter QR marks them here and says the code
- [x] 6. API: queue rows carry the counter details; shelf (search), here, cashier
- [x] 7. Beat: tidy every 15 minutes
- [x] 8. Tests: jobs/tests_counter_orders.py

## Frontend (octos-web, attendant Work tab)
- [x] 9. Badges (Pays at counter · coming about 5pm / Print on arrival · 4821 / Here now),
         Send to cashier, Waiting for collection shelf with code search, They're here

## Verify
- [x] 10. Full test run, build, screenshot of the Work tab

## Review (24 Nov 2026)
- Backend be21a: 25 tests in jobs/tests_counter_orders.py; full suite 1888, only the two
  known finance failures. Status AWAITING_ARRIVAL is left alone by axis moves, the cashier
  queue, day sheets and the attendant's Today (counted unpaid).
- Print-on-arrival work starts its 5- and 10-minute clocks when the customer arrives, not
  when Octos took it; it never alerts or escalates before then.
- Octos's replies are checked for the pickup code like prices and times (checker CODE).
- octos-web: Work tab checked on screen at desktop and phone width with sample jobs.

# Quote in the chat (25 Nov 2026)

Mock agreed: claude.ai Design "Quote in the chat". Staff build a quote beside
the chat and send it without leaving it, on the same foundations as Octos's
orders, so payment, the front desk, reminders and receipts work unchanged.

## Decisions
- Prices only from the engine (price_lines / ProformaEngine), never typed.
- Three ways: payment link (default), pay at the counter (pickup code),
  proforma PDF. Tick "Attach the quote as a PDF" (on by default) for the first two.
- Pay at the counter for staff follows Octos's rule (counter_orders.reserve:
  known customer, never a no-show, up to GHS 50 is printed ahead; otherwise on
  arrival). Khofi didn't change it; asked in the delivery note.
- Proformas are issued by the Octos account (the engine's roles), noting who asked.
- Sending a quote takes the chat over from Octos, like any staff reply.

## Backend (be21f)
- [x] 1. Fix: reserve() refused a DRAFT order, so Octos's pay_at_counter right
         after prepare_order failed ("no agreed order"). Accept an open DRAFT too.
- [x] 2. prepare_order(taken_by=user): notes say who quoted, chat marker unchanged
- [x] 3. Message.order (FK to OnlineOrder), migration
- [x] 4. services/quotes.py: services list, preview (lines, total, ready), send
- [x] 5. Quote PDF (jobs/pdf/quote_pdf.py), house style
- [x] 6. send_proforma(sent_by, asked_by) for staff
- [x] 7. API: GET quote/services/, POST <id>/quote/price/, POST <id>/quote/send/
- [x] 8. Serializer: quote card data (lines, total, status, code, ready)
- [x] 9. Tests

## Frontend (octos-web)
- [x] 10. QuotePanel.jsx: search a service, its spec fields, add-ons as chips,
          file from this chat, more lines, live price, ready time, three sends,
          PDF tick, customer details when a proforma needs them, Open in Proformas
- [x] 11. Inbox: Quote button by the paperclip (computer) and in "+" (phone);
          panel beside the chat, full screen on a phone; quote card in the thread

## Verify
- [x] 12. Full test run; build; screenshots of panel and card on computer and phone

## Review (25 Nov 2026)
- be21f backend: 15 new tests (tests_quotes); full suite run before delivery.
- The DRAFT fix matters beyond the panel: until now Octos's own "pay when I
  come" only worked if a payment link had gone out first.
- Quote PDF checked by eye (rendered to PNG): per-copy unit price, so
  quantity x unit price reads as the line total.
- Panel and card checked in a harness on a computer (1440, 1680) and an
  iPhone 13: the card widens on a phone so the order number and lines fit.
- be21d (video sends) was never pushed; its four files ride with be21f,
  because views.py carries both.

# Octos on the owner's line, week of 23 Nov (26 Nov 2026)

Assessed with Khofi from the line's export (Mon 23 to Thu 26). Agreed:
Monday's brief shows Saturday; area prices round to the nearest 50 pesewas;
sizes take decimals; the test job 05286 is cancelled (console); jobs get a
readable name in Octos and the reports, the full number kept everywhere it
must be.

## Backend (be21g)
- [x] 1. Stretched letters ("Thank youuu", "okkk") read as the plain word (brain._plain)
- [x] 2. Octos on his line: the price list (find_services, quote: the customer side's own)
- [x] 3. find_job: every line of the job (what, pages, sides, copies, price)
- [x] 4. Two quick messages, one answer: text waits 4s; a newer message answers both
- [x] 5. A reminder already settled on the line stays quiet
- [x] 6. Prompt: check a job number before it goes in a draft; call jobs by name
- [x] 7. Readable job names: jobs/services/job_names.py ("Kwabena's banner (#5286)");
         in boss look-ups, the job card, slipping alerts, discount cards, reports;
         checker holds a "#5286"/"job 5286" no look-up gave
- [x] 8. Reports: Monday shows Saturday against the Saturday before; promises row
         hidden when no job had a ready time; open cash sheets only at trading
         branches; halted jobs say since when, and a cancelled job is no alert
- [x] 9. Area prices round to the nearest GHS 0.50, a piece at a time (quote_line)
- [x] 10. The price view takes decimal sizes (2.5 in)
- [x] 11. Tests

## Frontend (octos-web)
- [x] 12. NewJobModal: width and height take decimals, kept as typed

## Verify
- [x] 13. Full suite, build, a look at the size field

## Review (26 Nov 2026)
- be21g: 16 new tests (tests_owner_week_26nov); three older tests updated to
  the new rules (568.75 is now 569.00; Octos's price tools on the owner's
  line are named price_list and price, apart from the customer side's).
- Octos's tools on his line keep their own names: the same price list,
  reached through price_list and price.
- The halted alert now names the job and says since when, and the Eye shows
  the same words. A cancelled job drops out.
- Not done here: names on the staff screens (a mock first, as agreed).

# Customer chats of 25 and 26 Nov (26 Nov 2026)

Reviewed with Khofi. Grace's GHS 2 was an envelope added at the counter:
the quote was right. Shop status (lights out and the rest) is mocked
separately and waits for his look.

- [x] "Wooow thank you", "awesome thanks": goodbyes (GOODBYE_WORDS)
- [x] A file still arriving from WhatsApp: Octos waits for it (_still_reading),
      and the chat line says it's loading, never that it didn't come
- [x] Arriving mid-chat ("Im here" after sending a file): the welcome says the
      attendant has the file and the chat, instead of asking for files
- [x] A second job for an order already waiting at the counter: the job screen
      shows the code with "Use code" or "This new job replaces it" (cancelled
      once the new job saves). desk/waiting-for/, <id>/desk/replace/

## Review
- 7 new tests (tests_chat_review_26nov); full suite before delivery.
- A file is marked fetching when its download is queued (whatsapp_inbound._keep_media);
  Octos waits only on that mark. Waiting on any file without a copy held up 11
  older tests whose files never get one, and would hold a chat whose file record
  was made some other way.

# Shared links and a chat being read (27 Nov 2026)

Ekd sent two Adobe Acrobat links; Octos asked for the PDFs (the 24 Nov rule)
while Khofi was reading the chat, and Kingsford opened the links himself.
Khofi: Octos should open links and read them; a chat being read keeps Octos
quiet. The link "did nothing" when clicked: not reproduced (opens on phone
and computer in a portal-like page); asked which device and which link.

- [x] 1. services/shared_links.py: Google Drive and Docs, Dropbox, OneDrive,
         WeTransfer turned into a direct download; HTML back means private.
         Adobe Acrobat and Canva need a sign-in: left to the team.
- [x] 2. A link that can be opened becomes the customer's file in the chat
         (a document message, fetching until saved), measured like any file;
         Octos is woken for it once it's in (or failed)
- [x] 3. whatsapp_media.keep(): the save-and-measure half of fetch, shared
- [x] 4. Prompt: links we can open arrive as files; links we can't (Adobe,
         Canva, private): the team opens them, Octos asks only what's missing
         and promises no price
- [x] 5. A chat open in the inbox (shop hours): Octos waits up to 3 minutes for
         the person reading; nobody replies, it answers
- [x] 6. Tests

## Review (27 Nov 2026)
- 11 new tests (tests_links_and_reading); the 24 Nov shared-link test now
  checks the new rule.
- The link's file is a FROM_LINK message: read by Octos like any file, never
  the message answered (Message.NOT_TRIGGERS). The customer's message with
  the link is answered, after waiting for the file (fetching, 3 min at most).
- The reading wait covers messages with words only; greetings and files
  keep the counter's own rule (quiet at once, recorded).
- Live links can't be fetched from the sandbox: Google Drive, Dropbox,
  OneDrive and WeTransfer to be tried for real once deployed.

# Files at 62 and 124 seconds again (27 Nov 2026)
- [x] Today's files: 8 of 16 slow, all at ~60 or ~120 s, queue empty, worker idle
- [x] Cause: one 60 s timeout for connecting and reading the download; a dead address sat out the minute
- [x] Connecting gets 5 s, reading 30 s between pieces (whatsapp_media.WAIT_FOR_*), test in tests_files_fast
- [ ] After deploy: run the files-today check again; slow files should be gone or ~5-10 s

# An open chat holds Octos, it never silences it (27 Nov 2026)
Gifty (6 files), Moro ("Hi" + ticket), Joanbaby (photo): "a person has this chat
open", then nothing for 6-13 minutes. The counter rule stood down for good on a
greeting or a file; Khofi chose "wait, then answer".
- [x] counter.step: the open-chat skip removed
- [x] brain._being_read: greetings and files held too (3 min from the message, shop hours)
- [x] After the hold, the usual guards: a person who wrote, files already handled, a job made
- [x] Deleted at the customer's word: never-saved files marked too; fetch skips deleted files (Lorrey)
- [x] Tests: tests_open_chat_27nov (5), focus/octos_update/week_review moved to the new rule
- [ ] After deploy: a file sent to an open chat with nobody replying gets Octos's answer at ~3 min
