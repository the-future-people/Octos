---
branch: kingshub
when: Sunday morning
topic: open on sundays
---
Customer: Goodmorning . Do you come on Sundays please
Staff: Hello
Staff: No please
Customer: Okay thank you
Customer: I want more stickers . 300 pieces of 2.5
Customer: So tomorrow
Customer: Thanks
Customer: And I’ll come and print some documents in the morning . Hope you’ll be there
*(6 hours later)*
Staff: Yes
Staff: Okay
*(next day, 9:10am)*
Customer: [sends a PDF, 2 pages]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 7 pages]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 1 page]
Customer: [sends a PDF, 5 pages]
Customer: [sends a PDF, 7 pages]
*(next day, 2:33pm)*
Customer: Goodafternoon
Customer: Please will I get the stickers tomorrow
Customer: And how much for the 300 pieces
*(next day, 2:49pm)*
Customer: Goodafternoon
Staff: Ei
  Good Afternoon
Customer: Can I get them tomorrow ?
Staff: Oh yea
  Its escaped me, its would have been ready today
Customer: Okay what time should I come tomorrow ?
Customer: And how much for 300 pieces
*(2 days later, 9:52am)*
Customer: Goodmorning
Customer: Please can I come for the stickers
Customer: And what’s the price
---
Octos should:
1. "Do you come on Sundays?": closed Sundays, with when it reopens (branch calendar). Offer to take the order now so it's ready on arrival.
2. The sticker order (300 pcs, 2.5in, "tomorrow"): confirm it, and give the price (pricing engine) and a ready time (promise engine) in the same reply. Create the job. Here she asked the price three times over three days.
3. The 10 PDFs with no instructions: acknowledge with the count, and ask once for what's missing (copies, colour, binding).
4. "Will I get the stickers tomorrow?": answer from the job's status; if late, say so plainly with a new time.
Never: let an order live only in the chat (here it was forgotten: "it escaped me"); leave a price question unanswered.
