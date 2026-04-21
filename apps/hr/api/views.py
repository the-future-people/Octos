import secrets
import string

from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.http import FileResponse, Http404
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError

from apps.hr.models import (
    JobPosition, Applicant, StageScore,
    StageQuestionnaire, OnboardingRecord, OfferLetter,
)
from apps.hr.api.serializers import (
    PublicVacancySerializer,
    PublicApplicationSerializer,
    OnboardingFormSerializer,
    JobPositionSerializer,
    ApplicantListSerializer,
    ApplicantDetailSerializer,
    StageScoreCreateSerializer,
    RecommendSerializer,
    AppointSerializer,
    DecideSerializer,
    VerifyInfoSerializer,
    EmploymentDetailsSerializer,
    IssueOfferSerializer,
    OfferLetterSerializer,
    OnboardingRecordSerializer,
)


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — /api/v1/careers/
# ══════════════════════════════════════════════════════════════════════════════

class PublicVacancyListView(APIView):
    """
    GET /api/v1/careers/vacancies/
    List all open vacancies grouped by branch. No auth required.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        vacancies = JobPosition.objects.filter(
            status=JobPosition.OPEN,
        ).select_related('branch', 'role').order_by('branch__name', 'title')

        grouped = {}
        general = []
        for v in vacancies:
            if not v.is_open:
                continue
            data = PublicVacancySerializer(v).data
            if v.branch:
                key = v.branch.name
                if key not in grouped:
                    grouped[key] = {
                        'branch_id'   : v.branch.id,
                        'branch_name' : v.branch.name,
                        'branch_code' : v.branch.code,
                        'vacancies'   : [],
                    }
                grouped[key]['vacancies'].append(data)
            else:
                general.append(data)

        result = list(grouped.values())
        if general:
            result.append({
                'branch_id'   : None,
                'branch_name' : 'General / Any Branch',
                'branch_code' : None,
                'vacancies'   : general,
            })

        return Response(result)


class PublicVacancyDetailView(APIView):
    """
    GET /api/v1/careers/vacancies/<id>/
    Single vacancy detail. No auth required.
    """
    permission_classes = [AllowAny]

    def get(self, request, pk):
        vacancy = get_object_or_404(
            JobPosition,
            pk=pk,
            status=JobPosition.OPEN,
        )
        return Response(PublicVacancySerializer(vacancy).data)


class PublicApplyView(APIView):
    """
    POST /api/v1/careers/apply/
    Submit a job application with CV and cover letter. No auth required.
    """
    permission_classes = [AllowAny]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = PublicApplicationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        applicant = serializer.save()
        return Response({
            'message'      : 'Application submitted successfully. We will be in touch.',
            'applicant_id' : applicant.id,
            'full_name'    : applicant.full_name,
        }, status=status.HTTP_201_CREATED)


class PublicOnboardingFormView(APIView):
    """
    GET  /api/v1/careers/onboarding/<token>/  — fetch form + applicant context
    POST /api/v1/careers/onboarding/<token>/  — submit completed form
    No auth required — secured by token.
    """
    permission_classes = [AllowAny]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def _get_record(self, token):
        applicant = get_object_or_404(Applicant, onboarding_token=token)
        if not applicant.onboarding_token_valid:
            return None, Response(
                {'detail': 'This onboarding link has expired. Please contact HR.'},
                status=status.HTTP_410_GONE,
            )
        record = get_object_or_404(OnboardingRecord, applicant=applicant)
        if record.status not in (OnboardingRecord.IN_PROGRESS,):
            return None, Response(
                {'detail': 'This form has already been submitted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return record, None

    def get(self, request, token):
        record, err = self._get_record(token)
        if err:
            return err
        return Response({
            'applicant_name'      : record.applicant.full_name,
            'role'                : record._get_role_name(),
            'requires_guarantor_1': record.requires_guarantor_1(),
            'requires_guarantor_2': record.requires_guarantor_2(),
            'requires_reference'  : record.requires_reference(),
            'form'                : OnboardingFormSerializer(record).data,
        })

    def post(self, request, token):
        record, err = self._get_record(token)
        if err:
            return err

        serializer = OnboardingFormSerializer(record, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()

        complete, errors = record.is_form_complete()
        if not complete:
            return Response(
                {'detail': 'Form is incomplete.', 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record.status       = OnboardingRecord.SUBMITTED
        record.submitted_at = timezone.now()
        record.save(update_fields=['status', 'submitted_at', 'updated_at'])

        record.applicant.status = Applicant.INFORMATION_SUBMITTED
        record.applicant.save(update_fields=['status', 'updated_at'])

        return Response({'message': 'Form submitted successfully. HR will review your information.'})


# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATED — /api/v1/recruitment/
# ══════════════════════════════════════════════════════════════════════════════

class VacancyListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = JobPosition.objects.select_related('branch', 'role', 'created_by').all()

        status_filter = request.query_params.get('status')
        branch_filter = request.query_params.get('branch')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if branch_filter:
            qs = qs.filter(branch_id=branch_filter)

        return Response(JobPositionSerializer(qs, many=True).data)

    def post(self, request):
        serializer = JobPositionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class VacancyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        vacancy = get_object_or_404(JobPosition, pk=pk)
        return Response(JobPositionSerializer(vacancy).data)

    def patch(self, request, pk):
        vacancy = get_object_or_404(JobPosition, pk=pk)
        serializer = JobPositionSerializer(vacancy, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


class ApplicationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Applicant.objects.select_related(
            'vacancy', 'vacancy__branch', 'vacancy__role',
            'branch_assigned', 'role_interest', 'assigned_hr',
        ).all()

        status_filter  = request.query_params.get('status')
        track_filter   = request.query_params.get('track')
        vacancy_filter = request.query_params.get('vacancy')
        branch_filter  = request.query_params.get('branch')

        if status_filter:
            qs = qs.filter(status=status_filter)
        if track_filter:
            qs = qs.filter(track=track_filter)
        if vacancy_filter:
            qs = qs.filter(vacancy_id=vacancy_filter)
        if branch_filter:
            from django.db.models import Q
            qs = qs.filter(
                Q(vacancy__branch_id=branch_filter) |
                Q(branch_assigned_id=branch_filter)
            )

        return Response(ApplicantListSerializer(qs, many=True).data)


class ApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        applicant = get_object_or_404(
            Applicant.objects.select_related(
                'vacancy', 'vacancy__branch', 'vacancy__role',
                'branch_preference', 'branch_assigned', 'role_interest',
                'recommended_by', 'appointed_by', 'assigned_hr',
            ).prefetch_related('stage_scores'),
            pk=pk,
        )
        return Response(ApplicantDetailSerializer(applicant).data)


class ScreenApplicationView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/screen/
    HR submits CV screening scores.
    Advances applicant from RECEIVED → SCREENING.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status not in (Applicant.RECEIVED, Applicant.SCREENING):
            return Response(
                {'detail': f'Cannot screen an application in status: {applicant.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = StageScoreCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        score, _ = StageScore.objects.update_or_create(
            applicant=applicant,
            stage=StageQuestionnaire.SCREENING,
            defaults={**serializer.validated_data, 'scored_by': request.user},
        )

        applicant.status = Applicant.SCREENING
        applicant.save(update_fields=['status', 'updated_at'])

        return Response({
            'message'          : 'Screening score saved.',
            'raw_score'        : score.raw_score,
            'normalized_score' : score.normalized_score,
            'passed'           : score.passed,
            'status'           : applicant.status,
        })


class InviteToInterviewView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/invite/
    HR schedules an interview after screening passes.
    Advances applicant SCREENING → INTERVIEW_SCHEDULED.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status != Applicant.SCREENING:
            return Response(
                {'detail': 'Applicant must be in SCREENING status to invite to interview.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        screening = StageScore.objects.filter(
            applicant=applicant,
            stage=StageQuestionnaire.SCREENING,
        ).first()

        if not screening:
            return Response(
                {'detail': 'Screening score must be submitted before inviting to interview.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not screening.passed:
            return Response(
                {'detail': f'Applicant did not pass screening ({screening.raw_score}/25). Cannot invite to interview.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        scheduled_at   = request.data.get('interview_scheduled_at')
        location       = request.data.get('interview_location', '')
        interviewer_id = request.data.get('interviewer')

        if not scheduled_at:
            return Response(
                {'detail': 'interview_scheduled_at is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        interview_score, _ = StageScore.objects.get_or_create(
            applicant=applicant,
            stage=StageQuestionnaire.INTERVIEW,
            defaults={'scored_by': request.user},
        )
        interview_score.interview_scheduled_at = scheduled_at
        interview_score.interview_location     = location
        if interviewer_id:
            interview_score.interviewer_id = interviewer_id
        interview_score.save()

        applicant.status = Applicant.INTERVIEW_SCHEDULED
        applicant.save(update_fields=['status', 'updated_at'])

        return Response({
            'message' : 'Interview scheduled.',
            'status'  : applicant.status,
        })


class SubmitInterviewScoreView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/interview/
    HR submits interview scores after interview is conducted.
    Advances applicant INTERVIEW_SCHEDULED → INTERVIEW_DONE.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status not in (Applicant.INTERVIEW_SCHEDULED, Applicant.INTERVIEW_DONE):
            return Response(
                {'detail': f'Cannot submit interview score for status: {applicant.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = StageScoreCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        score, _ = StageScore.objects.update_or_create(
            applicant=applicant,
            stage=StageQuestionnaire.INTERVIEW,
            defaults={**serializer.validated_data, 'scored_by': request.user},
        )

        applicant.status = Applicant.INTERVIEW_DONE
        applicant.save(update_fields=['status', 'updated_at'])

        return Response({
            'message'          : 'Interview score saved.',
            'raw_score'        : score.raw_score,
            'normalized_score' : score.normalized_score,
            'passed'           : score.passed,
            'status'           : applicant.status,
        })


class DecideApplicationView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/decide/
    HR makes final decision: HIRE or REJECT.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status not in (
            Applicant.INTERVIEW_DONE,
            Applicant.FINAL_REVIEW,
            Applicant.APPOINTED,
        ):
            return Response(
                {'detail': f'Cannot decide application in status: {applicant.status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DecideSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        decision = serializer.validated_data['decision']

        if decision == 'HIRE':
            applicant.status = Applicant.AWAITING_ACCEPTANCE
            applicant.save(update_fields=['status', 'updated_at'])
            return Response({
                'message' : 'Applicant marked as hired. Awaiting their acceptance.',
                'status'  : applicant.status,
            })

        else:
            applicant.status           = Applicant.REJECTED
            applicant.rejection_reason = serializer.validated_data.get('rejection_reason', '')
            applicant.rejected_at      = timezone.now()
            applicant.save(update_fields=['status', 'rejection_reason', 'rejected_at', 'updated_at'])

            if applicant.vacancy:
                applicant.vacancy.status = JobPosition.OPEN
                applicant.vacancy.save(update_fields=['status', 'updated_at'])

            return Response({
                'message' : 'Applicant rejected. Vacancy reopened.',
                'status'  : applicant.status,
            })


class AcceptOfferView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/accept/
    Records candidate acceptance. Creates OnboardingRecord and sends form link.
    AWAITING_ACCEPTANCE → ONBOARDING
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status != Applicant.AWAITING_ACCEPTANCE:
            return Response(
                {'detail': 'Applicant must be in AWAITING_ACCEPTANCE status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        accepted = request.data.get('accepted', True)

        if not accepted:
            applicant.status             = Applicant.DECLINED
            applicant.offer_accepted     = False
            applicant.offer_responded_at = timezone.now()
            applicant.save(update_fields=['status', 'offer_accepted', 'offer_responded_at', 'updated_at'])

            if applicant.vacancy:
                applicant.vacancy.status = JobPosition.OPEN
                applicant.vacancy.save(update_fields=['status', 'updated_at'])

            return Response({'message': 'Offer declined. Vacancy reopened.', 'status': applicant.status})

        applicant.status             = Applicant.ONBOARDING
        applicant.offer_accepted     = True
        applicant.offer_responded_at = timezone.now()
        applicant.save(update_fields=['status', 'offer_accepted', 'offer_responded_at', 'updated_at'])

        onboarding, created = OnboardingRecord.objects.get_or_create(
            applicant=applicant,
            defaults={'conducted_by': request.user},
        )

        token = applicant.generate_onboarding_token()

        return Response({
            'message'          : 'Offer accepted. Onboarding form link generated.',
            'status'           : applicant.status,
            'onboarding_token' : token,
            'onboarding_id'    : onboarding.id,
        })


class VerifyOnboardingInfoView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/verify-info/

    Extended flow:
      1. Validates onboarding info (existing behaviour)
      2. Validates employment details (new)
      3. Checks for role conflicts (new)
      4. Creates CustomUser account with SHADOW status (new)
      5. Creates PendingActivation record (new)
      6. Returns generated credentials — shown once, never stored in plaintext (new)

    INFORMATION_SUBMITTED → INFORMATION_VERIFIED
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from django.db import transaction
        from apps.accounts.models import CustomUser, Role, StaffAssignment, PendingActivation
        from apps.accounts.assignment_service import AssignmentService, ConflictError
        from apps.organization.models import Branch, Region

        applicant  = get_object_or_404(Applicant, pk=pk)
        onboarding = get_object_or_404(OnboardingRecord, applicant=applicant)

        if applicant.status != Applicant.INFORMATION_SUBMITTED:
            return Response(
                {'detail': 'Onboarding form must be submitted before verification.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate both sections together ──────────────────
        verify_serializer = VerifyInfoSerializer(data=request.data)
        employ_serializer = EmploymentDetailsSerializer(data=request.data)

        verify_valid = verify_serializer.is_valid()
        employ_valid = employ_serializer.is_valid()

        if not verify_valid or not employ_valid:
            errors = {}
            if not verify_valid:
                errors.update(verify_serializer.errors)
            if not employ_valid:
                errors.update(employ_serializer.errors)
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        employ_data = employ_serializer.validated_data
        role        = employ_data['role']
        branch      = employ_data.get('branch')
        region      = employ_data.get('region')
        designation = employ_data['designation']
        start_date  = employ_data['start_date']
        shadow_days = employ_data.get('shadow_days', 7)

        # ── Conflict check ────────────────────────────────────
        conflict = AssignmentService.check_conflict(
            role=role,
            designation=designation,
            branch=branch,
            region=region,
        )

        conflict_user_id      = employ_data.get('conflict_user')
        conflict_resolution   = employ_data.get('conflict_resolution')
        conflict_new_branch   = employ_data.get('conflict_new_branch')
        conflict_new_role     = employ_data.get('conflict_new_role')
        conflict_new_desig    = employ_data.get('conflict_new_designation')

        if conflict and not conflict_resolution:
            # Return conflict details so the frontend can show resolution UI
            return Response({
                'conflict': True,
                'conflict_user': {
                    'id'        : conflict.user.id,
                    'full_name' : conflict.user.full_name,
                    'email'     : conflict.user.email,
                    'role'      : conflict.role.display_name,
                    'designation': conflict.designation,
                },
                'detail': (
                    f'{conflict.user.full_name} currently holds '
                    f'{conflict.role.display_name} ({conflict.designation}) '
                    f'at this location. Please specify how to handle this.'
                ),
            }, status=status.HTTP_409_CONFLICT)

        # ── Generate credentials ──────────────────────────────
        first_initial = applicant.first_name[0].lower()
        last_clean    = applicant.last_name.lower().replace(' ', '')
        username      = f"{first_initial}{last_clean}"
        email         = f"{username}@farhatprintingpress.com"

        # Ensure email uniqueness — append digit if taken
        base_email = email
        counter    = 1
        while CustomUser.objects.filter(email=email).exists():
            email = base_email.replace('@', f'{counter}@')
            counter += 1

        # Generate a secure 12-char temp password
        alphabet  = string.ascii_letters + string.digits + '!@#$%'
        temp_pass = ''.join(secrets.choice(alphabet) for _ in range(12))

        # ── Create everything atomically ──────────────────────
        with transaction.atomic():
            # 1. Mark onboarding verified
            onboarding.status             = OnboardingRecord.VERIFIED
            onboarding.verified_at        = timezone.now()
            onboarding.verified_by        = request.user
            onboarding.verification_notes = verify_serializer.validated_data.get(
                'verification_notes', ''
            )
            onboarding.save(update_fields=[
                'status', 'verified_at', 'verified_by',
                'verification_notes', 'updated_at',
            ])

            applicant.status = Applicant.INFORMATION_VERIFIED
            applicant.save(update_fields=['status', 'updated_at'])

            # 2. Create CustomUser with SHADOW status
            new_user = CustomUser.objects.create_user(
                email                = email,
                password             = temp_pass,
                first_name           = applicant.first_name,
                last_name            = applicant.last_name,
                phone                = applicant.phone or '',
                role                 = role,
                branch               = branch,
                region               = region,
                employment_status    = CustomUser.SHADOW,
                must_change_password = True,
            )

            # Auto-generate employee ID
            new_user.employee_id = f"EMP-{new_user.pk:04d}"
            new_user.save(update_fields=['employee_id', 'updated_at'])

            # 3. Create PendingActivation
            activation = PendingActivation.objects.create(
                user                     = new_user,
                applicant                = applicant,
                role                     = role,
                designation              = designation,
                branch                   = branch,
                region                   = region,
                start_date               = start_date,
                shadow_days              = shadow_days,
                conflict_user_id         = conflict_user_id.id if conflict_user_id else None,
                conflict_resolution      = conflict_resolution or '',
                conflict_new_branch      = conflict_new_branch,
                conflict_new_role        = conflict_new_role,
                conflict_new_designation = conflict_new_desig or '',
                generated_email          = email,
                generated_username       = username,
                temp_password_hash       = make_password(temp_pass),
                status                   = PendingActivation.SHADOW,
                created_by               = request.user,
            )

        return Response({
            'message'    : 'Onboarding verified. Employee account created with shadow access.',
            'status'     : applicant.status,
            'activation' : {
                'id'           : activation.id,
                'start_date'   : str(start_date),
                'shadow_days'  : shadow_days,
                'days_until_start': activation.days_until_start,
            },
            'credentials': {
                'email'     : email,
                'username'  : username,
                'temp_password': temp_pass,  # shown once — never stored in plaintext
            },
        }, status=status.HTTP_201_CREATED)


class ConflictCheckView(APIView):
    """
    GET /api/v1/recruitment/conflict-check/
    Check if a constrained role slot is already occupied.
    Called by the HR modal when role + branch/region + designation are selected.

    Query params:
      role        — role id
      designation — MAIN or DEPUTY
      branch      — branch id (optional)
      region      — region id (optional)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.accounts.models import Role, StaffAssignment
        from apps.accounts.assignment_service import AssignmentService

        role_id     = request.query_params.get('role')
        designation = request.query_params.get('designation', 'MAIN')
        branch_id   = request.query_params.get('branch')
        region_id   = request.query_params.get('region')

        if not role_id:
            return Response(
                {'detail': 'role is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            role = Role.objects.get(pk=role_id)
        except Role.DoesNotExist:
            return Response({'detail': 'Role not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not role.is_constrained:
            return Response({'conflict': False, 'constrained': False})

        branch = None
        region = None
        if branch_id:
            from apps.organization.models import Branch
            branch = Branch.objects.filter(pk=branch_id).first()
        if region_id:
            from apps.organization.models import Region
            region = Region.objects.filter(pk=region_id).first()

        conflict = AssignmentService.check_conflict(
            role=role,
            designation=designation,
            branch=branch,
            region=region,
        )

        if conflict:
            return Response({
                'conflict'     : True,
                'constrained'  : True,
                'conflict_user': {
                    'id'         : conflict.user.id,
                    'full_name'  : conflict.user.full_name,
                    'email'      : conflict.user.email,
                    'employee_id': conflict.user.employee_id,
                    'role'       : conflict.role.display_name,
                    'designation': conflict.designation,
                },
            })

        return Response({'conflict': False, 'constrained': True})


class IssueOfferLetterView(APIView):
    """
    POST /api/v1/recruitment/applications/<id>/issue-offer/
    HR generates and issues the formal offer letter PDF.
    INFORMATION_VERIFIED → OFFER_ISSUED
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        applicant = get_object_or_404(Applicant, pk=pk)

        if applicant.status != Applicant.INFORMATION_VERIFIED:
            return Response(
                {'detail': 'Information must be verified before issuing offer letter.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = IssueOfferSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        role = (
            applicant.vacancy.role if applicant.vacancy
            else applicant.role_interest
        )

        if not role:
            return Response(
                {'detail': 'Cannot determine role for offer letter.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        offer, created = OfferLetter.objects.get_or_create(
            applicant=applicant,
            defaults={
                'branch'          : data['branch'],
                'role'            : role,
                'employment_type' : data['employment_type'],
                'salary_offered'  : data['salary_offered'],
                'pay_frequency'   : data['pay_frequency'],
                'start_date'      : data['start_date'],
                'probation_months': data['probation_months'],
                'additional_terms': data.get('additional_terms', ''),
                'generated_by'    : request.user,
            },
        )

        if not created:
            for field, value in data.items():
                setattr(offer, field, value)
            offer.role         = role
            offer.generated_by = request.user
            offer.save()

        offer.status   = OfferLetter.SENT
        offer.sent_at  = timezone.now()
        offer.sent_via = applicant.preferred_channel
        offer.save(update_fields=['status', 'sent_at', 'sent_via', 'updated_at'])

        applicant.status        = Applicant.OFFER_ISSUED
        applicant.offer_sent_at = timezone.now()
        applicant.save(update_fields=['status', 'offer_sent_at', 'updated_at'])

        return Response({
            'message'  : 'Offer letter issued.',
            'status'   : applicant.status,
            'offer_id' : offer.id,
        })


class RecommendCandidateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RecommendSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        applicant = Applicant.objects.create(
            first_name          = data['first_name'],
            last_name           = data['last_name'],
            email               = data['email'],
            phone               = data['phone'],
            vacancy             = data.get('vacancy'),
            role_interest       = data.get('role_interest'),
            track               = Applicant.RECOMMENDATION,
            status              = Applicant.RECEIVED,
            is_priority         = True,
            recommended_by      = request.user,
            recommendation_note = data.get('recommendation_note', ''),
        )

        return Response({
            'message'      : f'{applicant.full_name} recommended successfully. Marked as priority.',
            'applicant_id' : applicant.id,
        }, status=status.HTTP_201_CREATED)


class AppointCandidateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AppointSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        applicant = Applicant.objects.create(
            first_name       = data['first_name'],
            last_name        = data['last_name'],
            email            = data['email'],
            phone            = data['phone'],
            vacancy          = data.get('vacancy'),
            role_interest    = data.get('role'),
            branch_assigned  = data['branch'],
            track            = Applicant.APPOINTMENT,
            status           = Applicant.AWAITING_ACCEPTANCE,
            appointed_by     = request.user,
            appointment_note = data.get('appointment_note', ''),
        )

        return Response({
            'message'      : f'{applicant.full_name} appointed directly. Awaiting their acceptance.',
            'applicant_id' : applicant.id,
            'status'       : applicant.status,
        }, status=status.HTTP_201_CREATED)


class OnboardingRecordView(APIView):
    """
    GET /api/v1/recruitment/applications/<id>/onboarding/
    HR views the full onboarding record for an applicant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        applicant  = get_object_or_404(Applicant, pk=pk)
        onboarding = get_object_or_404(OnboardingRecord, applicant=applicant)
        return Response(OnboardingRecordSerializer(onboarding).data)


from django.views import View
from django.http import FileResponse, HttpResponseForbidden, Http404
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError


class ServeCVView(View):
    """
    GET /api/v1/recruitment/applications/<id>/cv/?token=<jwt>
    Plain Django view — bypasses DRF content negotiation.
    Serves CV as inline PDF for iframe embedding.
    """
    def get(self, request, pk):
        token_str = request.GET.get('token')
        user = None

        if token_str:
            try:
                token = AccessToken(token_str)
                from apps.accounts.models import CustomUser
                user = CustomUser.objects.get(id=token['user_id'])
            except (TokenError, Exception):
                return HttpResponseForbidden('Invalid token.')

        if not user:
            return HttpResponseForbidden('Authentication required.')

        allowed_roles = {
            'HQ_HR_MANAGER', 'REGIONAL_HR_COORDINATOR',
            'BELT_MANAGER', 'REGIONAL_MANAGER', 'SUPER_ADMIN',
        }
        user_role = getattr(user.role, 'name', None)
        if user_role not in allowed_roles:
            return HttpResponseForbidden('Not authorised.')

        applicant = get_object_or_404(Applicant, pk=pk)

        if not applicant.cv:
            raise Http404('No CV on file.')

        try:
            response = FileResponse(
                applicant.cv.open('rb'),
                content_type='application/pdf',
            )
            response['Content-Disposition'] = 'inline; filename="cv.pdf"'
            response['X-Frame-Options']     = 'SAMEORIGIN'
            response['Cache-Control']       = 'private, no-store'
            return response
        except FileNotFoundError:
            raise Http404('CV file not found.')