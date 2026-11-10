"""
Screening and interview questions for recruitment (10 Nov 2026).

Screening scores the CV, so every screening question asks what the CV shows.
Interview questions are for the conversation. The Attendant and Cashier
screening sets had interview questions in them; this replaces them, adds the
Operator role's sets, and adds an "All roles" set that Octos uses for any role
without its own (Designer, for example).

Safe to run again: questions are updated in place by role, stage and number.
Pass marks and any role or stage not listed here are left alone.

    python manage.py seed_hr_questions
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role
from apps.hr.models import StageQuestionnaire as Q

S, I = Q.SCREENING, Q.INTERVIEW

# role name (None = all roles) -> stage -> five (question, guidance)
QUESTIONS = {
    'ATTENDANT': {
        S: [
            ('Does the CV show customer-facing experience (shop, front desk, reception or service work)?',
             '5 = a year or more serving customers directly. 1 = none at all. Informal work counts.'),
            ('Does the CV show job stability, with reasonable time in each role?',
             '5 = steady roles, gaps explained. 1 = many short stints with nothing said about them.'),
            ('Does the CV show the person using a computer or phone for work (records, POS, typing, email)?',
             'Attendants record every job in Octos. 5 = clearly comfortable. 1 = no sign of it.'),
            ('Is the CV clear, complete and free of careless mistakes?',
             'Attendants check customers\' files for errors, so their own CV is a fair test of care.'),
            ('Does the CV suggest a practical fit: lives within reach of Westland and can work Monday to Saturday?',
             'Score what the CV shows; confirm the rest at interview.'),
        ],
    },
    'CASHIER': {
        S: [
            ('Does the CV show cash handling or POS experience?',
             '5 = a year or more responsible for a till or cash. 1 = none.'),
            ('Does the CV show accuracy with numbers (bookkeeping, accounting, business studies, till work)?',
             'Education or work both count.'),
            ('Does the CV show job stability and a trustworthy work history?',
             '5 = steady roles with clear reasons for leaving. 1 = many short stints, unexplained.'),
            ('Does the CV give references or guarantors who can be contacted?',
             '5 = named, with contacts. 1 = none. The role may need two verifiable guarantors.'),
            ('Is the CV clear, complete and consistent (dates line up, no unexplained gaps)?',
             'A cashier\'s records must add up; so should their CV.'),
        ],
    },
    'OPERATOR': {
        S: [
            ('Does the CV show hands-on experience with the machine this vacancy is for (large format, DTF, embroidery or guillotine)?',
             '5 = a year or more on the same kind of machine. 3 = a related machine. 1 = none.'),
            ('Does the CV show the skills the role needs (media and colour, heat pressing, digitised designs, accurate cutting)?',
             'Compare with the vacancy\'s "What we\'re looking for" list.'),
            ('Does the CV show job stability in production or technical work?',
             '5 = steady roles. 1 = many short stints, unexplained.'),
            ('Does the CV show training, a certificate or an apprenticeship in printing or a related trade?',
             'Formal or on-the-job training both count.'),
            ('Does the CV show care and reliability (machine maintenance, quality checks, low-waste work)?',
             'Look for duties, not adjectives.'),
        ],
        I: [
            ('Walk me through setting up your machine for a new job, from the file to the first good print.',
             'Look for: checking the file, the material, a test print, then the run.'),
            ('A print comes out with a colour or alignment problem. How do you find and fix the cause?',
             'Look for: methodical checks (file, settings, material, machine), not guessing.'),
            ('How do you keep waste down when the material is expensive?',
             'Look for: test pieces, nesting, careful handling, checking before a full run.'),
            ('The machine breaks down mid-job with a customer waiting. What do you do?',
             'Look for: telling the coordinator at once, safe shutdown, honesty about the delay.'),
            ('Tell me about a job you are proud of. What made it hard?',
             'Look for: real detail, ownership of the result.'),
        ],
    },
    None: {
        S: [
            ('Does the CV show experience directly relevant to this role?',
             'Compare with the vacancy\'s duties. 5 = a strong, direct match. 1 = none.'),
            ('Does the CV show job stability, with reasonable time in each role?',
             '5 = steady roles, gaps explained. 1 = many short stints, unexplained.'),
            ('Does the CV show education, training or certificates relevant to the role?',
             'Formal or on-the-job both count.'),
            ('Does the CV show the key skills the vacancy lists (for designers: a portfolio of print work)?',
             'Check against "What we\'re looking for".'),
            ('Is the CV clear, complete and professionally presented?',
             'Dates line up, contacts work, no careless errors.'),
        ],
        I: [
            ('Walk me through your most relevant experience for this role.',
             'Look for: concrete examples, not general claims.'),
            ('Tell me about a mistake you made at work and what you did about it.',
             'Look for: honesty, ownership, what they changed afterwards.'),
            ('It is a busy day: customers are waiting and several jobs are due. How do you handle it?',
             'Look for: calm prioritising, asking for help, keeping customers informed.'),
            ('What would you need from us in your first month to do this job well?',
             'Look for: realistic expectations, eagerness to learn.'),
            ('Why do you want to work at Farhat Printing Press?',
             'Look for: knowing what we do, a reason beyond "I need a job".'),
        ],
    },
}


class Command(BaseCommand):
    help = 'Write recruitment screening and interview questions (safe to re-run).'

    @transaction.atomic
    def handle(self, *args, **options):
        for role_name, stages in QUESTIONS.items():
            role = None
            if role_name:
                role = Role.objects.filter(name=role_name).first()
                if not role:
                    self.stdout.write(self.style.WARNING(f'{role_name}: no such role, skipped'))
                    continue
            label = role_name or 'ALL ROLES'
            for stage, items in stages.items():
                for number, (text, guidance) in enumerate(items, start=1):
                    q, created = Q.objects.update_or_create(
                        role=role, stage=stage, question_number=number,
                        defaults={'question_text': text, 'guidance': guidance, 'is_active': True},
                    )
                    self.stdout.write(f'{label} {stage} {number}: {"added" if created else "updated"}')
        self.stdout.write(self.style.SUCCESS('Questions written.'))
