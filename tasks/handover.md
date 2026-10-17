# Print Octos — where things stand

Updated 17 October 2026. First written 13 October, the day the
storefront ran end to end on real money. Since then: the catalogue
rebuilt around what Westland actually sells, finishing the customer
chooses, and a final check before anything is handed over.

Paste this at the start of a new session to pick up without
re-explaining. The whole platform is in `docs/continuity.md`; this is
the storefront.

---

## What a customer does

1. **Landing.** Two sections: *Order ahead* (banners, SAV, business
   cards) and *Documents & flyers*. One tile per product. What cannot be
   made yet shows as *Coming soon* and cannot be opened.
2. **Specify.**
   - Prints and flyers: *Front only* or *Front and back*, number of
     copies. No page count to type: it comes from the uploaded file.
   - Flexy and SAV: width and height exactly as typed, from 1in. Under
     the GHS 30 line minimum, the page offers the pieces it covers
     ("Make it 83").
   - Business cards: boxes of 100.
   - *Finishing · optional*: lamination, ring binding (ring size chosen
     from the sheets), brown envelope (one for all copies or one per
     copy), cut to shape on SAV, free eyelets on flexy. What has no
     price or machine yet is shown greyed: *Not available yet*.
   - The price box breaks the total down by the item and each add-on.
3. **Continue.** Only now does anything reach the server.
4. **Checkout.** Lines with their add-ons beneath, quantity steppers,
   phone and first name, branch options with ready times.
5. **Pay.** A full-screen *Taking you to Paystack* covers the hand-off;
   coming back with the back button clears it.
6. **Confirmation**, **a text**, **tracking**: unchanged.

---

## What happens behind it

Unchanged from the first handover: webhook, `PaystackEvent`, paid,
`convert_order` in the worker, receipt, today's sheet, text. Two
additions:

- **Add-ons become job lines attached to their piece**
  (`JobLineItem.parent`), each with its own price, and their routes
  join the piece's on the floor.
- **The page count is the server's.** At commit, after the artwork
  verdict is verified, sheets per copy are worked out from the file's
  pages and the sides. The browser's number is never used for that.

---

## Where the catalogue comes from

`python manage.py seed_catalogue` in the Railway shell, `--dry-run`
first. Each batch is what Khofi agreed, service by service. Re-running
is safe. The master spreadsheet holds the services still to agree.

A service appears on the storefront when `online` is set. It can be
ordered when it has a price and every machine its route needs exists
at the branch; nobody switches that by hand.

---

## Decisions worth not relitigating

The first handover's still stand (nothing reaches the server until
Continue; the confirmation is the destination; nothing load-bearing in
browser storage; `intake_by` and `cashier` empty on online work; each
payment attempt its own reference; media on R2). Added since:

- **One product per print.** Each side keeps its own service and price;
  the storefront groups them.
- **Pages come from the file**, counted on the server.
- **Add-ons are ordinary services** with their own price and route.
- **The minimum is per order line**, and the customer is offered the
  pieces it covers rather than charged for air.
- **Packing is the customer's call**: one for all copies or one per
  copy, with Octos suggesting.

---

## What's wrong right now

- **Checkout re-prices from the browser's line details** when a
  quantity changes, page count included.
- **Some orders convert with no promise.**
- **Tracking does not show the live estimate** the backend returns.
- **Em-dashes mangled to `???`** in descriptions.
- **The first-name field on checkout** shows what was typed.
- **No photos** for document printing yet.

## Still to build

- The live estimate on the tracking page
- A downloadable receipt (button there, disabled)
- Shared project-level variables on Railway
- Restoring the unconditional Sunday block before go-live