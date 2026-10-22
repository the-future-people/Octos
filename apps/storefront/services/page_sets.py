"""
Which pages of a file a line prints.

A customer can print part of a file, or different parts differently:
page 1 in colour five times, the rest in black and white once. Each of
those is a set, and each set is its own line, carrying the pages it
prints as `specifications.page_selection` ("1, 5, 8–12") and its count
as `pages`.

The selection is chosen in the app, so it is checked here against the
file itself: a customer cannot choose two pages and have all twelve
printed, or choose page 14 of a twelve-page file.
"""

import re


class SelectionRefused(Exception):
    """The selection does not fit the file; the message says why."""


def parse_selection(text, page_count):
    """
    "1, 5, 8-12" (or with en dashes) as a sorted list of distinct pages,
    each within the file. "all" means every page.
    """
    total = max(1, int(page_count or 1))
    raw = str(text or '').strip().lower()
    if not raw or raw == 'all':
        return list(range(1, total + 1))

    pages = set()
    for part in re.split(r'\s*,\s*', raw.replace('–', '-').replace('—', '-')):
        if not part:
            continue
        match = re.fullmatch(r'(\d+)\s*(?:-\s*(\d+))?', part)
        if not match:
            raise SelectionRefused(f'“{part}” is not a page or a range of pages.')
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < 1:
            raise SelectionRefused('Pages start at 1.')
        if start > end:
            start, end = end, start
        if end > total:
            raise SelectionRefused(
                f'Page {end}? This file has {total} page{"s" if total != 1 else ""}.'
            )
        pages.update(range(start, end + 1))
    if not pages:
        raise SelectionRefused('Choose at least one page.')
    return sorted(pages)


def format_selection(pages):
    """[1, 2, 3, 5, 8, 9] as "1–3, 5, 8–9": how it reads on the order and the floor."""
    pages = sorted(set(pages))
    if not pages:
        return ''
    runs, start, prev = [], pages[0], pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append((start, prev))
        start = prev = p
    runs.append((start, prev))
    return ', '.join(str(a) if a == b else f'{a}–{b}' for a, b in runs)