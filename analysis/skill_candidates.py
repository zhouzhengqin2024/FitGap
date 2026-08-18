import re

from .skill_catalogue import catalogue_lookup
from .skill_normalisation import normalise_candidate_label, normalise_skill_key


GENERIC_STOP_TERMS = {
    'applicant',
    'applicants',
    'business',
    'candidate',
    'candidates',
    'company',
    'experience',
    'job',
    'opportunities',
    'opportunity',
    'organisation',
    'organization',
    'position',
    'responsibilities',
    'responsibility',
    'role',
    'student',
    'team',
    'work',
}

LEADING_CONTEXT_WORDS = {
    'and',
    'experienced',
    'experience',
    'for',
    'in',
    'of',
    'or',
    'the',
    'to',
    'with',
}

GENERIC_ACRONYMS = {
    'API',
    'CV',
    'JD',
    'GC',
    'MS',
    'REST',
}

METHOD_HEAD_TERMS = (
    'analysis',
    'development',
    'media',
    'method',
    'methods',
    'modelling',
    'modeling',
    'process',
    'processes',
    'safety',
    'spectroscopy',
    'synthesis',
    'validation',
)


def split_candidate_fragments(text):
    """Split text into readable fragments for deterministic candidate evidence."""
    if not text:
        return []

    fragments = []
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue
        fragments.extend(
            fragment.strip()
            for fragment in re.split(r'(?<=[.!?。！？])\s+', stripped_line)
            if fragment.strip()
        )
    return fragments


def _is_generic_phrase(phrase):
    words = normalise_skill_key(phrase).split()
    return not words or all(word in GENERIC_STOP_TERMS for word in words)


def _clean_candidate_phrase(phrase):
    words = str(phrase or '').strip().split()
    while words and normalise_skill_key(words[0]) in LEADING_CONTEXT_WORDS:
        words.pop(0)
    return ' '.join(words)


def _catalogue_contains(candidate_key):
    return candidate_key in catalogue_lookup()


def _overlaps_catalogue(candidate_key):
    for known_key in catalogue_lookup():
        if known_key != candidate_key and f' {known_key} ' in f' {candidate_key} ':
            return True
    return False


def _add_candidate(candidates, seen, phrase):
    label = normalise_candidate_label(_clean_candidate_phrase(phrase))
    candidate_key = normalise_skill_key(label)

    if not label or candidate_key in seen or _catalogue_contains(candidate_key) or _overlaps_catalogue(candidate_key):
        return

    if _is_generic_phrase(label):
        return

    seen.add(candidate_key)
    candidates.append({
        'canonical': label,
        'aliases': [label],
        'category': 'Other / Domain Skill',
        'source': 'candidate',
    })


def discover_skill_candidates(text):
    """Conservatively discover uncatalogued skill-like phrases from plain text."""
    candidates = []
    seen = set()

    for fragment in split_candidate_fragments(text):
        for match in re.finditer(r'(?<![A-Za-z0-9])(?:[A-Z]{2,}(?:[-–—][A-Z]{2,})*)(?![A-Za-z0-9])', fragment):
            term = match.group(0)
            if term.upper() not in GENERIC_ACRONYMS:
                _add_candidate(candidates, seen, term)

        head_terms = '|'.join(METHOD_HEAD_TERMS)
        phrase_pattern = rf'\b[a-zA-Z][a-zA-Z-]*(?:\s+[a-zA-Z][a-zA-Z-]*){{1,4}}\s+(?:{head_terms})\b'
        for match in re.finditer(phrase_pattern, fragment, flags=re.IGNORECASE):
            phrase = match.group(0)
            words = normalise_skill_key(phrase).split()
            if len(words) >= 3:
                _add_candidate(candidates, seen, phrase)

    return candidates
