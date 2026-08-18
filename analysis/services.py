import re

from .skill_candidates import discover_skill_candidates
from .skill_catalogue import (
    SKILL_CATALOGUE,
    SKILL_CATALOGUE_ENTRIES,
    get_aliases_for_skill,
    get_category_for_skill,
    get_source_for_skill,
)
from .skill_normalisation import normalise_skill_key

RECOMMENDATION_CATALOGUE = {
    'Python': {
        'en': 'Review Python fundamentals, practise data structures and functions, and complete one small programming project.',
        'zh': '复习 Python 基础、练习数据结构与函数，并完成一个小型编程项目。',
    },
    'SQL': {
        'en': 'Learn SELECT, JOIN, GROUP BY, and subqueries, then practise with a small relational database.',
        'zh': '学习 SELECT、JOIN、GROUP BY 和子查询，并使用一个小型关系型数据库进行练习。',
    },
    'Git': {
        'en': 'Practise creating branches, committing changes, resolving merge conflicts, and using GitHub or GitLab.',
        'zh': '练习创建分支、提交修改、解决合并冲突，并熟悉 GitHub 或 GitLab。',
    },
    'Django': {
        'en': 'Complete a beginner Django tutorial and build a small CRUD web application.',
        'zh': '完成 Django 入门教程，并构建一个小型 CRUD Web 应用。',
    },
    'REST APIs': {
        'en': 'Learn HTTP methods, status codes, JSON, and build and test a simple REST endpoint.',
        'zh': '学习 HTTP 方法、状态码和 JSON，并构建和测试一个简单的 REST 接口。',
    },
    'JavaScript': {
        'en': 'Review JavaScript fundamentals, DOM manipulation, events, and build one small interactive webpage.',
        'zh': '复习 JavaScript 基础、DOM 操作和事件，并构建一个小型交互网页。',
    },
    'HTML': {
        'en': 'Learn semantic HTML structure and build an accessible multi-section webpage.',
        'zh': '学习语义化 HTML 结构，并构建一个具有可访问性的多区域网页。',
    },
    'CSS': {
        'en': 'Practise layout, responsive design, Flexbox, and Grid by styling a complete webpage.',
        'zh': '通过设计一个完整网页，练习布局、响应式设计、Flexbox 和 Grid。',
    },
    'Bootstrap': {
        'en': 'Learn the Bootstrap grid, components, and utilities, then rebuild a responsive page using Bootstrap.',
        'zh': '学习 Bootstrap 栅格、组件和工具类，并使用 Bootstrap 重构一个响应式页面。',
    },
    'Machine Learning': {
        'en': 'Learn the basic supervised-learning workflow, train one simple model, and evaluate it using appropriate metrics.',
        'zh': '学习基础监督学习流程，训练一个简单模型，并使用合适的指标进行评估。',
    },
    'Artificial Intelligence': {
        'en': 'Review core AI concepts, compare rule-based and machine-learning approaches, and implement one small AI example.',
        'zh': '复习人工智能核心概念，对比规则式方法与机器学习方法，并实现一个小型 AI 示例。',
    },
}

GENERIC_RECOMMENDATION = {
    'en': (
        'Review the role requirements for this skill and identify practical training, coursework, '
        'or supervised experience that can demonstrate it.'
    ),
    'zh': '复查该技能对应的岗位要求，并寻找能证明该技能的实践训练、课程作业或受指导经验。',
}

MAX_EVIDENCE_EXCERPTS = 2

CLASSIFICATION_EXPLANATIONS = {
    'en': {
        'matched': '{skill} was classified as matched because a configured term or alias was found in both the CV and the job description.',
        'missing': (
            '{skill} was recognised in the job description, but no configured canonical term or alias for '
            '{skill} was found in the CV.'
        ),
    },
    'zh': {
        'matched': '{skill} 被归类为匹配技能，因为简历和职位描述中都找到了已配置的术语或别名。',
        'missing': '{skill} 在职位描述中被识别出，但简历中未找到 {skill} 的已配置规范术语或别名。',
    },
}


def _build_alias_pattern(alias):
    escaped_alias = re.escape(alias)
    flexible_spaces = escaped_alias.replace(r'\ ', r'\s+')
    flexible_hyphens = flexible_spaces.replace(r'\-', r'[-\u2010-\u2015\s]+')
    flexible_hyphens = flexible_hyphens.replace('–', r'[-\u2010-\u2015\s]+')
    return rf'(?<![A-Za-z0-9]){flexible_hyphens}(?![A-Za-z0-9])'


def _get_aliases_for_skill(skill):
    return get_aliases_for_skill(skill)


def _normalise_language(language):
    return language if language in {'en', 'zh'} else 'en'


def _split_evidence_fragments(text):
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


