from decimal import Decimal
from django.utils import timezone
from apps.organization.models import Branch


# System default — can be moved to a SystemSettings model later
SUPERHEAVY_THRESHOLD_DAYS = 7
CAPACITY_THRESHOLD = 85  # percentage


class RoutingEngine:
    """
    Evaluates candidate branches for a job and returns a ranked list
    of routing suggestions.

    Routing rings:
      Ring 1 — Same branch (handled before engine is called)
      Ring 2 — Same region branches (always evaluated first)
      Ring 3 — Same belt branches (superheavy jobs only)
      Ring 4 — Cross belt branches (superheavy jobs only)
      HQ     — Always considered as fallback, gets +15 bonus score

    Scoring (per candidate branch):
      Capacity score   40%  — headroom available
      Queue depth      30%  — fewer jobs = higher score
      Service match    20%  — exact service available
      Proximity ring   10%  — closer ring = higher score
      HQ bonus        +15   — flat bonus for HQ
    """

    RING_PROXIMITY_SCORES = {
        2: 10,  # same region
        3: 6,   # same belt
        4: 3,   # cross belt
    }

    def __init__(self, job, service):
        self.job = job
        self.service = service
        self.originating_branch = job.branch
        self.is_superheavy = self._check_superheavy()

    def _check_superheavy(self):
        """
        A job is superheavy if its estimated time exceeds the threshold.
        """
        if not self.job.estimated_time:
            return False
        days = self.job.estimated_time / (60 * 24)
        return days >= SUPERHEAVY_THRESHOLD_DAYS

    def _get_candidate_branches(self):
        """
        Build the pool of candidate branches based on job weight.
        Superheavy jobs can go cross-belt.
        Normal jobs stay within region or go to HQ.
        """
        origin = self.originating_branch
        candidates = []

        # Always get same-region branches (Ring 2)
        region_branches = Branch.objects.filter(
            region=origin.region,
            is_active=True
        ).exclude(id=origin.id)

        for branch in region_branches:
            candidates.append((branch, 2))

        if self.is_superheavy:
            # Ring 3 — same belt, different region
            belt_branches = Branch.objects.filter(
                region__belt=origin.region.belt,
                is_active=True
            ).exclude(region=origin.region)

            for branch in belt_branches:
                candidates.append((branch, 3))

            # Ring 4 — cross belt
            cross_belt = Branch.objects.filter(
                is_active=True
            ).exclude(region__belt=origin.region.belt)

            for branch in cross_belt:
                candidates.append((branch, 4))

        # Always include HQ if not already in list
        try:
            hq = Branch.objects.get(is_headquarters=True, is_active=True)
            if hq.id != origin.id:
                # HQ gets ring 2 score to keep it competitive
                if not any(b.id == hq.id for b, _ in candidates):
                    candidates.append((hq, 2))
        except Branch.DoesNotExist:
            pass

        return candidates

    def _score_branch(self, branch, ring, service):
        """
        Score a candidate branch out of 100 + HQ bonus.
        """
        score = 0

        # 1. Capacity score (40 points)
        load = branch.load_percentage
        if load < CAPACITY_THRESHOLD:
            capacity_score = ((CAPACITY_THRESHOLD - load) / CAPACITY_THRESHOLD) * 40
        else:
            capacity_score = 0
        score += capacity_score

        # 2. Queue depth score (30 points)
        # Fewer active jobs = higher score
        active_jobs = branch.jobs.filter(
            status__in=['CONFIRMED', 'QUEUED', 'IN_PROGRESS']
        ).count()
        queue_score = max(0, 30 - (active_jobs * 2))
        score += queue_score

        # 3. Service match score (20 points)
        service_available = branch.services.filter(
            id=service.id,
            is_active=True
        ).exists() if hasattr(branch, 'services') else False
        score += 20 if service_available else 0

        # 4. Proximity ring score (10 points)
        score += self.RING_PROXIMITY_SCORES.get(ring, 0)

        # 5. HQ bonus (+15 flat)
        if branch.is_headquarters:
            score += 15

        return round(score, 2)

    def evaluate(self):
        """
        Main entry point. Returns a ranked list of routing suggestions.

        Returns:
            list of dicts with branch, score, ring, is_hq, estimated_wait
        """
        candidates = self._get_candidate_branches()

        if not candidates:
            return {
                'success': False,
                'error': 'No candidate branches found for routing.',
                'suggestions': []
            }

        results = []
        for branch, ring in candidates:
            score = self._score_branch(branch, ring, self.service)

            # Only suggest branches that can actually handle the job
            if score > 0:
                results.append({
                    'branch': branch,
                    'branch_id': branch.id,
                    'branch_name': branch.name,
                    'branch_code': branch.code,
                    'score': score,
                    'ring': ring,
                    'is_hq': branch.is_headquarters,
                    'load_percentage': branch.load_percentage,
                    'is_superheavy_route': ring in [3, 4],
                })

        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)

        return {
            'success': True,
            'is_superheavy': self.is_superheavy,
            'originating_branch': self.originating_branch.name,
            'suggestions': results,
            'top_suggestion': results[0] if results else None
        }

    @classmethod
    def suggest(cls, job, service):
        """
        Convenience method for quick routing suggestion.
        """
        engine = cls(job, service)
        return engine.evaluate()