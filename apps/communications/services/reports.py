"""
Octos's report on one of its own messages (8 Nov 2026): what it did and why,
in plain words, for staff in the inbox only, never sent to the customer.

Built from the AssistantRun behind the message: the tools Octos used, what
they returned, and whether it asked for a person. None when Octos did nothing
worth explaining.
"""
# What each tool means, said the way staff would say it.
PHRASES = {
    'find_services':     ('ok',   'Looked up the catalogue'),
    'quote':             ('ok',   'Priced it'),
    'prepare_order':     ('ok',   'Prepared the order'),
    'send_payment_link': ('ok',   'Sent the payment link'),
    'send_proforma':     ('ok',   'Issued a proforma'),
    'branch_hours':      ('info', 'Checked the opening hours'),
    'customer_jobs':     ('info', 'Looked up their jobs'),
    'hand_to_person':    ('warn', 'Asked for a person'),
}
PRICED = ('quote', 'prepare_order', 'send_proforma')


def _result(call):
    for key in ('result', 'output', 'content'):
        value = call.get(key)
        if isinstance(value, dict):
            return value
    return {}


def is_octos_message(message):
    """Said by Octos to the customer: outbound, no person, not a note, some words."""
    from apps.communications.models import Message
    return (message.direction == Message.OUTBOUND and not message.sent_by_id
            and not message.is_internal_note and bool(message.body))


def runs_by_reply(conversation_id):
    """A chat's runs, in one query, by what Octos said (the latest wins)."""
    from apps.communications.models import AssistantRun
    runs = {}
    for run in (AssistantRun.objects.filter(conversation_id=conversation_id)
                .only('id', 'reply', 'tool_calls', 'decision', 'reason').order_by('id')):
        if run.reply:
            runs[run.reply] = run
    return runs


_NOT_GIVEN = object()


def octos_report(message, run=_NOT_GIVEN):
    if not is_octos_message(message):
        return None
    if run is _NOT_GIVEN:   # one message on its own; a whole chat passes its runs in
        run = runs_by_reply(message.conversation_id).get(message.body)
    if run is None:
        return None

    steps, seen = [], []
    for call in (run.tool_calls or []):
        name = call.get('name', '') if isinstance(call, dict) else ''
        tone, words = PHRASES.get(name, ('info', name.replace('_', ' ').capitalize() or 'Used a tool'))
        result = _result(call) if isinstance(call, dict) else {}
        if result.get('error'):
            tone, words = 'warn', f"{words}: {str(result['error'])[:90]}"
        elif name in PRICED and result.get('total'):
            words = f"{words}: {result['total']}"
        if name == 'hand_to_person' and run.reason:
            words = f'Asked for a person: {run.reason[:120]}'
        steps.append([tone, words])
        short = PHRASES.get(name, (None, words))[1]
        if short not in seen:
            seen.append(short)
    if run.decision == run.HANDED_OVER and not any(c.get('name') == 'hand_to_person' for c in (run.tool_calls or []) if isinstance(c, dict)):
        steps.append(['warn', 'Asked for a person' + (f': {run.reason[:120]}' if run.reason else '')]); seen.append('Asked for a person')
    if not steps:
        return None
    return {'summary': ', '.join(seen[:3]) + (' and more' if len(seen) > 3 else ''), 'steps': steps}
