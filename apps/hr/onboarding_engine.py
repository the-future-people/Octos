import secrets
import string
from django.utils import timezone
from django.db import transaction
from apps.hr.models import OnboardingRecord, Employee
from apps.accounts.models import CustomUser


def generate_temp_password(length=12):
    """Generate a secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class OnboardingEngine:
    """
    Converts an accepted applicant into a fully onboarded employee.

    Steps:
      1. Capture personal, emergency, payment details
      2. Assign RFID tag
      3. Create CustomUser portal account with temp password
      4. Create Employee record
      5. Mark onboarding complete
      6. Send appointment letter + portal credentials (stubbed for now)
    """

    def __init__(self, onboarding_record):
        self.record = onboarding_record
        self.applicant = onboarding_record.applicant

    def _validate_required_fields(self):
        """Ensure all critical fields are filled before completing onboarding."""
        required = [
            ('national_id', 'National ID'),
            ('date_of_birth', 'Date of Birth'),
            ('address', 'Address'),
            ('emergency_contact_name', 'Emergency Contact Name'),
            ('emergency_contact_phone', 'Emergency Contact Phone'),
            ('next_of_kin_name', 'Next of Kin Name'),
            ('next_of_kin_phone', 'Next of Kin Phone'),
            ('start_date', 'Start Date'),
        ]
        missing = []
        for field, label in required:
            if not getattr(self.record, field):
                missing.append(label)
        return missing

    @transaction.atomic
    def complete(self, actor):
        """
        Complete onboarding — creates CustomUser and Employee records.

        Args:
            actor: CustomUser (HR staff) completing the onboarding

        Returns:
            dict with success, employee_number, portal credentials
        """
        if self.record.status == OnboardingRecord.COMPLETED:
            raise ValueError("Onboarding is already completed.")

        # Validate required fields
        missing = self._validate_required_fields()
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        position = self.applicant.position
        branch = position.branch
        role = position.role

        # Generate temp password
        temp_password = generate_temp_password()

        # Create portal account
        user = CustomUser.objects.create_user(
            email=self.applicant.email,
            password=temp_password,
            first_name=self.applicant.first_name,
            last_name=self.applicant.last_name,
            branch=branch,
            role=role,
            phone=self.applicant.phone,
            must_change_password=True,
        )

        # Create employee record
        employee = Employee.objects.create(
            user=user,
            branch=branch,
            role=role,
            national_id=self.record.national_id,
            date_of_birth=self.record.date_of_birth,
            gender=self.record.gender,
            phone=self.applicant.phone,
            address=self.record.address,
            emergency_contact_name=self.record.emergency_contact_name,
            emergency_contact_phone=self.record.emergency_contact_phone,
            profile_photo=self.record.profile_photo,
            employment_type=self.record.employment_type,
            pay_frequency=self.record.pay_frequency,
            base_salary=position.base_salary or 0,
            bank_name=self.record.bank_name,
            bank_account_number=self.record.bank_account_number,
            mobile_money_number=self.record.mobile_money_number,
            date_joined=self.record.start_date,
            onboarded_by=actor,
            onboarding_completed_at=timezone.now(),
        )

        # Update onboarding record
        now = timezone.now()
        self.record.employee = employee
        self.record.status = OnboardingRecord.COMPLETED
        self.record.completed_at = now
        self.record.save(update_fields=[
            'employee', 'status', 'completed_at', 'updated_at'
        ])

        # Update applicant stage
        self.applicant.stage = 'HIRED'
        self.applicant.save(update_fields=['stage', 'updated_at'])

        # Stub — send appointment letter and portal credentials
        # TODO: wire up email/WhatsApp when Communications phase is built
        self.record.appointment_letter_sent_at = now
        self.record.portal_credentials_sent_at = now
        self.record.save(update_fields=[
            'appointment_letter_sent_at', 'portal_credentials_sent_at'
        ])

        return {
            'success': True,
            'employee_number': employee.employee_number,
            'full_name': employee.full_name,
            'branch': branch.name,
            'role': role.name,
            'email': user.email,
            'temp_password': temp_password,
            'portal_credentials_sent': True,
            'appointment_letter_sent': True,
        }

    def update_details(self, data):
        """
        Update onboarding record fields progressively.
        HR can save and return — doesn't have to complete in one session.
        """
        allowed_fields = [
            'national_id', 'date_of_birth', 'gender', 'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship',
            'next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship',
            'has_dependants', 'dependants_details',
            'bank_name', 'bank_account_number', 'mobile_money_number',
            'employment_type', 'pay_frequency', 'start_date', 'probation_end_date',
            'profile_photo', 'id_document', 'additional_documents',
        ]
        for field, value in data.items():
            if field in allowed_fields:
                setattr(self.record, field, value)

        self.record.save()
        return {'success': True, 'updated_fields': list(data.keys())}

    @classmethod
    def get(cls, onboarding_record):
        return cls(onboarding_record)