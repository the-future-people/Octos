"""
A customer's statement (21 Nov 2026): what they owe from before, their new
work, and the total, from owing.statement().

  GET  /api/v1/finance/customers/<id>/statement/        the figures
  GET  /api/v1/finance/customers/<id>/statement/pdf/    the document
  POST /api/v1/finance/customers/<id>/statement/send/   on WhatsApp, in their chat
"""
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.customers.models import CustomerProfile
from apps.finance.services.owing import statement
from apps.finance.services.statement_pdf import build_statement_pdf, send_statement

STAFF = ('BRANCH_MANAGER', 'CASHIER', 'ATTENDANT', 'REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN')


def _scope(request, pk):
    """(customer, branch, branch_ids) or a Response refusing."""
    role = getattr(getattr(request.user, 'role', None), 'name', '')
    if role not in STAFF:
        return None, None, None, Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
    customer = CustomerProfile.objects.filter(pk=pk).first()
    if customer is None:
        return None, None, None, Response({'detail': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)
    branch = getattr(request.user, 'branch', None)
    return customer, branch, ([branch.pk] if branch else None), None


def _job(j):
    from apps.finance.services.statement_pdf import _what
    return {'id': j.pk, 'job_number': j.job_number, 'what': _what(j),
            'date': timezone.localtime(j.handed_over_at or j.created_at).date().isoformat(),
            'amount': f'{j.estimated_cost or 0:.2f}', 'paid': f'{j.amount_paid or 0:.2f}',
            'balance': f'{j.balance_due or 0:.2f}', 'delivered': j.handover_state == 'HANDED_OVER'}


class CustomerStatementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        customer, _branch, ids, refused = _scope(request, pk)
        if refused:
            return refused
        st = statement(customer, ids)
        return Response({
            'customer': {'id': customer.pk, 'name': customer.display_name, 'phone': customer.phone},
            'owed': [_job(j) for j in st['owed']], 'current': [_job(j) for j in st['current']],
            'owed_total': f"{st['owed_total']:.2f}", 'current_total': f"{st['current_total']:.2f}",
            'total': f"{st['total']:.2f}",
        })


class CustomerStatementPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        customer, branch, ids, refused = _scope(request, pk)
        if refused:
            return refused
        pdf = build_statement_pdf(statement(customer, ids), branch)
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = (f'attachment; filename="Statement-{customer.pk}-'
                                           f'{timezone.localdate():%Y-%m-%d}.pdf"')
        return response


class CustomerStatementSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        customer, branch, ids, refused = _scope(request, pk)
        if refused:
            return refused
        sent, reason = send_statement(customer, branch, ids)
        if sent:
            return Response({'detail': f'Statement sent to {customer.display_name} on WhatsApp.', 'sent': True})
        return Response({'detail': reason, 'sent': False}, status=status.HTTP_400_BAD_REQUEST)
