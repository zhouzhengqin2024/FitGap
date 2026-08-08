import os
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.urls import reverse
from docx import Document
from pypdf import PdfWriter

from .document_extraction import DocumentExtractionError, extract_document_text
from .services import (
    build_skill_evidence_details,
    calculate_match_score,
    compare_skills,
    extract_skill_evidence,
    extract_skill_evidence_occurrences,
    extract_skills,
    generate_learning_recommendations,
)


def _uploaded_file(name, content, content_type='application/octet-stream'):
    return SimpleUploadedFile(name, content, content_type=content_type)


def _docx_bytes(text):
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def _text_pdf_bytes(text):
    stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'
    objects = [
        '1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n',
        '2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n',
        '3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n',
        '4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n',
        f'5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n',
    ]
    pdf = '%PDF-1.4\n'
    offsets = [0]

    for obj in objects:
        offsets.append(len(pdf.encode()))
        pdf += obj

    xref_offset = len(pdf.encode())
    xref_entries = ['0000000000 65535 f \n'] + [
        f'{offset:010d} 00000 n \n'
        for offset in offsets[1:]
    ]

    pdf += 'xref\n0 6\n'
    pdf += ''.join(xref_entries)
    pdf += f'trailer << /Root 1 0 R /Size 6 >>\nstartxref\n{xref_offset}\n%%EOF\n'
    return pdf.encode()


def _blank_pdf_bytes():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


class DocumentExtractionTests(SimpleTestCase):
    def test_valid_txt_extraction(self):
        uploaded_file = _uploaded_file('cv.txt', b'Python SQL Git')

        self.assertEqual(extract_document_text(uploaded_file), 'Python SQL Git')

    def test_valid_docx_extraction(self):
        uploaded_file = _uploaded_file(
            'cv.docx',
            _docx_bytes('Python and Django experience.'),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

        self.assertEqual(extract_document_text(uploaded_file), 'Python and Django experience.')

    def test_valid_text_based_pdf_extraction(self):
        uploaded_file = _uploaded_file('cv.pdf', _text_pdf_bytes('Python Django SQL'), 'application/pdf')

        self.assertIn('Python Django SQL', extract_document_text(uploaded_file))

    def test_unsupported_extension_rejection(self):
        uploaded_file = _uploaded_file('cv.png', b'not an accepted document')

        with self.assertRaises(DocumentExtractionError) as context:
            extract_document_text(uploaded_file)

        self.assertEqual(context.exception.code, 'unsupported_file_type')

    def test_oversized_file_rejection(self):
        uploaded_file = _uploaded_file('cv.txt', b'x' * ((5 * 1024 * 1024) + 1))

        with self.assertRaises(DocumentExtractionError) as context:
            extract_document_text(uploaded_file)

        self.assertEqual(context.exception.code, 'file_too_large')

    def test_empty_file_rejection(self):
        uploaded_file = _uploaded_file('cv.txt', b'')

        with self.assertRaises(DocumentExtractionError) as context:
            extract_document_text(uploaded_file)

        self.assertEqual(context.exception.code, 'empty_file')

    def test_corrupt_file_handling(self):
        uploaded_file = _uploaded_file('cv.docx', b'not a real docx')

        with self.assertRaises(DocumentExtractionError) as context:
            extract_document_text(uploaded_file)

        self.assertEqual(context.exception.code, 'corrupt_file')

    def test_pdf_with_no_readable_text(self):
        uploaded_file = _uploaded_file('blank.pdf', _blank_pdf_bytes(), 'application/pdf')

        with self.assertRaises(DocumentExtractionError) as context:
            extract_document_text(uploaded_file)

        self.assertEqual(context.exception.code, 'no_readable_text')

    def test_extracted_cv_text_enters_analysis_workflow(self):
        extraction_response = self.client.post(
            reverse('analysis:extract_document_text'),
            {'document': _uploaded_file('cv.txt', b'Python SQL Git')},
        )
        extracted_text = extraction_response.json()['text']
        response = self.client.post('/?lang=en', data={
            'cv_text': extracted_text,
            'job_description_text': 'Python SQL Django',
            'output_language': 'en',
        })

        self.assertContains(response, '67%')
        self.assertContains(response, 'Django')

    def test_extracted_job_description_text_enters_analysis_workflow(self):
        extraction_response = self.client.post(
            reverse('analysis:extract_document_text'),
            {'document': _uploaded_file('jd.txt', b'Python SQL Django')},
        )
        extracted_text = extraction_response.json()['text']
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': extracted_text,
            'output_language': 'en',
        })

        self.assertContains(response, '67%')
        self.assertContains(response, 'Complete a beginner Django tutorial')

    def test_pasted_text_only_workflow_remains_valid(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python SQL Django',
            'output_language': 'en',
        })

        self.assertContains(response, 'Prototype Analysis Results')
        self.assertContains(response, '67%')

    def test_uploaded_files_are_not_persisted(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse('analysis:extract_document_text'),
                    {'document': _uploaded_file('cv.txt', b'Python SQL')},
                )

                self.assertTrue(response.json()['success'])
                self.assertEqual(os.listdir(media_root), [])

    def test_extraction_errors_display_clearly(self):
        response = self.client.post(
            reverse('analysis:extract_document_text') + '?lang=en',
            {'document': _uploaded_file('cv.png', b'not supported')},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            'Unsupported file type. Please upload a PDF, DOCX or TXT file.',
        )

    def test_existing_extraction_endpoint_flow_remains_intact(self):
        response = self.client.post(
            reverse('analysis:extract_document_text') + '?lang=en',
            {'document': _uploaded_file('cv.txt', b'Python from uploaded TXT')},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'success': True,
            'text': 'Python from uploaded TXT',
        })


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


