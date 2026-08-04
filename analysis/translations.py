SUPPORTED_LANGUAGES = {
    'en': 'English',
    'zh': '简体中文',
}

DEFAULT_LANGUAGE = 'en'

TRANSLATIONS = {
    'en': {
        'html_lang': 'en',
        'input_page_title': 'CV and Job Description Input',
        'input_intro': 'Paste the source text you want the prototype to use in a later analysis step.',
        'privacy_title': 'Privacy notice:',
        'privacy_notice': (
            'Do not include unnecessary personal identifiers such as full addresses, phone numbers, '
            'identification numbers, or other sensitive details.'
        ),
        'cv_label': 'CV Text',
        'cv_placeholder': 'Paste the CV text here.',
        'cv_required': 'Please paste the CV text before continuing.',
        'job_description_label': 'Job Description Text',
        'job_description_placeholder': 'Paste the job description text here.',
        'job_description_required': 'Please paste the job description text before continuing.',
        'output_language_label': 'Interface and Output Language',
        'language_english_choice': 'English interface and output',
        'language_chinese_choice': 'Simplified Chinese interface and output',
        'output_language_required': 'Please choose the interface and output language.',
        'submit_button': 'View Prototype Results',
        'results_page_title': 'Prototype Analysis Results',
        'output_language_selected': 'Output language selected:',
        'prototype_notice_title': 'Prototype output:',
        'prototype_notice': (
            'match score and learning recommendations are mock data and will later be replaced by '
            'rule-based analysis.'
        ),
        'extracted_skills': 'Extracted Skills',
        'real_extracted_notice': 'Real rule-based output from the submitted CV and job description text.',
        'skills_detected_cv': 'Skills detected in CV',
        'skills_detected_job_description': 'Skills detected in Job Description',
        'no_cv_skills': 'No recognised skills were found in the CV text.',
        'no_job_description_skills': 'No recognised skills were found in the job description text.',
        'match_score': 'Match Score',
        'matched_skills': 'Matched Skills',
        'matched_skills_notice': 'Real rule-based output: skills found in both the CV and job description.',
        'no_matched_skills': 'No matched skills were found.',
        'missing_skills': 'Missing Skills',
        'missing_skills_notice': 'Real rule-based output: job description skills not found in the CV.',
        'no_missing_skills': 'No missing skills were found.',
        'learning_recommendations': 'Learning Recommendations',
        'recommendation_django': 'Complete a beginner Django tutorial and build one small CRUD app.',
        'recommendation_rest_apis': 'Learn HTTP methods, status codes, and practise creating API endpoints.',
        'run_another_analysis': 'Run Another Analysis',
    },
    'zh': {
        'html_lang': 'zh-Hans',
        'input_page_title': '简历和职位描述输入',
        'input_intro': '粘贴原始文本，供原型在后续分析步骤中使用。',
        'privacy_title': '隐私提示：',
        'privacy_notice': '请不要包含不必要的个人标识信息，例如完整地址、电话号码、身份证件号码或其他敏感信息。',
        'cv_label': '简历文本',
        'cv_placeholder': '请在此粘贴简历文本。',
        'cv_required': '请先粘贴简历文本再继续。',
        'job_description_label': '职位描述文本',
        'job_description_placeholder': '请在此粘贴职位描述文本。',
        'job_description_required': '请先粘贴职位描述文本再继续。',
        'output_language_label': '界面和输出语言',
        'language_english_choice': '英文界面和输出',
        'language_chinese_choice': '简体中文界面和输出',
        'output_language_required': '请选择界面和输出语言。',
        'submit_button': '查看原型结果',
        'results_page_title': '原型分析结果',
        'output_language_selected': '已选择的输出语言：',
        'prototype_notice_title': '原型输出：',
        'prototype_notice': '匹配分数和学习建议目前是模拟数据，之后将由规则分析替换。',
        'extracted_skills': '提取的技能',
        'real_extracted_notice': '来自已提交简历和职位描述文本的真实规则输出。',
        'skills_detected_cv': '简历中检测到的技能',
        'skills_detected_job_description': '职位描述中检测到的技能',
        'no_cv_skills': '简历文本中未找到可识别的技能。',
        'no_job_description_skills': '职位描述文本中未找到可识别的技能。',
        'match_score': '匹配分数',
        'matched_skills': '匹配技能',
        'matched_skills_notice': '真实规则输出：同时出现在简历和职位描述中的技能。',
        'no_matched_skills': '未找到匹配技能。',
        'missing_skills': '缺失技能',
        'missing_skills_notice': '真实规则输出：职位描述中出现但简历中未出现的技能。',
        'no_missing_skills': '未找到缺失技能。',
        'learning_recommendations': '学习建议',
        'recommendation_django': '完成一个 Django 入门教程，并构建一个小型增删改查应用。',
        'recommendation_rest_apis': '学习 HTTP 方法和状态码，并练习创建 API 端点。',
        'run_another_analysis': '再次分析',
    },
}


def normalise_language(language):
    """Return a supported language code, falling back to English for unknown values."""
    if language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def get_translations(language):
    """Return interface text for the selected supported language."""
    return TRANSLATIONS[normalise_language(language)]
