from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.finance.models import (
    DailySalesSheet,
    CashierFloat,
    PettyCash,
    POSTransaction,
    Receipt,
    CreditAccount,
    CreditPayment,
    BranchTransferCredit,
)
from apps.finance.sheet_engine import SheetEngine
from apps.finance.receipt_engine import ReceiptEngine
from apps.finance.credit_engine import CreditEngine

from .serializers import (
    DailySalesSheetListSerializer,
    DailySalesSheetDetailSerializer,
    DailySalesSheetNotesSerializer,
    CashierFloatSerializer,
    CashierFloatSetSerializer,
    CashierFloatCloseSerializer,
    PettyCashSerializer,
    PettyCashCreateSerializer,
    POSTransactionSerializer,
    POSSettleSerializer,
    ReceiptSerializer,
    CreditAccountSerializer,
    CreditAccountCreateSerializer,
    CreditAccountApproveSerializer,
    CreditPaymentSerializer,
    CreditSettlementSerializer,
    BranchTransferCreditSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Daily Sales Sheet
# ─────────────────────────────────────────────────────────────────────────────

class DailySalesSheetListView(generics.ListAPIView):
    """
    GET /api/v1/finance/sheets/
    Returns sheets for the requesting user's branch.
    Belt/Region managers see all sheets across their scope.
    """
    serializer_class   = DailySalesSheetListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = DailySalesSheet.objects.select_related(
            'branch', 'opened_by', 'closed_by'
        )

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(date=date_param)

        return qs


class DailySalesSheetDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/sheets/<id>/
    Full sheet detail including floats and petty cash.
    """
    serializer_class   = DailySalesSheetDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs   = DailySalesSheet.objects.select_related(
            'branch', 'opened_by', 'closed_by'
        ).prefetch_related(
            'cashier_floats', 'petty_cash_entries'
        )
        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(branch=user.branch)
        return qs


class DailySalesSheetTodayView(APIView):
    """
    GET /api/v1/finance/sheets/today/
    Returns today's open sheet for the user's branch.
    Creates one if it doesn't exist (fallback open).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not hasattr(user, 'branch') or not user.branch:
            return Response(
                {'detail': 'User has no branch assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sheet, _ = SheetEngine(user.branch).get_or_open_today(
            opened_by=user,
        )

        if sheet is None:
            return Response(
                {'detail': 'No sheet today — branch may be closed (Sunday).'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.db.models import Sum
        from apps.jobs.models import Job

        data = DailySalesSheetDetailSerializer(
            sheet, context={'request': request}
        ).data

       # If sheet is still open, inject live totals from actual jobs
        if sheet.status == DailySalesSheet.Status.OPEN:
            jobs = Job.objects.filter(
                daily_sheet=sheet,
                status=Job.COMPLETE,
            )
            data['total_cash']         = str(jobs.filter(payment_method='CASH').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_momo']         = str(jobs.filter(payment_method='MOMO').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_pos']          = str(jobs.filter(payment_method='POS').aggregate(t=Sum('amount_paid'))['t'] or 0)
            data['total_jobs_created'] = jobs.count()
            data['net_cash_in_till']   = str(jobs.filter(payment_method='CASH').aggregate(t=Sum('amount_paid'))['t'] or 0)

        return Response(data)


class DailySalesSheetNotesView(APIView):
    """
    PATCH /api/v1/finance/sheets/<id>/notes/
    BM can add or update notes on a sheet.
    Numbers are never touched.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.status != DailySalesSheet.Status.OPEN:
            return Response(
                {'detail': 'Cannot edit a closed sheet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DailySalesSheetNotesSerializer(
            sheet, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data)


class DailySalesSheetCloseView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/close/
    BM manually closes the sheet.
    Blocked if non-carryover pending payments exist.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.select_related('branch').get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            engine = SheetEngine(sheet.branch)
            closed = engine.close_sheet(
                sheet,
                closed_by=request.user,
                auto=False,
            )
            return Response(
                DailySalesSheetDetailSerializer(
                    closed, context={'request': request}
                ).data
            )
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Cashier Float
# ─────────────────────────────────────────────────────────────────────────────

class CashierFloatSetView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/floats/set/
    BM sets the opening float for a cashier at day start.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CashierFloatSetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from apps.accounts.models import CustomUser
        from django.utils import timezone

        try:
            cashier = CustomUser.objects.get(
                pk=serializer.validated_data['cashier_id']
            )
        except CustomUser.DoesNotExist:
            return Response(
                {'detail': 'Cashier not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        float_record, created = CashierFloat.objects.get_or_create(
            daily_sheet=sheet,
            cashier=cashier,
            defaults={
                'opening_float' : serializer.validated_data['opening_float'],
                'float_set_by'  : request.user,
                'float_set_at'  : timezone.now(),
            },
        )

        if not created:
            return Response(
                {'detail': 'Float already set for this cashier today.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            CashierFloatSerializer(float_record).data,
            status=status.HTTP_201_CREATED,
        )


class CashierFloatCloseView(APIView):
    """
    POST /api/v1/finance/floats/<id>/close/
    Cashier submits their closing cash count.
    Variance is computed automatically.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            float_record = CashierFloat.objects.get(pk=pk)
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Float record not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CashierFloatCloseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        float_record.closing_cash   = serializer.validated_data['closing_cash']
        float_record.variance_notes = serializer.validated_data.get(
            'variance_notes', ''
        )
        float_record.compute_variance()
        float_record.save(update_fields=[
            'closing_cash', 'variance_notes', 'variance', 'updated_at'
        ])

        return Response(CashierFloatSerializer(float_record).data)


# ─────────────────────────────────────────────────────────────────────────────
# Petty Cash
# ─────────────────────────────────────────────────────────────────────────────

class PettyCashCreateView(APIView):
    """
    POST /api/v1/finance/sheets/<id>/petty-cash/
    Record a petty cash disbursement — requires BM approval.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response(
                {'detail': 'Sheet not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sheet.status != DailySalesSheet.Status.OPEN:
            return Response(
                {'detail': 'Cannot record petty cash on a closed sheet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PettyCashCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            float_record = CashierFloat.objects.get(
                pk=serializer.validated_data['cashier_float_id'],
                daily_sheet=sheet,
            )
        except CashierFloat.DoesNotExist:
            return Response(
                {'detail': 'Cashier float not found for this sheet.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.utils import timezone

        entry = PettyCash.objects.create(
            daily_sheet   = sheet,
            cashier_float = float_record,
            amount        = serializer.validated_data['amount'],
            category      = serializer.validated_data['category'],
            purpose       = serializer.validated_data['purpose'],
            approved_by   = request.user,
            approved_at   = timezone.now(),
            recorded_by   = request.user,
        )

        return Response(
            PettyCashSerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# POS Transactions
# ─────────────────────────────────────────────────────────────────────────────

class POSTransactionListView(generics.ListAPIView):
    """
    GET /api/v1/finance/pos/
    Returns POS transactions for the user's branch.
    Filter by status: ?status=PENDING | SETTLED | REVERSED
    """
    serializer_class   = POSTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user   = self.request.user
        qs     = POSTransaction.objects.select_related('job', 'cashier')
        status_param = self.request.query_params.get('status')

        if hasattr(user, 'branch') and user.branch:
            qs = qs.filter(job__branch=user.branch)
        if status_param:
            qs = qs.filter(status=status_param)

        return qs


class POSTransactionSettleView(APIView):
    """
    POST /api/v1/finance/pos/<id>/settle/
    Mark a POS transaction as settled by the bank.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            txn = POSTransaction.objects.get(pk=pk)
        except POSTransaction.DoesNotExist:
            return Response(
                {'detail': 'POS transaction not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if txn.status != POSTransaction.Status.PENDING:
            return Response(
                {'detail': f"Transaction is already {txn.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = POSSettleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone

        txn.status          = POSTransaction.Status.SETTLED
        txn.settlement_date = serializer.validated_data['settlement_date']
        txn.settled_by      = request.user
        txn.save(update_fields=[
            'status', 'settlement_date', 'settled_by', 'updated_at'
        ])

        return Response(POSTransactionSerializer(txn).data)


# ─────────────────────────────────────────────────────────────────────────────
# Receipts
# ─────────────────────────────────────────────────────────────────────────────

class ReceiptDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/receipts/<id>/
    """
    serializer_class   = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    queryset           = Receipt.objects.select_related('job', 'cashier')


class ReceiptSendWhatsAppView(APIView):
    """
    POST /api/v1/finance/receipts/<id>/send-whatsapp/
    Re-send or send receipt via WhatsApp.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            receipt = Receipt.objects.select_related(
                'job__branch'
            ).get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine  = ReceiptEngine(receipt.job.branch)
        success = engine.send_whatsapp(receipt)

        if success:
            return Response({'detail': 'Receipt sent via WhatsApp.'})
        return Response(
            {'detail': 'WhatsApp delivery failed — check phone number.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ReceiptThermalView(APIView):
    """
    GET /api/v1/finance/receipts/<id>/thermal/
    Returns the thermal-formatted receipt as plain text.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            receipt = Receipt.objects.select_related(
                'job__branch', 'cashier'
            ).get(pk=pk)
        except Receipt.DoesNotExist:
            return Response(
                {'detail': 'Receipt not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        engine = ReceiptEngine(receipt.job.branch)
        text   = engine.format_thermal(receipt)

        return Response({'text': text})


# ─────────────────────────────────────────────────────────────────────────────
# Credit Accounts
# ─────────────────────────────────────────────────────────────────────────────

class CreditAccountListView(generics.ListAPIView):
    """
    GET /api/v1/finance/credit/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditAccount.objects.select_related(
            'customer', 'recommended_by', 'approved_by'
        )


class CreditAccountDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/finance/credit/<id>/
    """
    serializer_class   = CreditAccountSerializer
    permission_classes = [IsAuthenticated]
    queryset           = CreditAccount.objects.select_related(
        'customer', 'recommended_by', 'approved_by'
    )


class CreditAccountCreateView(APIView):
    """
    POST /api/v1/finance/credit/
    BM recommends a credit account.
    Belt Manager approves via separate endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreditAccountCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from apps.customers.models import CustomerProfile

        try:
            customer = CustomerProfile.objects.get(
                pk=serializer.validated_data['customer_id']
            )
        except CustomerProfile.DoesNotExist:
            return Response(
                {'detail': 'Customer not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if hasattr(customer, 'credit_account'):
            return Response(
                {'detail': 'Customer already has a credit account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account = CreditAccount.objects.create(
            customer          = customer,
            account_type      = serializer.validated_data['account_type'],
            credit_limit      = serializer.validated_data['credit_limit'],
            payment_terms     = serializer.validated_data.get('payment_terms', 30),
            organisation_name = serializer.validated_data.get('organisation_name', ''),
            contact_person    = serializer.validated_data.get('contact_person', ''),
            contact_phone     = serializer.validated_data.get('contact_phone', ''),
            notes             = serializer.validated_data.get('notes', ''),
            recommended_by    = request.user,
            approved_by       = request.user,  # placeholder — overwritten on approval
            status            = CreditAccount.Status.SUSPENDED,  # inactive until approved
        )

        return Response(
            CreditAccountSerializer(account).data,
            status=status.HTTP_201_CREATED,
        )


class CreditAccountApproveView(APIView):
    """
    POST /api/v1/finance/credit/<id>/approve/
    Belt Manager approves or rejects a recommended credit account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.get(pk=pk)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CreditAccountApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from django.utils import timezone

        if serializer.validated_data['approved']:
            account.status      = CreditAccount.Status.ACTIVE
            account.approved_by = request.user
            account.approved_at = timezone.now()
            account.notes       = serializer.validated_data.get('notes', account.notes)
        else:
            account.status = CreditAccount.Status.CLOSED
            account.notes  = serializer.validated_data.get('notes', account.notes)

        account.save()

        return Response(CreditAccountSerializer(account).data)


# ─────────────────────────────────────────────────────────────────────────────
# Credit Settlements
# ─────────────────────────────────────────────────────────────────────────────

class CreditSettlementView(APIView):
    """
    POST /api/v1/finance/credit/<id>/settle/
    Record a credit settlement payment against an account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            account = CreditAccount.objects.select_related('customer').get(pk=pk)
        except CreditAccount.DoesNotExist:
            return Response(
                {'detail': 'Credit account not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CreditSettlementSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user  = request.user
        sheet = self._get_today_sheet(user)
        if not sheet:
            return Response(
                {'detail': 'No open sheet for today — cannot process settlement.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            engine  = CreditEngine(account)
            payment = engine.settle(
                amount            = serializer.validated_data['amount'],
                payment_method    = serializer.validated_data['payment_method'],
                actor             = user,
                daily_sheet       = sheet,
                momo_reference    = serializer.validated_data.get('momo_reference', ''),
                pos_approval_code = serializer.validated_data.get('pos_approval_code', ''),
                notes             = serializer.validated_data.get('notes', ''),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CreditPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )

    def _get_today_sheet(self, user):
        from django.utils import timezone
        try:
            return DailySalesSheet.objects.get(
                branch=user.branch,
                date=timezone.localdate(),
                status=DailySalesSheet.Status.OPEN,
            )
        except DailySalesSheet.DoesNotExist:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Branch Transfer Credits
# ─────────────────────────────────────────────────────────────────────────────

class BranchTransferCreditListView(generics.ListAPIView):
    """
    GET /api/v1/finance/transfers/
    Belt Manager sees all pending transfer credits for reconciliation.
    """
    serializer_class   = BranchTransferCreditSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs           = BranchTransferCredit.objects.select_related(
            'job', 'origin_branch', 'destination_branch', 'reconciled_by'
        )
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class BranchTransferCreditReconcileView(APIView):
    """
    POST /api/v1/finance/transfers/<id>/reconcile/
    Belt Manager marks a transfer credit as reconciled.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            transfer = BranchTransferCredit.objects.get(pk=pk)
        except BranchTransferCredit.DoesNotExist:
            return Response(
                {'detail': 'Transfer credit not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if transfer.status == BranchTransferCredit.Status.RECONCILED:
            return Response(
                {'detail': 'Already reconciled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone

        transfer.status               = BranchTransferCredit.Status.RECONCILED
        transfer.reconciled_by        = request.user
        transfer.reconciled_at        = timezone.now()
        transfer.reconciliation_notes = request.data.get('notes', '')
        transfer.save(update_fields=[
            'status', 'reconciled_by',
            'reconciled_at', 'reconciliation_notes', 'updated_at',
        ])

        return Response(BranchTransferCreditSerializer(transfer).data)

class DailySalesSheetPDFView(APIView):
    """
    GET /api/v1/finance/sheets/<pk>/pdf/
    Generates and serves the day sheet as a read-only PDF.
    Only accessible by branch manager of that branch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = DailySalesSheet.objects.get(pk=pk)
        except DailySalesSheet.DoesNotExist:
            return Response({'detail': 'Sheet not found.'}, status=404)

        # Only allow access to own branch
        if request.user.branch != sheet.branch:
            return Response({'detail': 'Access denied.'}, status=403)

        # Only closed sheets can be downloaded
        if sheet.status != DailySalesSheet.Status.CLOSED:
            return Response(
                {'detail': 'Sheet must be closed before downloading.'},
                status=400
            )

        # Generate PDF
        import os
        from django.conf import settings
        from io import BytesIO
        from django.core.management import call_command

        media_root = getattr(settings, 'MEDIA_ROOT', 'media')
        sheets_dir = os.path.join(media_root, 'sheets')
        os.makedirs(sheets_dir, exist_ok=True)
        output_path = os.path.join(sheets_dir, f"sheet_{sheet.pk}_{sheet.date}.pdf")

        # Regenerate if file doesn't exist
        if not os.path.exists(output_path):
            call_command('generate_sheet_pdf', sheet_id=sheet.pk, output=output_path)

        # Serve the file
        from django.http import FileResponse
        response = FileResponse(
            open(output_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="sheet_{sheet.branch.code}_{sheet.date}.pdf"'
        )
        return response