class CalculateMatchScoreTests(SimpleTestCase):
    def test_full_match_returns_100(self):
        self.assertEqual(calculate_match_score(['Python', 'SQL'], ['Python', 'SQL']), 100)

    def test_partial_match_returns_correctly_rounded_percentage(self):
        self.assertEqual(calculate_match_score(['Python', 'SQL'], ['Python', 'SQL', 'Git']), 67)

    def test_no_match_returns_0(self):
        self.assertEqual(calculate_match_score([], ['Python', 'SQL']), 0)

    def test_empty_job_description_skills_returns_0(self):
        self.assertEqual(calculate_match_score(['Python'], []), 0)

    def test_duplicate_skills_do_not_inflate_score(self):
        self.assertEqual(
            calculate_match_score(['Python', 'Python', 'SQL'], ['Python', 'Python', 'SQL', 'Git']),
            67,
        )

    def test_case_insensitive_skill_handling(self):
        self.assertEqual(calculate_match_score(['python', 'SQL'], ['Python', 'sql']), 100)

    def test_matched_skill_not_in_job_description_is_not_counted(self):
        self.assertEqual(calculate_match_score(['Python', 'Django'], ['Python', 'SQL']), 50)


class GenerateLearningRecommendationsTests(SimpleTestCase):
    def test_english_recommendation_for_one_missing_skill(self):
        self.assertEqual(
            generate_learning_recommendations(['Python'], 'en'),
            [{
                'skill': 'Python',
                'recommendation': (
                    'Review Python fundamentals, practise data structures and functions, and complete one small '
                    'programming project.'
                ),
            }],
        )

    def test_chinese_recommendation_for_one_missing_skill(self):
        self.assertEqual(
            generate_learning_recommendations(['Python'], 'zh'),
            [{
                'skill': 'Python',
                'recommendation': '复习 Python 基础、练习数据结构与函数，并完成一个小型编程项目。',
            }],
        )

    def test_multiple_missing_skills_preserve_order(self):
        recommendations = generate_learning_recommendations(['Django', 'REST APIs', 'JavaScript'], 'en')

        self.assertEqual([item['skill'] for item in recommendations], ['Django', 'REST APIs', 'JavaScript'])

    def test_duplicate_missing_skills_are_removed(self):
        recommendations = generate_learning_recommendations(['Django', 'django', 'REST APIs'], 'en')

        self.assertEqual([item['skill'] for item in recommendations], ['Django', 'REST APIs'])

    def test_case_insensitive_skill_handling(self):
        recommendations = generate_learning_recommendations(['python'], 'en')

        self.assertEqual(recommendations[0]['recommendation'], (
            'Review Python fundamentals, practise data structures and functions, and complete one small '
            'programming project.'
        ))

    def test_empty_missing_skills_list(self):
        self.assertEqual(generate_learning_recommendations([], 'en'), [])

    def test_invalid_language_falls_back_to_english(self):
        recommendations = generate_learning_recommendations(['SQL'], 'unsupported')

        self.assertEqual(
            recommendations[0]['recommendation'],
            'Learn SELECT, JOIN, GROUP BY, and subqueries, then practise with a small relational database.',
        )

    def test_unknown_skill_uses_generic_fallback(self):
        self.assertEqual(
            generate_learning_recommendations(['Cloud Security'], 'en'),
            [{
                'skill': 'Cloud Security',
                'recommendation': (
                    'Review the fundamentals of this skill, complete a structured tutorial, and apply it in a small '
                    'practical project.'
                ),
            }],
        )


