from django.utils import timezone
from django.db import transaction
from apps.hr.models import Applicant, StageScore, OnboardingRecord


# Pass threshold per stage
PASS_THRESHOLD = 6.0

# Offer expiry days
OFFER_EXPIRY_DAYS = 7


class RecruitmentEngine:
    """
    Controls the full applicant pipeline from application to offer.
    Every stage transition is validated and logged.
    No applicant moves between stages outside this engine.
    """

    VALID_TRANSITIONS = {
        'APPLICATION_REVIEW': ['SCREENING', 'REJECTED'],
        'SCREENING': ['INTERVIEW', 'REJECTED'],
        'INTERVIEW': ['FINAL_REVIEW', 'REJECTED'],
        'FINAL_REVIEW': ['DECISION', 'REJECTED'],
        'DECISION': ['ONBOARDING', 'REJECTED', 'OFFER_DECLINED'],
        'ONBOARDING': ['HIRED'],
        'HIRED': [],
        'REJECTED': [],
        'WITHDRAWN': [],
        'OFFER_DECLINED': [],
    }

    def __init__(self, applicant):
        self.applicant = applicant

    def can_transition(self, to_stage):
        allowed = self.VALID_TRANSITIONS.get(self.applicant.stage, [])
        return to_stage in allowed

    def get_allowed_transitions(self):
        return self.VALID_TRANSITIONS.get(self.applicant.stage, [])

    def _check_duplicate(self):
        """Check if applicant has already applied for this position."""
        return Applicant.objects.filter(
            email=self.applicant.email,
            position=self.applicant.position
        ).exclude(id=self.applicant.id).exists()

    @transaction.atomic
    def advance(self, to_stage, actor, notes=''):
        """
        Move applicant to the next stage.
        Validates transition and scores where required.
        """
        if not self.can_transition(to_stage):
            allowed = self.get_allowed_transitions()
            raise ValueError(
                f"Cannot move {self.applicant.full_name} "
                f"from '{self.applicant.stage}' to '{to_stage}'. "
                f"Allowed: {allowed}"
            )

        # For SCREENING → INTERVIEW and INTERVIEW → FINAL_REVIEW
        # check that the current stage has a passing score
        scored_stages = {
            'INTERVIEW': 'SCREENING',
            'FINAL_REVIEW': 'INTERVIEW',
            'DECISION': 'FINAL_REVIEW',
        }

        if to_stage in scored_stages:
            required_stage = scored_stages[to_stage]
            score = StageScore.objects.filter(
                applicant=self.applicant,
                stage=required_stage
            ).first()

            if not score:
                raise ValueError(
                    f"Cannot advance — no score recorded for {required_stage} stage."
                )

            if not score.passed:
                raise ValueError(
                    f"Cannot advance — applicant scored {score.normalized_score}/10 "
                    f"in {required_stage}. Minimum is {PASS_THRESHOLD}/10."
                )

        from_stage = self.applicant.stage
        self.applicant.stage = to_stage
        self.applicant.save(update_fields=['stage', 'updated_at'])

        return {
            'success': True,
            'applicant': self.applicant.full_name,
            'from_stage': from_stage,
            'to_stage': to_stage,
            'actor': actor.get_full_name() or actor.email,
            'timestamp': timezone.now().isoformat(),
        }

    @transaction.atomic
    def reject(self, actor, reason=''):
        """Reject an applicant with a reason."""
        if self.applicant.stage in ['HIRED', 'REJECTED', 'WITHDRAWN']:
            raise ValueError(f"Cannot reject applicant in stage: {self.applicant.stage}")

        self.applicant.stage = 'REJECTED'
        self.applicant.rejection_reason = reason
        self.applicant.rejected_at = timezone.now()
        self.applicant.save(update_fields=['stage', 'rejection_reason', 'rejected_at', 'updated_at'])

        return {
            'success': True,
            'applicant': self.applicant.full_name,
            'stage': 'REJECTED',
            'actor': actor.get_full_name() or actor.email,
        }

    @transaction.atomic
    def send_offer(self, actor):
        """Send employment offer to applicant."""
        if self.applicant.stage != 'DECISION':
            raise ValueError("Offer can only be sent at DECISION stage.")

        now = timezone.now()
        self.applicant.offer_sent_at = now
        self.applicant.offer_expires_at = now + timezone.timedelta(days=OFFER_EXPIRY_DAYS)
        self.applicant.save(update_fields=['offer_sent_at', 'offer_expires_at', 'updated_at'])

        return {
            'success': True,
            'applicant': self.applicant.full_name,
            'offer_sent_at': now.isoformat(),
            'offer_expires_at': self.applicant.offer_expires_at.isoformat(),
        }

    @transaction.atomic
    def record_offer_response(self, accepted, actor):
        """Record whether the applicant accepted or declined the offer."""
        if not self.applicant.offer_sent_at:
            raise ValueError("No offer has been sent to this applicant.")

        now = timezone.now()
        self.applicant.offer_accepted = accepted
        self.applicant.offer_responded_at = now

        if accepted:
            self.applicant.stage = 'ONBOARDING'
            # Trigger onboarding record creation
            OnboardingRecord.objects.get_or_create(
                applicant=self.applicant,
                defaults={'conducted_by': actor}
            )
        else:
            self.applicant.stage = 'OFFER_DECLINED'

        self.applicant.save(update_fields=[
            'offer_accepted', 'offer_responded_at', 'stage', 'updated_at'
        ])

        return {
            'success': True,
            'applicant': self.applicant.full_name,
            'offer_accepted': accepted,
            'stage': self.applicant.stage,
        }

    def get_octos_recommendation(self):
        """
        Generate Octos recommendation based on cumulative scores.
        Combined score = Screening + Interview normalized scores (max 20)
        """
        screening = StageScore.objects.filter(
            applicant=self.applicant, stage='SCREENING'
        ).first()
        interview = StageScore.objects.filter(
            applicant=self.applicant, stage='INTERVIEW'
        ).first()

        screening_score = screening.normalized_score if screening else 0
        interview_score = interview.normalized_score if interview else 0
        combined = screening_score + interview_score

        if combined >= 17:
            recommendation = 'STRONG RECOMMEND'
            color = 'green'
        elif combined >= 13:
            recommendation = 'RECOMMEND'
            color = 'blue'
        elif combined >= 10:
            recommendation = 'BORDERLINE'
            color = 'amber'
        else:
            recommendation = 'DO NOT RECOMMEND'
            color = 'red'

        return {
            'screening_score': screening_score,
            'interview_score': interview_score,
            'combined_score': combined,
            'max_score': 20,
            'recommendation': recommendation,
            'color': color,
        }

    @classmethod
    def apply(cls, applicant):
        """Convenience method to get engine for an applicant."""
        return cls(applicant)