---
branch: kingshub
when: Tuesday morning
topic: a3 colour price
---
Customer: How much is A3 colour?
Customer: 21 sheets to be bound
Staff: a page is 5 cedis please the binding will be 15 cedis
Customer: 26 sheets. Print and bind 6 sets. Please don’t mix the pages
Customer: If my calculations are right it should be GHC 870
Customer: Please text me when it is ready
Staff: Alright
Staff: Yes please
*(next day, 1:23pm)*
Customer: How far?
Staff: Please how many copies?
Customer: Black and white
  6 sets
Customer: Bind
Staff: Alright
Staff: The Black and white is done.
  We will alert soon when the guy arrives
Customer: Okay and the total bill
*(next day, 8:14am)*
Staff: Good morning boss
Staff: We are working on the color now please its will be ready soon
Staff: Thanks for your patience..
Customer: Ok please text me the TOTAL Bill
Staff: Alright...
*(2 hours later)*
Customer: Okay I am coming over
Staff: Not give me some time for the colored
Staff: will finish very soon please
Staff: i'm now sorting it
Staff: to bind
*(3 hours later)*
Customer: Progress?
Staff: I’m sorting two of the black and white and it’s will be done
Customer: Okay
Staff: please its ready
Customer: Okay
*(5 hours later)*
Staff: Seen with Thanks
*(next day, 6:56am)*
Customer: Both black and white 5 sets. Good morning
Staff: Good morning boss
Staff: Please is it A4 or A3?
Customer: A 3
Staff: Alright
Staff: Are we binding?
Customer: Yessah
Customer: I will need them today please
Staff: Yes I’m on it
Staff: Please its ready
Customer: Okay
---
Octos should:
1. "How much is A3 colour, 21 sheets to be bound?": the per-page price and the binding price, then the total for what he described.
2. "26 sheets, 6 sets... should be GHC 870": confirm or correct his total from the pricing engine, before work starts.
3. "Text me when it's ready" and every "How far?" / "Progress?": status from the job, with what's done and what's left.
4. "Text me the TOTAL bill": give it the first time it's asked. Here it was asked three times.
Never: make the customer work out the bill alone; wait until pickup to state the total.