class SkillEvidenceTests(SimpleTestCase):
    def test_exact_matched_term_is_returned(self):
        evidence = extract_skill_evidence_occurrences('Worked with PostgreSQL databases.', 'SQL')

        self.assertEqual(evidence[0]['matched_term'], 'PostgreSQL')

    def test_alias_metadata_is_returned(self):
        evidence = extract_skill_evidence_occurrences('Used GitLab for source control.', 'Git')

        self.assertEqual(evidence[0]['matched_term'], 'GitLab')
        self.assertTrue(evidence[0]['is_alias'])

    def test_canonical_match_is_not_marked_as_alias(self):
        evidence = extract_skill_evidence_occurrences('Used Git for source control.', 'Git')

        self.assertEqual(evidence[0]['matched_term'], 'Git')
        self.assertFalse(evidence[0]['is_alias'])

    def test_matched_skill_returns_cv_and_job_description_evidence(self):
        details = build_skill_evidence_details(
            ['Python'],
            [],
            'Built Python scripts for data cleaning.',
            'The role requires Python for automation.',
        )

        matched_detail = details['matched_skill_details'][0]

        self.assertEqual(matched_detail['skill'], 'Python')
        self.assertEqual(matched_detail['status'], 'matched')
        self.assertEqual(matched_detail['cv_evidence'][0]['excerpt'], 'Built Python scripts for data cleaning.')
        self.assertEqual(matched_detail['cv_evidence'][0]['matched_term'], 'Python')
        self.assertEqual(matched_detail['jd_evidence'][0]['excerpt'], 'The role requires Python for automation.')
        self.assertIn('classified as matched', matched_detail['explanation'])

    def test_matched_skill_explanation_is_generated(self):
        details = build_skill_evidence_details(
            ['Git'],
            [],
            'Used GitLab for source control.',
            'Git is required.',
        )

        self.assertEqual(
            details['matched_skill_details'][0]['explanation'],
            'Git was classified as matched because a configured term or alias was found in both the CV and the job description.',
        )

    def test_missing_skill_returns_job_description_evidence_and_no_cv_evidence(self):
        details = build_skill_evidence_details(
            [],
            ['Django'],
            'Built Python scripts.',
            'Experience with Django is required.',
        )

        missing_detail = details['missing_skill_details'][0]

        self.assertEqual(missing_detail['skill'], 'Django')
        self.assertEqual(missing_detail['status'], 'missing')
        self.assertEqual(missing_detail['cv_evidence'], [])
        self.assertEqual(missing_detail['jd_evidence'][0]['excerpt'], 'Experience with Django is required.')
        self.assertIn('no configured canonical term or alias', missing_detail['explanation'])

    def test_missing_skill_explanation_is_generated(self):
        details = build_skill_evidence_details(
            [],
            ['Django'],
            'Built Python scripts.',
            'Django is required.',
        )

        self.assertEqual(
            details['missing_skill_details'][0]['explanation'],
            'Django was recognised in the job description, but no configured canonical term or alias for Django was found in the CV.',
        )

    def test_alias_evidence_maps_to_canonical_skill(self):
        self.assertEqual(
            extract_skill_evidence('Used GitLab for source control.', 'Git'),
            ['Used GitLab for source control.'],
        )

    def test_case_insensitive_evidence_matching(self):
        self.assertEqual(
            extract_skill_evidence('Built services with PYTHON.', 'Python'),
            ['Built services with PYTHON.'],
        )

    def test_duplicate_excerpts_are_removed(self):
        evidence = extract_skill_evidence('Python automation.\nPython automation.', 'Python')

        self.assertEqual(evidence, ['Python automation.'])

    def test_maximum_evidence_limit_is_respected(self):
        evidence = extract_skill_evidence(
            'Python automation. Python testing. Python scripting.',
            'Python',
        )

        self.assertEqual(evidence, ['Python automation.', 'Python testing.'])

    def test_partial_word_false_positives_remain_prevented(self):
        self.assertEqual(extract_skill_evidence('Worked with githubactions pipelines.', 'Git'), [])

    def test_empty_or_unusual_text_does_not_crash(self):
        self.assertEqual(extract_skill_evidence('', 'Python'), [])
        self.assertEqual(extract_skill_evidence(None, 'Python'), [])
        self.assertEqual(extract_skill_evidence('   \n\t', 'Python'), [])


