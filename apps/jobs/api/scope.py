"""
Which branches' jobs a user may act on.

The finance scope (apps.core.finance_scope) answers who may see money,
and fails closed: a role it does not know sees nothing. The flow
coordinator is deliberately not a finance role — the coordinator never
touches money — so through that scope every move, halt and resume the
coordinator made answered "Job not found". Stage moves never reached the
server at all.

So jobs have their own scope: the finance scope as it stands, plus the
coordinator's own branch. What each role may then do to a job — which
axis it may move, whether it may release, whether it may take money —
is still decided by the status engine, not here. This only answers
"which jobs can you see to act on".
"""

from django.db.models import Q

from apps.core.finance_scope import get_branch_scope, get_role_name

# Branch-floor roles that act on jobs but are not finance roles.
FLOOR_ROLES = {'FLOW_COORDINATOR'}


def job_branch_scope(user):
    scope = get_branch_scope(user)
    branch_id = getattr(user, 'branch_id', None)

    if branch_id and get_role_name(user) in FLOOR_ROLES:
        return {
            'scope_label':   scope['scope_label'],
            'branch_filter': scope['branch_filter'] | Q(pk=branch_id),
        }
    return scope