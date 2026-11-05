"""
Who can see which conversation. Every inbox view asks here, so the
list, the detail and every action agree, and none can drift.

A branch user sees their own branch's conversations, and every company
conversation (branch empty): the central WhatsApp number belongs to no
branch, and any branch may answer it. A user with no branch (HQ) sees
everything.

Before this, the list and detail scoped by branch alone, which hid
every WhatsApp conversation from everyone; and reply, assign, resolve
and link-job didn't scope at all, so any signed-in user could act on
any branch's conversation by changing the id in the URL.
"""
from django.db.models import Q

from apps.communications.models import Conversation


def visible_conversations(user):
    qs = Conversation.objects.all()
    branch_id = getattr(user, 'branch_id', None)
    if branch_id:
        qs = qs.filter(Q(branch_id=branch_id) | Q(branch__isnull=True))
    return qs