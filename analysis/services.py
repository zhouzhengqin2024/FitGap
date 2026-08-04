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
    'en': 'Review the fundamentals of this skill, complete a structured tutorial, and apply it in a small practical project.',
    'zh': '复习该技能的基础知识，完成一个结构化教程，并在一个小型实践项目中应用。',
}


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


def calculate_match_score(matched_skills, job_description_skills):
    """Calculate the percentage of recognised job description skills found in the CV."""
    unique_job_description_skills = {skill.lower() for skill in job_description_skills}

    if not unique_job_description_skills:
        return 0

    unique_matched_skills = {skill.lower() for skill in matched_skills}
    counted_matches = unique_matched_skills.intersection(unique_job_description_skills)
    score = (len(counted_matches) / len(unique_job_description_skills)) * 100

    return int(score + 0.5)


def generate_learning_recommendations(missing_skills, language):
    """Generate rule-based learning recommendations for missing skills."""
    if not missing_skills:
        return []

    selected_language = language if language in {'en', 'zh'} else 'en'
    catalogue_lookup = {
        skill.lower(): recommendations
        for skill, recommendations in RECOMMENDATION_CATALOGUE.items()
    }
    seen_skills = set()
    recommendations = []

    for skill in missing_skills:
        normalised_skill = skill.lower()

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
