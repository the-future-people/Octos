"""
The vocabulary of the spine: every kind of event Octos knows.

An event's kind is written as noun.verb_in_past_tense, because an event is a
fact that already happened ("message.received", never "receive_message").
record() refuses any kind not listed here, so a typo is an error, not a
silent new kind nobody will ever query.

Add a kind here first, in the same change that starts recording it.
"""

# WhatsApp and other channels
MESSAGE_RECEIVED = 'message.received'        # a customer's message reached us
MESSAGE_SENT = 'message.sent'                # we sent a message (Octos or staff)
MESSAGE_DELIVERED = 'message.delivered'      # the provider says it arrived on the phone
MESSAGE_READ = 'message.read'
MESSAGE_FAILED = 'message.failed'            # the provider refused or never answered
FILE_RECEIVED = 'file.received'              # a customer's file was saved
FILE_MEASURED = 'file.measured'              # pages, size, DPI etc. worked out

# Who is handling a conversation
STAFF_TOOK_OVER = 'staff.took_over'
STAFF_HANDED_BACK = 'staff.handed_back'
OCTOS_TOOK_BACK = 'octos.took_back'          # the handover watcher took it back
OCTOS_ASKED_FOR_PERSON = 'octos.asked_for_person'   # Octos handed over and said why
STAFF_REMINDED = 'staff.reminded'            # a customer waited 30 minutes on a person
CONVERSATION_RESOLVED = 'conversation.resolved'

# The counter (Layer 2 starts recording these)
PRESENCE_COUNTER = 'presence.counter'        # verified: the customer is at a counter
COUNTER_CLAIMED = 'counter.claimed'          # an attendant picked the customer up

# Octos's own decisions
OCTOS_REPLIED = 'octos.replied'
OCTOS_STAYED_SILENT = 'octos.stayed_silent'
OCTOS_HANDED_OVER = 'octos.handed_over'      # replied (or not) and brought a person in
OCTOS_SHADOWED = 'octos.shadowed'            # shadow mode: wrote a note, sent nothing
OCTOS_BLOCKED = 'octos.blocked'              # a reply was stopped by a check (e.g. an unlooked-up price)
OCTOS_FAILED = 'octos.failed'                # Octos itself errored; a person was brought in

# Jobs, quotes and money
QUOTE_GIVEN = 'quote.given'
PAYMENT_LINK_SENT = 'payment.link_sent'
PAYMENT_SUCCEEDED = 'payment.succeeded'
JOB_CREATED = 'job.created'
JOB_STATUS_CHANGED = 'job.status_changed'    # any move without a more meaningful name
JOB_DEPOSIT_PAID = 'job.deposit_paid'
JOB_PAID = 'job.paid'                        # payment settled in full
JOB_READY = 'job.ready'                      # work reached DONE
JOB_COLLECTED = 'job.collected'              # handed over to the customer
JOB_CANCELLED = 'job.cancelled'
JOB_HALTED = 'job.halted'
JOB_RESUMED = 'job.resumed'

# Customers
VISIT_CLOSED = 'visit.closed'                # a visit ended: by an outcome, or quiet for 2 hours

CUSTOMER_REGISTERED = 'customer.registered'
CUSTOMER_MATCHED = 'customer.matched'        # a sender was linked to an existing customer

ALL = {
    value for name, value in globals().items()
    if name.isupper() and isinstance(value, str)
}