def extract_skills(text):
    """Extract recognised skills from plain text using deterministic catalogue and candidate matching."""
    if not text:
        return []

    extracted_skills = []
    seen_skills = set()

    for entry in SKILL_CATALOGUE_ENTRIES:
        canonical_skill = entry['canonical']
        for alias in entry['aliases']:
            # The lookarounds avoid matching aliases inside longer words.
            if re.search(_build_alias_pattern(alias), text, flags=re.IGNORECASE):
                seen_skills.add(normalise_skill_key(canonical_skill))
                extracted_skills.append(canonical_skill)
                break

    for candidate in discover_skill_candidates(text):
        normalised_candidate = normalise_skill_key(candidate['canonical'])
        if normalised_candidate in seen_skills:
            continue
        seen_skills.add(normalised_candidate)
        extracted_skills.append(candidate['canonical'])

    return extracted_skills


def extract_skill_evidence(text, skill, max_excerpts=MAX_EVIDENCE_EXCERPTS):
    """Return original text excerpts that support a recognised skill match."""
    return [
        occurrence['excerpt']
        for occurrence in extract_skill_evidence_occurrences(text, skill, max_excerpts)
    ]


def _build_highlight_parts(excerpt, start, end):
    return [
        {'text': excerpt[:start], 'is_match': False},
        {'text': excerpt[start:end], 'is_match': True},
        {'text': excerpt[end:], 'is_match': False},
    ]


def extract_skill_evidence_occurrences(text, skill, max_excerpts=MAX_EVIDENCE_EXCERPTS):
    """Return structured evidence occurrences for a recognised skill match."""
    occurrences = []
    seen_excerpts = set()

    for fragment in _split_evidence_fragments(text):
        for alias in _get_aliases_for_skill(skill):
            match = re.search(_build_alias_pattern(alias), fragment, flags=re.IGNORECASE)

            if match:
                normalised_fragment = re.sub(r'\s+', ' ', fragment).lower()

                if normalised_fragment not in seen_excerpts:
                    seen_excerpts.add(normalised_fragment)
                    matched_term = match.group(0)
                    occurrences.append({
                        'excerpt': fragment,
                        'matched_term': matched_term,
                        'is_alias': normalise_skill_key(alias) != normalise_skill_key(skill),
                        'highlight_parts': _build_highlight_parts(fragment, match.start(), match.end()),
                    })

                break

        if len(occurrences) >= max_excerpts:
            break

    return occurrences


def build_skill_evidence_details(matched_skills, missing_skills, cv_text, job_description_text, language='en'):
    """Build structured CV and job description evidence for matched and missing skills."""
    selected_language = _normalise_language(language)
    matched_skill_details = [
        {
            'skill': skill,
            'status': 'matched',
            'category': get_category_for_skill(skill),
            'source': get_source_for_skill(skill),
            'cv_evidence': extract_skill_evidence_occurrences(cv_text, skill),
            'jd_evidence': extract_skill_evidence_occurrences(job_description_text, skill),
            'explanation': CLASSIFICATION_EXPLANATIONS[selected_language]['matched'].format(skill=skill),
        }
        for skill in matched_skills
    ]
    missing_skill_details = [
        {
            'skill': skill,
            'status': 'missing',
            'category': get_category_for_skill(skill),
            'source': get_source_for_skill(skill),
            'cv_evidence': [],
            'jd_evidence': extract_skill_evidence_occurrences(job_description_text, skill),
            'explanation': CLASSIFICATION_EXPLANATIONS[selected_language]['missing'].format(skill=skill),
        }
        for skill in missing_skills
    ]

    return {
        'matched_skill_details': matched_skill_details,
        'missing_skill_details': missing_skill_details,
    }


def compare_skills(cv_skills, job_description_skills):
    """Compare extracted CV and job description skills using exact case-insensitive matching."""
    if not job_description_skills:
        return {
            'matched_skills': [],
            'missing_skills': [],
        }

    cv_skill_lookup = {normalise_skill_key(skill) for skill in cv_skills}
    seen_job_description_skills = set()
    matched_skills = []
    missing_skills = []

    for skill in job_description_skills:
        normalised_skill = normalise_skill_key(skill)

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


def calculate_match_score(matched_skills, job_description_skills):
    """Calculate the percentage of recognised job description skills found in the CV."""
    unique_job_description_skills = {normalise_skill_key(skill) for skill in job_description_skills}

    if not unique_job_description_skills:
        return 0

    unique_matched_skills = {normalise_skill_key(skill) for skill in matched_skills}
    counted_matches = unique_matched_skills.intersection(unique_job_description_skills)
    score = (len(counted_matches) / len(unique_job_description_skills)) * 100

    return int(score + 0.5)


def generate_learning_recommendations(missing_skills, language):
    """Generate rule-based learning recommendations for missing skills."""
    if not missing_skills:
        return []

    selected_language = language if language in {'en', 'zh'} else 'en'
    catalogue_lookup = {
        normalise_skill_key(skill): recommendations
        for skill, recommendations in RECOMMENDATION_CATALOGUE.items()
    }
    seen_skills = set()
    recommendations = []

    for skill in missing_skills:
        normalised_skill = normalise_skill_key(skill)

        if normalised_skill in seen_skills:
            continue

        seen_skills.add(normalised_skill)
        recommendation_text = catalogue_lookup.get(
            normalised_skill,
            GENERIC_RECOMMENDATION,
        )[selected_language]
        recommendations.append({
            'skill': skill,
            'recommendation': recommendation_text,
        })

    return recommendations
