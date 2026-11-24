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
