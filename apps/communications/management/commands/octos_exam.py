"""
python manage.py octos_exam [--case NAME] [--show]

Replays the exam conversations through Octos against the real catalogue,
rolled back (nothing saved, sent or announced), and prints a score.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.communications.assistant.exam import CASES, run_case


class Command(BaseCommand):
    help = "Replay the exam conversations through Octos and grade every reply."

    def add_arguments(self, parser):
        parser.add_argument('--case', help='Only cases whose name contains this.')
        parser.add_argument('--show', action='store_true', help="Show every reply, not only the failures'.")

    def handle(self, *args, **opts):
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError('ANTHROPIC_API_KEY is not set.')
        cases = [c for c in CASES if not opts['case'] or opts['case'] in c['name']]
        if not cases:
            raise CommandError(f"No case matches {opts['case']!r}.")

        self.stdout.write(f'Octos exam: {len(cases)} cases, model {settings.OCTOS_ASSISTANT_MODEL}\n')
        passed, tokens_in, tokens_out = 0, 0, 0
        for case in cases:
            try:
                r = run_case(case)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'ERROR {case["name"]}: {exc!r}'))
                continue
            passed += r['passed']
            tokens_in += r['tokens'][0]
            tokens_out += r['tokens'][1]
            mark = self.style.SUCCESS('PASS') if r['passed'] else self.style.ERROR('FAIL')
            self.stdout.write(f"{mark} {r['name']}  [{', '.join(r['tools']) or 'no tools'}]")
            for why in r['fails']:
                self.stdout.write(f'     - {why}')
            if opts['show'] or not r['passed']:
                self.stdout.write(f"     reply: {r['reply']}")
                if r['handover']:
                    self.stdout.write(f"     handover: {r['handover']}")

        self.stdout.write(f'\n{passed}/{len(cases)} passed. Tokens: {tokens_in} in, {tokens_out} out.')