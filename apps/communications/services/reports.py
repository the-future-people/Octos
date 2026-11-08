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


def octos_report(message):
    from apps.communications.models import Message
    if (message.direction != Message.OUTBOUND or message.sent_by_id or message.is_internal_note
            or not message.body):
        return None
    run = message.conversation.assistant_runs.filter(reply=message.body).order_by('-id').first()
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
