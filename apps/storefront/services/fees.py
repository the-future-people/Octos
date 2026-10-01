"""
What the payment provider takes.

Paystack Ghana charges 1.95% on every local transaction — cards, mobile
money and bank transfer alike — with no flat fee and no cap. That rate
is theirs and can change, so it lives here as one figure rather than
appearing in whichever file happened to need it.

Three numbers come out, and all three are kept:

    gross   what the customer was charged
    fee     what the provider took
    net     what reached the bank

The day sheet shows the gross, so a banner sold online is comparable
with the same banner sold at the counter. It shows the net too, because
that is what has to reconcile against a bank statement. Neither stands
in for the other.

Payouts are charged separately — GHS 8 to a bank account, GHS 1 to a
mobile money wallet — but those are per settlement rather than per
transaction, so they are not a job's cost and do not belong here.
"""

from decimal import Decimal, ROUND_HALF_UP

# Paystack Ghana, local transactions, as published October 2026.
PAYSTACK_GH_RATE = Decimal('0.0195')

PESEWA = Decimal('0.01')


def split_payment(gross, rate=PAYSTACK_GH_RATE):
    """
    Split what the customer paid into the fee and what arrives.

    The net is derived by subtraction rather than calculated
    independently, so the three figures always add back to the gross
    whatever the rounding does. A day sheet that is a pesewa out
    reconciles against nothing.
    """
    gross = Decimal(str(gross)).quantize(PESEWA, rounding=ROUND_HALF_UP)
    fee = (gross * rate).quantize(PESEWA, rounding=ROUND_HALF_UP)
    net = gross - fee
    return gross, fee, net