class InterfaceLanguageTests(SimpleTestCase):
    def test_english_input_page(self):
        response = self.client.get('/?lang=en')

        self.assertContains(response, 'CV and Job Description Input')
        self.assertContains(response, 'Interface and Output Language')
        self.assertContains(response, 'English interface and output')
        self.assertContains(response, 'AI Career Skill-Gap Assistant')
        self.assertContains(
            response,
            '<strong class="d-inline-block fs-5 mb-3 text-primary">AI Career Skill-Gap Assistant</strong>',
            html=True,
        )
        self.assertContains(response, 'See Your Skill Gaps. Learn What Matters Next.')
        self.assertContains(
            response,
            'Not sure how far you are from your target role or what to learn next? Upload your CV and a job description to uncover your skill gaps, verify the evidence, and',
        )
        self.assertContains(
            response,
            '<strong>build the right skills faster to move closer to the job you want.</strong>',
            html=True,
        )
        self.assertContains(response, 'Language:')
        self.assertContains(response, 'Upload CV')
        self.assertContains(response, 'Upload Job Description')
        self.assertContains(response, 'Supported formats: PDF, DOCX and TXT')
        self.assertContains(response, 'The extracted text can be reviewed and edited before analysis.')
        self.assertContains(response, 'Choose file')
        self.assertContains(response, 'No file selected')
        self.assertContains(response, 'href="/?lang=zh"')

    def test_chinese_input_page(self):
        response = self.client.get('/?lang=zh')

        self.assertContains(response, '简历和职位描述输入')
        self.assertContains(response, '界面和输出语言')
        self.assertContains(response, '简体中文界面和输出')
        self.assertContains(response, 'AI 求职技能差距助手')
        self.assertContains(
            response,
            '<strong class="d-inline-block fs-5 mb-3 text-primary">AI 求职技能差距助手</strong>',
            html=True,
        )
        self.assertContains(response, '看清技能差距，知道下一步该学什么。')
        self.assertContains(response, '不知道自己离目标岗位还有多远，也不知道下一步该学什么？上传简历和职位描述，快速识别技能差距、核实判断依据，')
        self.assertContains(
            response,
            '<strong>更高效地补齐关键技能，向理想岗位更进一步。</strong>',
            html=True,
        )
        self.assertContains(response, '语言：')
        self.assertContains(response, '上传简历')
        self.assertContains(response, '上传职位描述')
        self.assertContains(response, '支持格式：PDF、DOCX 和 TXT')
        self.assertContains(response, '分析前可以检查和修改提取的文本。')
        self.assertContains(response, '选择文件')
        self.assertContains(response, '未选择文件')
        self.assertContains(response, 'href="/?lang=en"')

    def test_native_file_inputs_still_exist_and_are_visually_hidden(self):
        response = self.client.get('/?lang=en')

        self.assertContains(response, 'type="file"', count=2)
        self.assertContains(response, 'name="cv_file"')
        self.assertContains(response, 'name="job_description_file"')
        self.assertContains(response, 'class="visually-hidden document-upload-input"', count=2)

    def test_accepted_file_extensions_remain_unchanged(self):
        response = self.client.get('/?lang=en')
        accept_value = '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'

        self.assertContains(response, f'accept="{accept_value}"', count=2)

    def test_cv_and_job_description_custom_controls_have_distinct_identifiers(self):
        response = self.client.get('/?lang=en')

        self.assertContains(response, 'id="id_cv_file_filename"')
        self.assertContains(response, 'id="id_job_description_file_filename"')
        self.assertContains(response, 'data-file-input="id_cv_file"')
        self.assertContains(response, 'data-file-input="id_job_description_file"')

    def test_existing_analysis_workflow_remains_intact_after_hero_addition(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python SQL Django',
            'output_language': 'en',
        })

        self.assertContains(response, 'Prototype Analysis Results')
        self.assertContains(response, '67%')
        self.assertContains(response, 'Complete a beginner Django tutorial and build a small CRUD web application.')

    def test_english_results_page(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })

        self.assertContains(response, 'Prototype Analysis Results')
        self.assertContains(response, 'Extracted Skills')
        self.assertContains(response, 'Matched Skills')
        self.assertContains(response, '67%')
        self.assertContains(response, '2 of 3 recognised job-description skills were found in the CV.')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')
        self.assertContains(response, 'Complete a beginner Django tutorial and build a small CRUD web application.')
        self.assertContains(response, 'Real rule-based output: practical next steps for each missing skill.')
        self.assertContains(response, 'Evidence from CV')
        self.assertContains(response, 'Evidence from Job Description')
        self.assertContains(response, 'No configured occurrence or alias was found in the CV.')
        self.assertContains(response, '<span class="badge text-bg-success">Matched</span>', html=True)
        self.assertContains(response, '<span class="badge text-bg-warning">Missing</span>', html=True)

    def test_duplicated_plain_matched_and_missing_skill_lists_are_removed(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })
        content = response.content.decode()
        matched_section = content.split('<h2 class="h4">Matched Skills</h2>', 1)[1].split(
            '<h2 class="h4">Missing Skills</h2>',
            1,
        )[0]
        missing_section = content.split('<h2 class="h4">Missing Skills</h2>', 1)[1].split(
            '<h2 class="h4">Learning Recommendations</h2>',
            1,
        )[0]

        self.assertNotIn('<ul class="list-group">', matched_section)
        self.assertNotIn('<ul class="list-group">', missing_section)
        self.assertIn('View explanation', matched_section)
        self.assertIn('View explanation', missing_section)

    def test_chinese_results_page(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'zh',
        })

        self.assertContains(response, '原型分析结果')
        self.assertContains(response, '提取的技能')
        self.assertContains(response, '匹配技能')
        self.assertContains(response, '67%')
        self.assertContains(response, '岗位描述中识别出的3项技能里，有2项在简历中被找到。')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')
        self.assertContains(response, '完成 Django 入门教程，并构建一个小型 CRUD Web 应用。')
        self.assertContains(response, '真实规则输出：针对每项缺失技能的实用后续学习步骤。')
        self.assertContains(response, '简历证据')
        self.assertContains(response, '职位描述证据')
        self.assertContains(response, '简历中未找到已配置的术语或别名。')
        self.assertContains(response, '<span class="badge text-bg-success">匹配</span>', html=True)
        self.assertContains(response, '<span class="badge text-bg-warning">缺失</span>', html=True)

    def test_exact_matched_term_is_highlighted_safely(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': '<script>alert(1)</script> Used GitLab safely.',
            'job_description_text': 'Git is required.',
            'output_language': 'en',
        })
        content = response.content.decode()

        self.assertIn('<mark>GitLab</mark>', content)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', content)
        self.assertNotIn('<script>alert(1)</script>', content)

    def test_english_no_missing_skills_recommendation_message(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL Django',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })

        self.assertContains(
            response,
            'No learning recommendations are needed because no recognised job-description skills are missing.',
        )

    def test_chinese_no_missing_skills_recommendation_message(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': 'Python SQL Django',
            'job_description_text': 'Python Django SQL',
            'output_language': 'zh',
        })

        self.assertContains(response, '没有需要生成的学习建议，因为未发现缺失的岗位技能。')

    def test_realistic_input_generates_rule_based_recommendations(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Developer with Python, SQL, GitLab, HTML5, CSS3, and Bootstrap experience.',
            'job_description_text': 'The role requires Django, REST APIs, PostgreSQL, Git, and JavaScript.',
            'output_language': 'en',
        })

        self.assertContains(response, 'Complete a beginner Django tutorial and build a small CRUD web application.')
        self.assertContains(response, 'Learn HTTP methods, status codes, JSON, and build and test a simple REST endpoint.')
        self.assertContains(
            response,
            'Review JavaScript fundamentals, DOM manipulation, events, and build one small interactive webpage.',
        )

    def test_end_to_end_result_context_includes_structured_evidence_details(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python developer. Used GitLab for collaboration.',
            'job_description_text': 'Needs Python, Git, and Django experience.',
            'output_language': 'en',
        })
        results = response.context['results']

        self.assertEqual(results['matched_skill_details'][0]['skill'], 'Python')
        self.assertEqual(results['matched_skill_details'][0]['cv_evidence'][0]['matched_term'], 'Python')
        self.assertFalse(results['matched_skill_details'][0]['cv_evidence'][0]['is_alias'])
        self.assertEqual(results['matched_skill_details'][1]['skill'], 'Git')
        self.assertEqual(results['matched_skill_details'][1]['cv_evidence'][0]['matched_term'], 'GitLab')
        self.assertTrue(results['matched_skill_details'][1]['cv_evidence'][0]['is_alias'])
        self.assertEqual(results['missing_skill_details'][0]['skill'], 'Django')
        self.assertEqual(results['missing_skill_details'][0]['cv_evidence'], [])
        self.assertEqual(
            results['missing_skill_details'][0]['jd_evidence'][0]['excerpt'],
            'Needs Python, Git, and Django experience.',
        )

    def test_english_zero_job_description_skill_explanation(self):
        response = self.client.post('/?lang=en', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'communication teamwork',
            'output_language': 'en',
        })

        self.assertContains(response, '0%')
        self.assertContains(response, 'No recognised job-description skills were found')

    def test_chinese_zero_job_description_skill_explanation(self):
        response = self.client.post('/?lang=zh', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'communication teamwork',
            'output_language': 'zh',
        })

        self.assertContains(response, '0%')
        self.assertContains(response, '岗位描述中未识别出技能')

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
