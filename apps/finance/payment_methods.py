"""
The one place that says what a payment method is.

Before this file, "which payment methods exist" was written out by hand in
about twenty places: sheet totals, summary services, revenue selectors,
serializers, PDFs. They mostly agreed, because they were copied from each
other. Adding a method meant finding all twenty, and the one that got
missed failed silently — SheetEngine._snapshot_totals sorted receipts with
an if/elif chain, so a method it did not recognise landed in no total at
all and the money vanished from the books with no error raised.

Everything that needs to know about payment methods reads this instead.

Each method declares what the rest of the system actually asks about it:

    in_till       Is this money physically in the cashier's drawer?
                  Only CASH is. This is what keeps online and card money
                  out of a cashier's variance — she can only be held to
                  what she can count.

    collected     Did the branch receive this money at all? Cash, momo and
                  POS arrive at the branch. Credit is owed, not received.
                  Online lands in an HQ account — the branch earns it but
                  never touches it.

    sheet_field   The DailySalesSheet column this method totals into, or
                  None if it does not total anywhere. Adding a method with
                  a new column means a migration, which is deliberate:
                  these are frozen financial records and a real column
                  carries a type and a constraint that a loose key does not.

    can_split     Can this be one leg of a split payment?
    can_settle    Can this settle a credit account balance?
    requires      The field that must be present for the payment to be
                  valid — a momo reference, a POS approval code.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PaymentMethod:
    code        : str
    label       : str
    in_till     : bool
    collected   : bool
    sheet_field : Optional[str]
    can_split   : bool = False
    can_settle  : bool = False
    requires    : Optional[str] = None
    # What the required value must look like, when it matters. MoMo
    # references are 11 digits; a POS code has no fixed shape.
    requires_digits : Optional[int] = None


CASH = PaymentMethod(
    code='CASH', label='Cash',
    in_till=True, collected=True,
    sheet_field='total_cash',
    can_split=True, can_settle=True,
)

MOMO = PaymentMethod(
    code='MOMO', label='Mobile Money',
    in_till=False, collected=True,
    sheet_field='total_momo',
    can_split=True, can_settle=True,
    requires='momo_reference', requires_digits=11,
)

POS = PaymentMethod(
    code='POS', label='POS',
    in_till=False, collected=True,
    sheet_field='total_pos',
    can_split=True, can_settle=True,
    requires='pos_approval_code',
)

CREDIT = PaymentMethod(
    code='CREDIT', label='Credit Account',
    in_till=False, collected=False,
    sheet_field='total_credit_issued',
)

# Every method, in the order they should be displayed.
METHODS = (CASH, MOMO, POS, CREDIT)

BY_CODE = {m.code: m for m in METHODS}


def get(code):
    """The method, or None if the code is not one we know."""
    return BY_CODE.get(code)


def choices(*, can_split=None, can_settle=None, collected=None):
    """
    Django/DRF choices, narrowed to the methods that belong in a given
    place. A split leg cannot be a credit account; a credit settlement
    cannot itself be credit.
    """
    out = []
    for m in METHODS:
        if can_split  is not None and m.can_split  != can_split:
            continue
        if can_settle is not None and m.can_settle != can_settle:
            continue
        if collected  is not None and m.collected  != collected:
            continue
        out.append((m.code, m.label))
    return out


def codes(**kwargs):
    """Just the codes, narrowed the same way as choices()."""
    return [code for code, _ in choices(**kwargs)]


def sheet_fields():
    """
    Every DailySalesSheet total a method writes into, as
    {field name: [method codes that feed it]}.

    Methods can share a field, so this is built as a mapping rather than
    assuming one column each.
    """
    fields = {}
    for m in METHODS:
        if m.sheet_field:
            fields.setdefault(m.sheet_field, []).append(m.code)
    return fields


def zero_totals():
    """A fresh {field: Decimal('0.00')} for every field a method feeds."""
    return {field: Decimal('0.00') for field in sheet_fields()}