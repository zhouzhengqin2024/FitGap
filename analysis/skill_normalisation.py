import re


def normalise_skill_key(value):
    """Return a stable comparison key for catalogue skills, aliases, and candidates."""
    if value is None:
        return ''

    text = str(value).strip().lower()
    text = re.sub(r'[\u2010-\u2015]', '-', text)
    text = text.replace('&', ' and ')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalise_candidate_label(value):
    """Return a readable canonical label for a dynamically discovered skill phrase."""
    text = re.sub(r'\s+', ' ', str(value or '').strip(' .,:;()[]{}')).strip()
    if not text:
        return ''

    if re.fullmatch(r'[A-Z0-9]+(?:[-\s][A-Z0-9]+)*', text):
        return re.sub(r'\s+', '-', text.upper())

    return text[:1].upper() + text[1:]
