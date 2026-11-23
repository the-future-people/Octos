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
- [ ] 9. 6% off every job, server-side; 10% on the first job and one in every 20;
         never on a line already at its minimum charge; rewards replace, never stack
- [ ] 10. Paystack fee as its own line, paid by the partner
- [ ] 11. Partner orders through the storefront's own upload and pay; no customer code
          discount on top; paid orders become jobs for the partner's business
- [ ] 12. Job: trade_partner, partner_reference (plain packaging, label, board tag)
- [ ] 13. Rewards progress: wrap at 15, next 10% at every 20 (paid jobs of GHS 30+)
- [ ] 14. Tests

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
