from apps.accounts.models import Role
from apps.hr.models import StageQuestionnaire

# Clear existing questionnaires
StageQuestionnaire.objects.all().delete()

questions = {
    'ATTENDANT': {
        'SCREENING': {
            'threshold': 12,
            'questions': [
                ('Can you describe any experience you have in a customer-facing role?',
                 'Look for: patience, communication, service orientation. Even informal experience counts.'),
                ('How do you handle a difficult or impatient customer?',
                 'Look for: calmness, empathy, de-escalation skills. Red flag: blaming the customer.'),
                ('Are you comfortable operating basic office or printing equipment?',
                 'Look for: willingness to learn, any prior exposure. Not expected to be expert.'),
                ('How do you prioritise when you have multiple tasks at once?',
                 'Look for: structured thinking, not panicking, asking for help when needed.'),
                ('Are you available for the full Monday to Saturday shift schedule?',
                 'Straightforward. Must confirm availability. Note any constraints.'),
            ],
        },
        'INTERVIEW': {
            'threshold': 15,
            'questions': [
                ('Walk me through how you would handle a job from the moment a customer walks in to completion.',
                 'Look for: process awareness, customer focus, attention to detail.'),
                ('A customer is unhappy with their print quality. What do you do?',
                 'Look for: ownership, calm resolution, knowing when to escalate to BM.'),
                ('Describe a time you worked under significant pressure.',
                 'Look for: resilience, composure, practical problem-solving.'),
                ('How do you ensure accuracy when doing repetitive tasks?',
                 'Look for: systems thinking, self-checking habits, care for quality.'),
                ('Why do you want to work at Farhat Printing Press specifically?',
                 'Look for: genuine interest, awareness of the business, long-term thinking.'),
            ],
        },
    },
    'CASHIER': {
        'SCREENING': {
            'threshold': 18,
            'questions': [
                ('Do you have experience handling cash or operating a POS system?',
                 'Look for: direct cash handling experience. This is critical — low score if none.'),
                ('How do you ensure accuracy when counting large sums of money?',
                 'Look for: double-counting habits, concentration, systematic approach.'),
                ('How would you handle a discrepancy in your till at end of day?',
                 'Look for: immediate reporting, no concealment instinct, transparency.'),
                ('Are you comfortable being fully accountable for cash under your custody?',
                 'Look for: confidence, seriousness about responsibility. Hesitation is a red flag.'),
                ('Can you provide two verifiable guarantors if required for this role?',
                 'Must answer yes. If no, cannot proceed. This is non-negotiable for Cashier.'),
            ],
        },
        'INTERVIEW': {
            'threshold': 20,
            'questions': [
                ('Describe your experience with cash handling and end-of-day reconciliation.',
                 'Look for: specifics, familiarity with counting procedures, prior accountability.'),
                ('A customer insists they gave you a larger note than what you recorded. How do you handle it?',
                 'Look for: calm, process-driven response. Should not accuse or capitulate without process.'),
                ('What would you do if you noticed a colleague behaving suspiciously around the cash drawer?',
                 'Look for: immediate reporting to BM. Zero tolerance for covering up.'),
                ('Walk me through how you would close out your till at end of day.',
                 'Look for: counting, recording, reconciling with receipts, reporting variance.'),
                ('Why should Farhat Printing Press trust you with full financial responsibility?',
                 'Look for: integrity, track record, seriousness. Vague answers score low.'),
            ],
        },
    },
    'BRANCH_MANAGER': {
        'SCREENING': {
            'threshold': 20,
            'questions': [
                ('Do you have experience managing a team of three or more people?',
                 'Look for: direct management experience, team size, duration.'),
                ('How do you handle underperformance in a direct report?',
                 'Look for: structured feedback, documentation, fairness, decisiveness.'),
                ('Describe your approach to daily operations management.',
                 'Look for: planning, delegation, monitoring, end-of-day review habits.'),
                ('Have you been responsible for financial reporting or cash reconciliation?',
                 'Look for: familiarity with financial accountability. Critical for BM role.'),
                ('Are you comfortable being the final decision-maker for your branch?',
                 'Look for: confidence, ownership mentality. Indecisiveness is a red flag.'),
            ],
        },
        'INTERVIEW': {
            'threshold': 22,
            'questions': [
                ('A cashier\'s till is short at end of day and they cannot explain why. Walk me through your response.',
                 'Look for: immediate escalation protocol, documentation, no cover-up, calm investigation.'),
                ('Two of your attendants have a conflict that is affecting customer service. How do you resolve it?',
                 'Look for: private mediation, root cause focus, firmness, fairness.'),
                ('Branch revenue drops 30% over two consecutive weeks. What steps do you take?',
                 'Look for: data analysis, staff review, service audit, escalation to Belt Manager.'),
                ('How would you onboard and train a new attendant in their first week?',
                 'Look for: structured plan, shadowing, feedback loops, patience.'),
                ('What does operational excellence look like to you in a printing press environment?',
                 'Look for: zero errors on jobs, happy customers, clean EOD, motivated staff, no waste.'),
            ],
        },
    },
}

created = 0
for role_name, stages in questions.items():
    try:
        role = Role.objects.get(name=role_name)
    except Role.DoesNotExist:
        print(f'Role not found: {role_name} — skipping')
        continue

    for stage_key, data in stages.items():
        threshold = data['threshold']
        for i, (question_text, guidance) in enumerate(data['questions'], start=1):
            StageQuestionnaire.objects.create(
                role=role,
                stage=stage_key,
                question_number=i,
                question_text=question_text,
                guidance=guidance,
                pass_threshold=threshold,
                is_active=True,
            )
            created += 1

print(f'Seeded {created} questions across {len(questions)} roles.')
StageQuestionnaire.objects.values('role__name', 'stage').annotate(
    count=__import__('django.db.models', fromlist=['Count']).Count('id')
).order_by('role__name', 'stage')

from django.db.models import Count
summary = StageQuestionnaire.objects.values('role__name', 'stage').annotate(count=Count('id')).order_by('role__name', 'stage')
for row in summary:
    print(f"  {row['role__name']} | {row['stage']} | {row['count']} questions")