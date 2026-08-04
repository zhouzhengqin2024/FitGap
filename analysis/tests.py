from django.test import SimpleTestCase

from .services import compare_skills, extract_skills


class ExtractSkillsTests(SimpleTestCase):
    def test_matches_case_insensitively(self):
        self.assertEqual(extract_skills('Built tools with PYTHON and django.'), ['Python', 'Django'])

    def test_matches_aliases(self):
        text = 'Used PostgreSQL, GitHub, RESTful APIs, JS, HTML5, CSS3, ML, and AI.'

        self.assertEqual(
            extract_skills(text),
            [
                'SQL',
                'Git',
                'REST APIs',
                'JavaScript',
                'HTML',
                'CSS',
                'Machine Learning',
                'Artificial Intelligence',
            ],
        )

    def test_removes_duplicates(self):
        self.assertEqual(extract_skills('Python python PYTHON'), ['Python'])

    def test_preserves_catalogue_order(self):
        self.assertEqual(extract_skills('Bootstrap, CSS, HTML, JavaScript, Django, Git, SQL, Python'), [
            'Python',
            'SQL',
            'Git',
            'Django',
            'JavaScript',
            'HTML',
            'CSS',
            'Bootstrap',
        ])

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(extract_skills(''), [])
        self.assertEqual(extract_skills(None), [])

    def test_text_with_no_recognised_skills_returns_empty_list(self):
        self.assertEqual(extract_skills('Excellent communication and stakeholder management.'), [])

    def test_avoids_partial_word_matches(self):
        text = 'The candidate used githubactions, mysqlite, postgraduate research, and a majestic style.'

        self.assertEqual(extract_skills(text), [])

    def test_realistic_cv_and_job_description_examples(self):
        cv_text = 'Developer with Python, SQL, GitLab, HTML5, CSS3, and Bootstrap experience.'
        job_description_text = 'The role requires Django, REST API design, PostgreSQL, Git, and JavaScript.'

        self.assertEqual(
            extract_skills(cv_text),
            ['Python', 'SQL', 'Git', 'HTML', 'CSS', 'Bootstrap'],
        )
        self.assertEqual(
            extract_skills(job_description_text),
            ['SQL', 'Git', 'Django', 'REST APIs', 'JavaScript'],
        )


class CompareSkillsTests(SimpleTestCase):
    def test_normal_matched_and_missing_skill_comparison(self):
        self.assertEqual(
            compare_skills(['Python', 'SQL'], ['Python', 'Django', 'SQL']),
            {
                'matched_skills': ['Python', 'SQL'],
                'missing_skills': ['Django'],
            },
        )

    def test_no_matched_skills(self):
        self.assertEqual(
            compare_skills(['Python'], ['Django', 'REST APIs']),
            {
                'matched_skills': [],
                'missing_skills': ['Django', 'REST APIs'],
            },
        )

    def test_no_missing_skills(self):
        self.assertEqual(
            compare_skills(['Python', 'SQL', 'Git'], ['Python', 'Git']),
            {
                'matched_skills': ['Python', 'Git'],
                'missing_skills': [],
            },
        )

    def test_empty_cv_skills(self):
        self.assertEqual(
            compare_skills([], ['Python', 'SQL']),
            {
                'matched_skills': [],
                'missing_skills': [],
            },
        )

    def test_empty_job_description_skills(self):
        self.assertEqual(
            compare_skills(['Python', 'SQL'], []),
            {
                'matched_skills': [],
                'missing_skills': [],
            },
        )

    def test_duplicate_input_skills_are_returned_once(self):
        self.assertEqual(
            compare_skills(['Python', 'python'], ['Python', 'Python', 'Django', 'django']),
            {
                'matched_skills': ['Python'],
                'missing_skills': ['Django'],
            },
        )

    def test_case_insensitive_comparison(self):
        self.assertEqual(
            compare_skills(['python', 'sql'], ['Python', 'SQL', 'Git']),
            {
                'matched_skills': ['Python', 'SQL'],
                'missing_skills': ['Git'],
            },
        )

    def test_preserves_job_description_skill_order(self):
        self.assertEqual(
            compare_skills(['SQL', 'Git'], ['Django', 'Git', 'Python', 'SQL']),
            {
                'matched_skills': ['Git', 'SQL'],
                'missing_skills': ['Django', 'Python'],
            },
        )

    def test_integration_with_realistic_extracted_skill_lists(self):
        cv_skills = extract_skills('Python developer with SQL, GitLab, HTML5, CSS3, and Bootstrap.')
        job_description_skills = extract_skills('Needs Django, REST APIs, PostgreSQL, Git, and JavaScript.')

        self.assertEqual(
            compare_skills(cv_skills, job_description_skills),
            {
                'matched_skills': ['SQL', 'Git'],
                'missing_skills': ['Django', 'REST APIs', 'JavaScript'],
            },
        )


class InterfaceLanguageTests(SimpleTestCase):
    def test_english_input_page(self):
        response = self.client.get('/?lang=en')

        self.assertContains(response, 'CV and Job Description Input')
        self.assertContains(response, 'Interface and Output Language')
        self.assertContains(response, 'English interface and output')
        self.assertContains(response, 'href="/?lang=zh"')

    def test_chinese_input_page(self):
        response = self.client.get('/?lang=zh')

        self.assertContains(response, '简历和职位描述输入')
        self.assertContains(response, '界面和输出语言')
        self.assertContains(response, '简体中文界面和输出')
        self.assertContains(response, 'href="/?lang=en"')

    def test_english_results_page(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })

        self.assertContains(response, 'Prototype Analysis Results')
        self.assertContains(response, 'Extracted Skills')
        self.assertContains(response, 'Matched Skills')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')

    def test_chinese_results_page(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'zh',
        })

        self.assertContains(response, '原型分析结果')
        self.assertContains(response, '提取的技能')
        self.assertContains(response, '匹配技能')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')
        self.assertContains(response, '完成一个 Django 入门教程')

    def test_language_preservation_after_post(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'Python Django',
            'output_language': 'zh',
        })

        self.assertContains(response, '原型分析结果')
        self.assertContains(response, 'href="/?lang=zh"')

    def test_chinese_required_field_validation_messages(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': '',
            'job_description_text': '',
            'output_language': 'zh',
        })

        self.assertContains(response, '请先粘贴简历文本再继续。')
        self.assertContains(response, '请先粘贴职位描述文本再继续。')
        self.assertContains(response, '简历和职位描述输入')

    def test_invalid_language_falls_back_to_english(self):
        response = self.client.get('/?lang=unsupported')

        self.assertContains(response, 'CV and Job Description Input')
        self.assertContains(response, 'View Prototype Results')

    def test_run_another_analysis_preserves_selected_language(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': 'Python',
            'job_description_text': 'Django',
            'output_language': 'zh',
        })

        self.assertContains(response, 'href="/?lang=zh"')
        self.assertContains(response, '再次分析')
