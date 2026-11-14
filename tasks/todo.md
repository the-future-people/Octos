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
