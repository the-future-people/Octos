from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.hr.models import (
    Employee, PayrollRecord, JobPosition,
    Applicant, StageScore, StageQuestionnaire, OnboardingRecord
)
from apps.hr.recruitment_engine import RecruitmentEngine
from apps.hr.onboarding_engine import OnboardingEngine
from .serializers import (
    EmployeeSerializer, PayrollRecordSerializer, JobPositionSerializer,
    ApplicantListSerializer, ApplicantDetailSerializer, ApplicantCreateSerializer,
    StageTransitionSerializer, StageScoreCreateSerializer,
    OnboardingSerializer, StageQuestionnaireSerializer
)


# --- Job Positions ---

class JobPositionListView(generics.ListAPIView):
    serializer_class = JobPositionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = JobPosition.objects.select_related('branch', 'role').all()
        status_param = self.request.query_params.get('status')
        branch_id = self.request.query_params.get('branch')
        if status_param:
            qs = qs.filter(status=status_param)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs


class JobPositionCreateView(generics.CreateAPIView):
    serializer_class = JobPositionSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class JobPositionDetailView(generics.RetrieveUpdateAPIView):
    queryset = JobPosition.objects.select_related('branch', 'role').all()
    serializer_class = JobPositionSerializer
    permission_classes = [IsAuthenticated]


# --- Applicants ---

class ApplicantListView(generics.ListAPIView):
    serializer_class = ApplicantListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'email', 'phone']

    def get_queryset(self):
        qs = Applicant.objects.select_related(
            'position', 'position__branch'
        ).all()
        stage = self.request.query_params.get('stage')
        channel = self.request.query_params.get('channel')
        position_id = self.request.query_params.get('position')
        is_priority = self.request.query_params.get('is_priority')
        if stage:
            qs = qs.filter(stage=stage)
        if channel:
            qs = qs.filter(channel=channel)
        if position_id:
            qs = qs.filter(position_id=position_id)
        if is_priority is not None:
            qs = qs.filter(is_priority=is_priority.lower() == 'true')
        return qs


class ApplicantDetailView(generics.RetrieveAPIView):
    queryset = Applicant.objects.select_related(
        'position', 'position__branch', 'recommended_by', 'assigned_hr'
    ).prefetch_related('stage_scores').all()
    serializer_class = ApplicantDetailSerializer
    permission_classes = [IsAuthenticated]


class ApplicantCreateView(generics.CreateAPIView):
    serializer_class = ApplicantCreateSerializer
    permission_classes = [IsAuthenticated]


class ApplicantTransitionView(APIView):
    """
    Advance applicant to next stage.
    POST /api/v1/hr/applicants/{id}/transition/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            applicant = Applicant.objects.get(pk=pk)
        except Applicant.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = StageTransitionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            engine = RecruitmentEngine(applicant)
            result = engine.advance(
                to_stage=serializer.validated_data['to_stage'],
                actor=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ApplicantRejectView(APIView):
    """
    Reject an applicant with a reason.
    POST /api/v1/hr/applicants/{id}/reject/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            applicant = Applicant.objects.get(pk=pk)
        except Applicant.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('reason', '')
        try:
            engine = RecruitmentEngine(applicant)
            result = engine.reject(actor=request.user, reason=reason)
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ApplicantSendOfferView(APIView):
    """
    Send employment offer to applicant.
    POST /api/v1/hr/applicants/{id}/send-offer/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            applicant = Applicant.objects.get(pk=pk)
        except Applicant.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            engine = RecruitmentEngine(applicant)
            result = engine.send_offer(actor=request.user)
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ApplicantOfferResponseView(APIView):
    """
    Record applicant's response to offer.
    POST /api/v1/hr/applicants/{id}/offer-response/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            applicant = Applicant.objects.get(pk=pk)
        except Applicant.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)

        accepted = request.data.get('accepted')
        if accepted is None:
            return Response(
                {'detail': 'accepted field is required (true or false).'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            engine = RecruitmentEngine(applicant)
            result = engine.record_offer_response(
                accepted=bool(accepted),
                actor=request.user
            )
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# --- Stage Scores ---

class StageScoreCreateView(APIView):
    """
    Record a score for an applicant at a specific stage.
    POST /api/v1/hr/applicants/{id}/score/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            applicant = Applicant.objects.get(pk=pk)
        except Applicant.DoesNotExist:
            return Response({'detail': 'Applicant not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = StageScoreCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        score = StageScore.objects.create(
            applicant=applicant,
            scored_by=request.user,
            **serializer.validated_data
        )

        return Response({
            'success': True,
            'stage': score.stage,
            'normalized_score': score.normalized_score,
            'passed': score.passed,
        }, status=status.HTTP_201_CREATED)


# --- Questionnaires ---

class StageQuestionnaireListView(generics.ListAPIView):
    serializer_class = StageQuestionnaireSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StageQuestionnaire.objects.filter(is_active=True)
        stage = self.request.query_params.get('stage')
        if stage:
            qs = qs.filter(stage=stage)
        return qs


# --- Onboarding ---

class OnboardingDetailView(generics.RetrieveAPIView):
    queryset = OnboardingRecord.objects.select_related('applicant', 'conducted_by').all()
    serializer_class = OnboardingSerializer
    permission_classes = [IsAuthenticated]


class OnboardingUpdateView(APIView):
    """
    Progressively update onboarding details.
    PATCH /api/v1/hr/onboarding/{id}/update/
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            record = OnboardingRecord.objects.get(pk=pk)
        except OnboardingRecord.DoesNotExist:
            return Response({'detail': 'Onboarding record not found.'}, status=status.HTTP_404_NOT_FOUND)

        engine = OnboardingEngine(record)
        result = engine.update_details(request.data)
        return Response(result)


class OnboardingCompleteView(APIView):
    """
    Complete onboarding — creates Employee and portal account.
    POST /api/v1/hr/onboarding/{id}/complete/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            record = OnboardingRecord.objects.get(pk=pk)
        except OnboardingRecord.DoesNotExist:
            return Response({'detail': 'Onboarding record not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            engine = OnboardingEngine(record)
            result = engine.complete(actor=request.user)
            return Response(result)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# --- Employees ---

class EmployeeListView(generics.ListAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['employee_number', 'user__first_name', 'user__last_name']

    def get_queryset(self):
        qs = Employee.objects.select_related('user', 'branch', 'role').all()
        branch_id = self.request.query_params.get('branch')
        status_param = self.request.query_params.get('status')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class EmployeeDetailView(generics.RetrieveUpdateAPIView):
    queryset = Employee.objects.select_related('user', 'branch', 'role').all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]


# --- Payroll ---

class PayrollListView(generics.ListAPIView):
    serializer_class = PayrollRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = PayrollRecord.objects.select_related('employee').all()
        employee_id = self.request.query_params.get('employee')
        status_param = self.request.query_params.get('status')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class PayrollDetailView(generics.RetrieveUpdateAPIView):
    queryset = PayrollRecord.objects.select_related('employee').all()
    serializer_class = PayrollRecordSerializer
    permission_classes = [IsAuthenticated]