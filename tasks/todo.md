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