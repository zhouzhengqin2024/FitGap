import re


SKILL_CATALOGUE = [
    ('Python', ['python']),
    ('SQL', ['sql', 'mysql', 'postgresql', 'postgres']),
    ('Git', ['git', 'github', 'gitlab']),
    ('Django', ['django']),
    ('REST APIs', ['rest api', 'rest APIs', 'restful api', 'restful APIs']),
    ('JavaScript', ['javascript', 'js']),
    ('HTML', ['html', 'html5']),
    ('CSS', ['css', 'css3']),
    ('Bootstrap', ['bootstrap']),
    ('Machine Learning', ['machine learning', 'ml']),
    ('Artificial Intelligence', ['artificial intelligence', 'ai']),
]


def _build_alias_pattern(alias):
    escaped_alias = re.escape(alias)
    flexible_spaces = escaped_alias.replace(r'\ ', r'\s+')
    return rf'(?<![A-Za-z0-9]){flexible_spaces}(?![A-Za-z0-9])'


def extract_skills(text):
    """Extract recognised skills from plain text using deterministic catalogue matching."""
    if not text:
        return []

    extracted_skills = []

    for canonical_skill, aliases in SKILL_CATALOGUE:
        for alias in aliases:
            # The lookarounds avoid matching aliases inside longer words.
            if re.search(_build_alias_pattern(alias), text, flags=re.IGNORECASE):
                extracted_skills.append(canonical_skill)
                break

    return extracted_skills


def compare_skills(cv_skills, job_description_skills):
    """Compare extracted CV and job description skills using exact case-insensitive matching."""
    if not cv_skills or not job_description_skills:
        return {
            'matched_skills': [],
            'missing_skills': [],
        }

    cv_skill_lookup = {skill.lower() for skill in cv_skills}
    seen_job_description_skills = set()
    matched_skills = []
    missing_skills = []

    for skill in job_description_skills:
        normalised_skill = skill.lower()

        # Keep the first JD occurrence only so each result skill appears once.
        if normalised_skill in seen_job_description_skills:
            continue

        seen_job_description_skills.add(normalised_skill)

        if normalised_skill in cv_skill_lookup:
            matched_skills.append(skill)
        else:
            missing_skills.append(skill)

    return {
        'matched_skills': matched_skills,
        'missing_skills': missing_skills,
    }
