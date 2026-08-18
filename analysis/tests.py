import os
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.staticfiles import finders
from django.test import Client
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from docx import Document
from pypdf import PdfWriter

from .document_extraction import DocumentExtractionError, extract_document_text
from .ai_learning_roadmap import (
    LearningRoadmapUnavailable,
    ROADMAP_RESPONSE_SCHEMA,
    build_learning_roadmap_input,
    generate_learning_roadmap,
    validate_learning_roadmap,
)
from .ai_prioritisation import (
    AIPrioritisationUnavailable,
    GEMINI_MODEL,
    build_ai_gap_input,
    prioritise_skill_gaps,
    validate_ai_priorities,
)
from .models import AnalysisRecord
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


def _sample_roadmap(skills=None):
    skills = skills or ['Django']
    roadmap_skills = []

    for index, skill in enumerate(skills, start=1):
        roadmap_skills.append({
            'skill': skill,
            'priority': 'high' if index == 1 else 'medium',
            'stage': 'now' if index == 1 else 'next',
            'estimated_hours': '6-8 hours' if index == 1 else '3-4 hours',
            'target_outcome': f'Build and explain a practical {skill} feature for the target role.',
            'core_steps': [{
                'step_number': 1,
                'title': f'Build a {skill} mini feature',
                'action': f'Create a small deliverable using {skill}.',
                'estimated_hours': '4-6 hours',
                'completion_criteria': f'You can explain and demonstrate the completed {skill} work.',
                'why_this_step': f'This turns the {skill} gap into practical evidence.',
                'topics': [skill, 'project evidence'],
            }],
            'verification_standard': f'You can independently demonstrate the completed {skill} work.',
            'evidence_target': f'{skill} mini project with Git history and README',
            'details': {
                'minimum_features': ['working feature', 'validation', 'README'],
                'evidence_to_keep': ['GitLab repository', 'README', 'screenshot'],
                'interview_talking_points': ['Design decision', 'Validation approach'],
                'cv_usage_guidance': f'After completing and testing the work, use it as future {skill} project evidence.',
            },
        })

    return {
        'summary': {
            'immediate_next_action': {
                'skill': skills[0],
                'action': f'Create one observable {skills[0]} feature today.',
                'estimated_hours': '2-3 hours',
                'completion_criteria': f'You can demonstrate the {skills[0]} feature without following a tutorial.',
            },
            'core_estimated_hours': '12-18 hours',
            'suggested_pace': 'About 1-2 weeks at 2 hours per day.',
            'can_wait': 'Machine Learning can wait until core backend evidence is complete.',
            'strategy': 'Start with the highest priority gap and build one credible artifact. Keep applying while optional skills wait.',
        },
        'skills': roadmap_skills,
    }


class AnalysisRecordModelTests(TestCase):
    def _create_user(self, email='student@example.com', password='StrongPass123!'):
        User = get_user_model()
        return User.objects.create_user(
            username=email.lower(),
            email=email.lower(),
            password=password,
        )

    def test_analysis_record_can_be_created_for_authenticated_user(self):
        user = self._create_user()

        record = AnalysisRecord.objects.create(user=user, language='en', target_role='Untitled Analysis')

        self.assertEqual(record.user, user)
        self.assertEqual(record.language, 'en')
        self.assertEqual(record.target_role, 'Untitled Analysis')

    def test_analysis_record_requires_user_link(self):
        user_field = AnalysisRecord._meta.get_field('user')

        self.assertFalse(user_field.null)
        self.assertEqual(user_field.remote_field.model, get_user_model())

    def test_default_status_is_valid(self):
        user = self._create_user()
        record = AnalysisRecord.objects.create(user=user)

        self.assertEqual(record.status, AnalysisRecord.STATUS_STARTED)
        self.assertIn(record.status, dict(AnalysisRecord.STATUS_CHOICES))

    def test_json_snapshots_store_structured_data(self):
        user = self._create_user()
        record = AnalysisRecord.objects.create(
            user=user,
            analysis_snapshot={'matched_skills': ['Python']},
            priority_snapshot={'status': 'success', 'priorities': [{'skill': 'Django'}]},
            roadmap_snapshot={'skills': [{'skill': 'Django', 'core_steps': [{'title': 'Build'}]}]},
        )

        record.refresh_from_db()
        self.assertEqual(record.analysis_snapshot['matched_skills'], ['Python'])
        self.assertEqual(record.priority_snapshot['priorities'][0]['skill'], 'Django')
        self.assertEqual(record.roadmap_snapshot['skills'][0]['core_steps'][0]['title'], 'Build')

    def test_timestamps_are_created(self):
        user = self._create_user()
        record = AnalysisRecord.objects.create(user=user)

        self.assertIsNotNone(record.created_at)
        self.assertIsNotNone(record.updated_at)


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
        response = self.client.post('/analyse/?lang=en', data={
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
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': extracted_text,
            'output_language': 'en',
        })

        self.assertContains(response, '67%')
        self.assertContains(response, 'Complete a beginner Django tutorial')

    def test_pasted_text_only_workflow_remains_valid(self):
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python SQL Django',
            'output_language': 'en',
        })

        self.assertContains(response, 'Analysis Results')
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


class AIPrioritisationServiceTests(SimpleTestCase):
    def test_build_ai_gap_input_uses_verified_missing_skill_evidence_only(self):
        gap_input = build_ai_gap_input([
            {
                'skill': 'Django',
                'cv_evidence': [],
                'jd_evidence': [{'excerpt': 'Django is required.'}],
            },
        ])

        self.assertEqual(gap_input, [{
            'skill': 'Django',
            'jd_evidence': ['Django is required.'],
            'cv_evidence': None,
        }])

    def test_validate_ai_priorities_rejects_more_than_three_results(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            validate_ai_priorities({
                'priorities': [
                    {'skill': 'Django', 'priority': 'high', 'reason': 'Required for backend work.'},
                    {'skill': 'REST APIs', 'priority': 'high', 'reason': 'Needed for API work.'},
                    {'skill': 'JavaScript', 'priority': 'medium', 'reason': 'Useful for frontend tasks.'},
                    {'skill': 'SQL', 'priority': 'low', 'reason': 'Mentioned less strongly.'},
                ],
            }, ['Django', 'REST APIs', 'JavaScript', 'SQL'])

    def test_validate_ai_priorities_rejects_unverified_skill(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            validate_ai_priorities({
                'priorities': [
                    {'skill': 'AWS', 'priority': 'high', 'reason': 'Invented by the model.'},
                ],
            }, ['Django'])

    def test_validate_ai_priorities_rejects_duplicate_skills(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            validate_ai_priorities({
                'priorities': [
                    {'skill': 'Django', 'priority': 'high', 'reason': 'Required.'},
                    {'skill': 'django', 'priority': 'medium', 'reason': 'Duplicate.'},
                ],
            }, ['Django'])

    def test_validate_ai_priorities_rejects_invalid_priority(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            validate_ai_priorities({
                'priorities': [
                    {'skill': 'Django', 'priority': 'urgent', 'reason': 'Invalid label.'},
                ],
            }, ['Django'])

    def test_validate_ai_priorities_rejects_malformed_response(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            validate_ai_priorities({'items': []}, ['Django'])

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_gemini_api_key_triggers_fallback_exception(self):
        with self.assertRaises(AIPrioritisationUnavailable):
            prioritise_skill_gaps([{'skill': 'Django', 'jd_evidence': [], 'cv_evidence': []}], 'en')

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_prioritisation.genai')
    def test_gemini_generate_content_is_called_with_structured_output(self, mock_genai):
        class FakeResponse:
            text = '{"priorities":[{"skill":"Django","priority":"high","reason":"Django is required."}]}'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = FakeResponse()

        result = prioritise_skill_gaps([
            {
                'skill': 'Django',
                'cv_evidence': [],
                'jd_evidence': [{'excerpt': 'Django is required.'}],
            },
        ], 'en')

        mock_genai.Client.assert_called_once_with(api_key='test-key')
        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        self.assertEqual(call_kwargs['model'], GEMINI_MODEL)
        self.assertEqual(call_kwargs['config']['response_mime_type'], 'application/json')
        self.assertIn('response_json_schema', call_kwargs['config'])
        self.assertIn('Django is required.', call_kwargs['contents'])
        self.assertEqual(result[0]['skill'], 'Django')


class LearningRoadmapServiceTests(SimpleTestCase):
    def test_roadmap_response_schema_keeps_v11_fields_but_avoids_business_constraints(self):
        summary_schema = ROADMAP_RESPONSE_SCHEMA['properties']['summary']
        skill_schema = ROADMAP_RESPONSE_SCHEMA['properties']['skills']['items']
        details_schema = skill_schema['properties']['details']

        self.assertEqual(ROADMAP_RESPONSE_SCHEMA['required'], ['summary', 'skills'])
        self.assertIn('core_estimated_hours', summary_schema['required'])
        self.assertIn('suggested_pace', summary_schema['required'])
        self.assertIn('can_wait', summary_schema['required'])
        self.assertIn('immediate_next_action', summary_schema['required'])
        self.assertEqual(
            summary_schema['properties']['immediate_next_action']['required'],
            ['skill', 'action', 'estimated_hours', 'completion_criteria'],
        )
        self.assertIn('core_steps', skill_schema['required'])
        self.assertIn('estimated_hours', skill_schema['required'])
        self.assertIn('target_outcome', skill_schema['required'])
        self.assertIn('verification_standard', skill_schema['required'])
        self.assertIn('evidence_target', skill_schema['required'])
        self.assertEqual(skill_schema['properties']['core_steps']['items']['properties']['step_number']['type'], 'integer')
        self.assertEqual(skill_schema['properties']['priority'], {'type': 'string'})
        self.assertEqual(skill_schema['properties']['stage'], {'type': 'string'})
        for field in [
            'minimum_features',
            'evidence_to_keep',
            'interview_talking_points',
            'cv_usage_guidance',
        ]:
            self.assertIn(field, details_schema['required'])

        self.assertNotIn('additionalProperties', str(ROADMAP_RESPONSE_SCHEMA))
        self.assertNotIn('maxItems', str(ROADMAP_RESPONSE_SCHEMA))
        self.assertNotIn('minItems', str(ROADMAP_RESPONSE_SCHEMA))
        self.assertNotIn('enum', str(ROADMAP_RESPONSE_SCHEMA))

    def test_build_learning_roadmap_input_uses_minimised_structured_data(self):
        roadmap_input = build_learning_roadmap_input({
            'cv_skills': ['Python', 'SQL'],
            'missing_skill_details': [{
                'skill': 'Django',
                'jd_evidence': [{'excerpt': 'Django is required.'}],
                'cv_evidence': [],
            }],
            'ai_prioritisation': {
                'status': 'success',
                'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Core backend skill.'}],
            },
        })

        self.assertEqual(roadmap_input, {
            'existing_skills': ['Python', 'SQL'],
            'priority_gaps': [{
                'skill': 'Django',
                'priority': 'high',
                'priority_reason': 'Core backend skill.',
                'jd_evidence': ['Django is required.'],
                'cv_evidence': None,
            }],
        })

    def test_validate_learning_roadmap_accepts_valid_structure(self):
        roadmap = validate_learning_roadmap(_sample_roadmap(['Django']), ['Django'])

        self.assertEqual(roadmap['summary']['core_estimated_hours'], '12-18 hours')
        self.assertEqual(roadmap['summary']['suggested_pace'], 'About 1-2 weeks at 2 hours per day.')
        self.assertIn('Machine Learning can wait', roadmap['summary']['can_wait'])
        self.assertGreater(len(roadmap['summary']['strategy']), 0)
        self.assertLessEqual(len(roadmap['summary']['strategy']), 320)
        self.assertEqual(roadmap['summary']['immediate_next_action']['skill'], 'Django')
        self.assertIn('completion_criteria', roadmap['summary']['immediate_next_action'])
        self.assertEqual(roadmap['skills'][0]['skill'], 'Django')
        self.assertEqual(roadmap['skills'][0]['estimated_hours'], '6-8 hours')
        self.assertEqual(roadmap['skills'][0]['core_steps'][0]['estimated_hours'], '4-6 hours')
        self.assertIn('minimum_features', roadmap['skills'][0]['details'])
        self.assertIn('interview_talking_points', roadmap['skills'][0]['details'])
        self.assertIn('cv_usage_guidance', roadmap['skills'][0]['details'])

    def test_validate_learning_roadmap_accepts_chinese_prose_with_canonical_machine_values(self):
        roadmap_data = _sample_roadmap(['Django'])
        roadmap_data['skills'][0]['target_outcome'] = '能够构建并解释一个 Django 功能。'
        roadmap_data['skills'][0]['priority'] = 'high'
        roadmap_data['skills'][0]['stage'] = 'now'

        roadmap = validate_learning_roadmap(roadmap_data, ['Django'])

        self.assertEqual(roadmap['skills'][0]['priority'], 'high')
        self.assertEqual(roadmap['skills'][0]['stage'], 'now')
        self.assertEqual(roadmap['skills'][0]['target_outcome'], '能够构建并解释一个 Django 功能。')

    def test_validate_learning_roadmap_normalises_priority_and_stage_casing(self):
        roadmap_data = _sample_roadmap(['Django'])
        roadmap_data['skills'][0]['priority'] = 'High'
        roadmap_data['skills'][0]['stage'] = 'NOW'

        roadmap = validate_learning_roadmap(roadmap_data, ['Django'])

        self.assertEqual(roadmap['skills'][0]['priority'], 'high')
        self.assertEqual(roadmap['skills'][0]['stage'], 'now')

    def test_validate_learning_roadmap_normalises_priority_and_stage_whitespace(self):
        roadmap_data = _sample_roadmap(['Django'])
        roadmap_data['skills'][0]['priority'] = ' high '
        roadmap_data['skills'][0]['stage'] = ' now '

        roadmap = validate_learning_roadmap(roadmap_data, ['Django'])

        self.assertEqual(roadmap['skills'][0]['priority'], 'high')
        self.assertEqual(roadmap['skills'][0]['stage'], 'now')

    def test_validate_learning_roadmap_rejects_hallucinated_skill(self):
        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(_sample_roadmap(['AWS']), ['Django'])

    def test_validate_learning_roadmap_rejects_duplicate_skill(self):
        roadmap = _sample_roadmap(['Django', 'Django'])

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_invalid_priority(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['priority'] = 'urgent'

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_translated_priority(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['priority'] = '高优先级'

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_invalid_stage(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['stage'] = 'immediately'

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_arbitrary_stage_alternative(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['stage'] = 'first'

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_more_than_three_skills(self):
        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(_sample_roadmap(['Django', 'REST APIs', 'JavaScript', 'SQL']), [
                'Django',
                'REST APIs',
                'JavaScript',
                'SQL',
            ])

    def test_validate_learning_roadmap_rejects_more_than_three_high_priority_core_steps(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['core_steps'] = roadmap['skills'][0]['core_steps'] * 4

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_more_than_three_medium_priority_core_steps(self):
        roadmap = _sample_roadmap(['Django', 'REST APIs'])
        roadmap['skills'][1]['core_steps'] = roadmap['skills'][1]['core_steps'] * 4

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django', 'REST APIs'])

    def test_validate_learning_roadmap_rejects_more_than_one_low_priority_core_step(self):
        roadmap = _sample_roadmap(['Machine Learning'])
        roadmap['skills'][0]['priority'] = 'low'
        roadmap['skills'][0]['stage'] = 'later'
        roadmap['skills'][0]['core_steps'] = roadmap['skills'][0]['core_steps'] * 2

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Machine Learning'])

    def test_validate_learning_roadmap_accepts_low_priority_optional_without_core_steps(self):
        roadmap = _sample_roadmap(['Machine Learning'])
        roadmap['skills'][0]['priority'] = 'low'
        roadmap['skills'][0]['stage'] = 'later'
        roadmap['skills'][0]['core_steps'] = []

        validated = validate_learning_roadmap(roadmap, ['Machine Learning'])

        self.assertEqual(validated['skills'][0]['core_steps'], [])

    def test_validate_learning_roadmap_rejects_empty_required_field(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['core_steps'][0]['completion_criteria'] = ''

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_unknown_immediate_action_skill(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['summary']['immediate_next_action']['skill'] = 'AWS'

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_empty_recruitment_value(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['evidence_target'] = ''

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_empty_minimum_features(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['details']['minimum_features'] = []

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_excessive_minimum_features(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['details']['minimum_features'] = [f'Feature {index}' for index in range(9)]

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_excessive_evidence_items(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['details']['evidence_to_keep'] = [f'Evidence {index}' for index in range(7)]

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_excessive_interview_talking_points(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['skills'][0]['details']['interview_talking_points'] = [
            f'Talking point {index}' for index in range(5)
        ]

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_malformed_evidence_schema(self):
        roadmap = _sample_roadmap(['Django'])
        del roadmap['skills'][0]['details']['cv_usage_guidance']

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    def test_validate_learning_roadmap_rejects_malformed_or_empty_response(self):
        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap({'summary': {}, 'skills': []}, ['Django'])

    def test_validate_learning_roadmap_rejects_overlong_strategy(self):
        roadmap = _sample_roadmap(['Django'])
        roadmap['summary']['strategy'] = 'Too long. ' * 40

        with self.assertRaises(LearningRoadmapUnavailable):
            validate_learning_roadmap(roadmap, ['Django'])

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_gemini_api_key_triggers_roadmap_fallback_exception(self):
        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{'skill': 'Django', 'jd_evidence': [], 'cv_evidence': []}],
                }, 'en')

        self.assertIn(
            'Learning roadmap unavailable: missing API key or Gemini SDK unavailable',
            '\n'.join(logs.output),
        )

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_logs_validation_failure_reason_safely(self, mock_genai):
        class FakeResponse:
            text = '{"summary":{},"skills":[]}'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = FakeResponse()

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{
                        'skill': 'Django',
                        'jd_evidence': [{'excerpt': 'Django is required.'}],
                        'cv_evidence': [],
                    }],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn('Learning roadmap validation failed: skills is empty', logged_output)
        self.assertNotIn('Django is required.', logged_output)
        self.assertNotIn('test-key', logged_output)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_json_failure_does_not_log_raw_response(self, mock_genai):
        class FakeResponse:
            text = 'not json with raw private CV details'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value = FakeResponse()

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{'skill': 'Django', 'jd_evidence': [], 'cv_evidence': []}],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn('Learning roadmap JSON parsing failed: JSONDecodeError', logged_output)
        self.assertNotIn('raw private CV details', logged_output)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_sdk_failure_does_not_log_exception_payload(self, mock_genai):
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = RuntimeError('private JD payload test-key')

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{'skill': 'Django', 'jd_evidence': [], 'cv_evidence': []}],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn(
            'Learning roadmap Gemini request failed: RuntimeError status=unknown code=unknown message="unavailable"',
            logged_output,
        )
        self.assertNotIn('private JD payload', logged_output)
        self.assertNotIn('test-key', logged_output)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_client_error_logs_safe_api_metadata(self, mock_genai):
        class FakeClientError(Exception):
            code = 400
            status = 'INVALID_ARGUMENT'
            message = 'Invalid response_json_schema: unsupported field additionalProperties.'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = FakeClientError()

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{
                        'skill': 'Django',
                        'jd_evidence': [{'excerpt': 'Django is required.'}],
                        'cv_evidence': [],
                    }],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn('Learning roadmap Gemini request failed: FakeClientError', logged_output)
        self.assertIn('status=400', logged_output)
        self.assertIn('code=INVALID_ARGUMENT', logged_output)
        self.assertIn('Invalid response_json_schema: unsupported field additionalProperties.', logged_output)
        self.assertNotIn('test-key', logged_output)
        self.assertNotIn('Django is required.', logged_output)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_client_error_omits_message_with_raw_evidence(self, mock_genai):
        class FakeClientError(Exception):
            code = 400
            status = 'INVALID_ARGUMENT'
            message = 'Invalid request included Django is required for this role.'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = FakeClientError()

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{
                        'skill': 'Django',
                        'jd_evidence': [{'excerpt': 'Django is required for this role.'}],
                        'cv_evidence': [],
                    }],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn('status=400', logged_output)
        self.assertIn('code=INVALID_ARGUMENT', logged_output)
        self.assertIn('[omitted unsafe or overly long API message]', logged_output)
        self.assertNotIn('Django is required for this role.', logged_output)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=True)
    @patch('analysis.ai_learning_roadmap.genai')
    def test_learning_roadmap_client_error_redacts_personal_identifiers(self, mock_genai):
        class FakeClientError(Exception):
            code = 400
            status = 'INVALID_ARGUMENT'
            message = 'Invalid schema for ada@example.com and +44 7700 900123.'

        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = FakeClientError()

        with self.assertLogs('analysis.ai_learning_roadmap', level='WARNING') as logs:
            with self.assertRaises(LearningRoadmapUnavailable):
                generate_learning_roadmap({
                    'cv_skills': ['Python'],
                    'ai_prioritisation': {
                        'status': 'success',
                        'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Required.'}],
                    },
                    'missing_skill_details': [{'skill': 'Django', 'jd_evidence': [], 'cv_evidence': []}],
                }, 'en')

        logged_output = '\n'.join(logs.output)
        self.assertIn('[redacted-email]', logged_output)
        self.assertIn('[redacted-phone]', logged_output)
        self.assertNotIn('ada@example.com', logged_output)
        self.assertNotIn('+44 7700 900123', logged_output)


class InterfaceLanguageTests(TestCase):
    def _create_user(self, email='student@example.com', password='StrongPass123!'):
        User = get_user_model()
        return User.objects.create_user(
            username=email.lower(),
            email=email.lower(),
            password=password,
        )

    def _login_user(self, email='student@example.com', password='StrongPass123!'):
        self._create_user(email, password)
        self.assertTrue(self.client.login(username=email.lower(), password=password))

    def _results_response(self, language='en', cv_text='Python SQL Git', job_description_text='Python SQL Django REST APIs JavaScript'):
        return self.client.post(f'/analyse/?lang={language}', data={
            'cv_text': cv_text,
            'job_description_text': job_description_text,
            'output_language': language,
        })

    def _post_ai_prioritisation(self, results_response, language='en'):
        return self.client.post(f'/results/ai-prioritise/?lang={language}', data={
            'analysis_payload': results_response.context['analysis_payload'],
            'output_language': language,
        })

    def _switch_full_analysis_language(self, response, language):
        return self.client.post(f'/results/full-analysis/?lang={language}', data={
            'analysis_payload': response.context['analysis_payload'],
            'output_language': language,
        })

    def _switch_ai_results_language(self, response, language):
        return self.client.post(f'/results/ai-results/?lang={language}', data={
            'analysis_payload': response.context['analysis_payload'],
            'output_language': language,
        })

    def _post_learning_roadmap(self, response, language='en'):
        return self.client.post(f'/results/ai-learning-roadmap/?lang={language}', data={
            'analysis_payload': response.context['analysis_payload'],
            'output_language': language,
        })

    def _post_roadmap_auth_start(self, response, language='en', target='register'):
        return self.client.post(f'/account/roadmap-continuity/?lang={language}', data={
            'analysis_payload': response.context['analysis_payload'],
            'output_language': language,
            'target': target,
        })

    def _switch_learning_roadmap_language(self, response, language):
        return self.client.post(f'/results/learning-roadmap/?lang={language}', data={
            'analysis_payload': response.context['analysis_payload'],
            'output_language': language,
        })

    def _assert_account_menu_trigger(self, response):
        self.assertContains(response, 'data-account-drawer-trigger')
        self.assertContains(response, 'aria-controls="fitgap-account-drawer"')
        self.assertContains(response, 'aria-expanded="false"')

    def _assert_guest_drawer(self, response):
        self._assert_account_menu_trigger(response)
        self.assertContains(response, 'Browsing as Guest')
        self.assertContains(response, "You can explore FitGap&#x27;s skill-gap analysis without an account.", html=False)
        self.assertContains(response, 'Sign In')
        self.assertContains(response, 'Create Account')
        self.assertContains(response, 'href="/account/login/?lang=en"')
        self.assertContains(response, 'href="/account/register/?lang=en"')

    def _assert_authenticated_drawer(self, response, email='student@example.com'):
        self._assert_account_menu_trigger(response)
        self.assertContains(response, 'Signed in')
        self.assertContains(response, email)
        self.assertContains(response, 'Start New Analysis')
        self.assertContains(response, 'My Analyses')
        self.assertContains(response, 'My FitGap')
        self.assertContains(response, 'Log out')
        self.assertContains(response, 'name="account_action" value="logout"')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_english_landing_page_renders_entry_experience(self, mock_prioritise, mock_roadmap):
        response = self.client.get('/?lang=en')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/landing.html')
        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')
        self.assertContains(response, 'AI Career Skill-Gap Assistant')
        self.assertContains(response, 'See Your Skill Gaps in Just Three Steps. Know What to Do Next.')
        self.assertContains(response, 'Try FitGap Free →')
        self.assertContains(response, 'No account required. Analyse your CV and target role first.')
        self.assertContains(response, 'href="/analyse/?lang=en"')
        self.assertContains(response, 'Sign In / Create Account')
        self.assertContains(response, 'href="/account/login/?lang=en"')
        self.assertContains(response, 'Identify the Gap')
        self.assertContains(response, 'Prioritise What Matters')
        self.assertContains(response, 'Build a Clear Path')
        self.assertContains(response, 'href="/?lang=zh"')
        self.assertNotContains(response, 'fake user')
        self.assertNotContains(response, 'trusted by')
        self.assertNotContains(response, 'Pricing')

    def test_chinese_landing_page_renders_entry_experience(self):
        response = self.client.get('/?lang=zh')

        self.assertTemplateUsed(response, 'analysis/landing.html')
        self.assertContains(response, 'AI 求职技能差距助手')
        self.assertContains(response, '看清技能差距，仅需三步，知道下一步怎么做。')
        self.assertContains(response, '免费体验一次 →')
        self.assertContains(response, '无需注册，先体验完整的技能差距分析流程。')
        self.assertContains(response, 'href="/analyse/?lang=zh"')
        self.assertContains(response, '登录 / 注册')
        self.assertContains(response, 'href="/account/login/?lang=zh"')
        self.assertContains(response, '识别差距')
        self.assertContains(response, '明确优先级')
        self.assertContains(response, '形成行动路径')
        self.assertContains(response, 'href="/?lang=en"')

    def test_guest_landing_page_renders_account_drawer(self):
        response = self.client.get('/?lang=en')

        self._assert_guest_drawer(response)
        self.assertContains(response, '☰')
        self.assertContains(response, 'Menu')
        self.assertContains(response, 'Open account menu')
        self.assertContains(response, 'Close account menu')
        self.assertContains(response, 'fitgap-account-drawer')

    def test_authenticated_landing_page_renders_account_drawer(self):
        self._login_user()
        response = self.client.get('/?lang=en')

        self._assert_authenticated_drawer(response)
        self.assertNotContains(response, 'Browsing as Guest')
        self.assertContains(response, 'You&#x27;re signed in', html=False)
        self.assertContains(response, 'Your FitGap account is ready. Start a new analysis or manage your account.')
        self.assertContains(response, 'Start New Analysis →')
        self.assertContains(response, 'My FitGap')
        self.assertNotContains(response, 'Sign In / Create Account')

    def test_chinese_guest_landing_page_renders_account_drawer(self):
        response = self.client.get('/?lang=zh')

        self._assert_account_menu_trigger(response)
        self.assertContains(response, '菜单')
        self.assertContains(response, '打开账号菜单')
        self.assertContains(response, '关闭账号菜单')
        self.assertContains(response, '游客模式')
        self.assertContains(response, '无需账号即可体验 FitGap 的技能差距分析。')
        self.assertContains(response, '登录')
        self.assertContains(response, '注册账号')
        self.assertContains(response, 'href="/account/login/?lang=zh"')
        self.assertContains(response, 'href="/account/register/?lang=zh"')

    def test_chinese_authenticated_landing_page_renders_account_drawer(self):
        self._login_user()
        response = self.client.get('/?lang=zh')

        self._assert_account_menu_trigger(response)
        self.assertContains(response, '已登录')
        self.assertContains(response, 'student@example.com')
        self.assertContains(response, '开始新的分析')
        self.assertContains(response, '我的分析')
        self.assertContains(response, '我的 FitGap')
        self.assertContains(response, '退出登录')
        self.assertContains(response, '你的账号已可使用。开始新的分析，或进入我的 FitGap。')
        self.assertNotContains(response, '登录 / 注册')

    def test_language_switch_preserves_authenticated_drawer_state(self):
        self._login_user()
        response = self.client.get('/?lang=zh')

        self.assertContains(response, '菜单')
        self.assertContains(response, '已登录')
        self.assertContains(response, 'student@example.com')
        self.assertIn('_auth_user_id', self.client.session)

    def test_landing_language_switch_stays_on_landing_page(self):
        response = self.client.get('/?lang=en')

        self.assertContains(response, 'href="/?lang=zh"')
        self.assertNotContains(response, 'href="/analyse/?lang=zh">简体中文</a>')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_guest_account_entry_redirects_to_login_without_ai_calls(self, mock_prioritise, mock_roadmap):
        response = self.client.get('/account/?lang=en')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/account/login/?lang=en')

    def test_english_login_page_renders_login_form_only(self):
        response = self.client.get('/account/login/?lang=en')

        self.assertTemplateUsed(response, 'analysis/account_login.html')
        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')
        self.assertContains(response, 'Welcome back')
        self.assertContains(response, 'Sign In')
        self.assertContains(response, 'New to FitGap?')
        self.assertContains(response, 'Create an account →')
        self.assertContains(response, 'Email')
        self.assertContains(response, 'Password')
        self.assertNotContains(response, 'Confirm password')
        self.assertNotContains(response, 'Create your FitGap account')
        self.assertContains(response, 'Keep Your Progress with FitGap')
        self.assertContains(response, 'Your career progress shouldn&#x27;t disappear after one session.', html=False)
        self.assertContains(response, 'href="/account/register/?lang=en"')

    def test_english_register_page_renders_registration_form_only(self):
        response = self.client.get('/account/register/?lang=en')

        self.assertTemplateUsed(response, 'analysis/account_register.html')
        self.assertContains(response, 'Create your FitGap account')
        self.assertContains(response, 'Create Account')
        self.assertContains(response, 'Already have an account?')
        self.assertContains(response, 'Sign in →')
        self.assertContains(response, 'Email')
        self.assertContains(response, 'Password')
        self.assertContains(response, 'Confirm password')
        self.assertNotContains(response, 'Welcome back')
        self.assertNotContains(response, 'New to FitGap?')
        self.assertContains(response, 'Keep Your Progress with FitGap')
        self.assertContains(response, 'href="/account/login/?lang=en"')

    def test_chinese_login_page_renders(self):
        response = self.client.get('/account/login/?lang=zh')

        self.assertTemplateUsed(response, 'analysis/account_login.html')
        self.assertContains(response, '欢迎回来')
        self.assertContains(response, '登录')
        self.assertContains(response, '第一次使用 FitGap？')
        self.assertContains(response, '创建账号 →')
        self.assertContains(response, '邮箱')
        self.assertContains(response, '密码')
        self.assertNotContains(response, '确认密码')
        self.assertContains(response, '让你的 FitGap 分析持续积累')
        self.assertContains(response, 'href="/account/register/?lang=zh"')

    def test_chinese_register_page_renders(self):
        response = self.client.get('/account/register/?lang=zh')

        self.assertTemplateUsed(response, 'analysis/account_register.html')
        self.assertContains(response, '创建你的 FitGap 账号')
        self.assertContains(response, '创建账号')
        self.assertContains(response, '已有账号？')
        self.assertContains(response, '返回登录 →')
        self.assertContains(response, '邮箱')
        self.assertContains(response, '密码')
        self.assertContains(response, '确认密码')
        self.assertNotContains(response, '欢迎回来')
        self.assertContains(response, '让你的 FitGap 分析持续积累')
        self.assertContains(response, 'href="/account/login/?lang=zh"')

    def test_login_page_renders_account_drawer(self):
        response = self.client.get('/account/login/?lang=en')

        self._assert_guest_drawer(response)

    def test_register_page_renders_account_drawer(self):
        response = self.client.get('/account/register/?lang=en')

        self._assert_guest_drawer(response)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_english_roadmap_account_gate_context_renders_without_ai_calls(self, mock_prioritise, mock_roadmap):
        response = self.client.get('/account/login/?lang=en&intent=roadmap')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/account_login.html')
        self.assertContains(response, 'Unlock Your Personalised Learning Roadmap')
        self.assertContains(response, 'Sign in or create an account to continue.')
        self.assertContains(response, 'href="/account/login/?lang=zh&amp;intent=roadmap"', html=False)
        self.assertContains(response, 'href="/account/register/?lang=en&amp;intent=roadmap"', html=False)
        self.assertContains(response, 'action="/account/login/?lang=en&amp;intent=roadmap"', html=False)
        self.assertNotContains(response, 'My AI Learning Roadmap')

    def test_chinese_roadmap_account_gate_context_renders(self):
        response = self.client.get('/account/register/?lang=zh&intent=roadmap')

        self.assertContains(response, '解锁你的个性化学习路线')
        self.assertContains(response, '登录或创建账号后继续。')
        self.assertContains(response, 'href="/account/register/?lang=en&amp;intent=roadmap"', html=False)
        self.assertContains(response, 'href="/account/login/?lang=zh&amp;intent=roadmap"', html=False)
        self.assertContains(response, 'action="/account/register/?lang=zh&amp;intent=roadmap"', html=False)

    def test_login_register_links_preserve_roadmap_intent(self):
        login_response = self.client.get('/account/login/?lang=en&intent=roadmap')
        register_response = self.client.get('/account/register/?lang=en&intent=roadmap')

        self.assertContains(login_response, 'href="/account/register/?lang=en&amp;intent=roadmap"', html=False)
        self.assertContains(register_response, 'href="/account/login/?lang=en&amp;intent=roadmap"', html=False)

    def test_auth_language_switch_preserves_page_and_roadmap_intent(self):
        login_response = self.client.get('/account/login/?lang=en&intent=roadmap')
        register_response = self.client.get('/account/register/?lang=zh&intent=roadmap')

        self.assertContains(login_response, 'href="/account/login/?lang=zh&amp;intent=roadmap"', html=False)
        self.assertContains(register_response, 'href="/account/register/?lang=en&amp;intent=roadmap"', html=False)

    def test_auth_password_fields_are_not_server_prefilled(self):
        login_response = self.client.get('/account/login/?lang=en')
        register_response = self.client.get('/account/register/?lang=en')

        self.assertContains(login_response, 'type="password"', count=1)
        self.assertContains(register_response, 'type="password"', count=2)
        self.assertNotContains(login_response, 'name="login-password" value=')
        self.assertNotContains(register_response, 'name="register-password" value=')
        self.assertNotContains(register_response, 'name="register-confirm_password" value=')

    def test_valid_registration_creates_hashed_user_and_logs_in(self):
        response = self.client.post('/account/register/?lang=en', data={
            'register-email': 'Student@Example.com',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'VeryStrongPass123!',
        }, follow=True)
        User = get_user_model()
        user = User.objects.get()

        self.assertRedirects(response, '/account/?lang=en')
        self.assertEqual(user.username, 'student@example.com')
        self.assertEqual(user.email, 'student@example.com')
        self.assertNotEqual(user.password, 'VeryStrongPass123!')
        self.assertTrue(user.check_password('VeryStrongPass123!'))
        self.assertContains(response, 'You&#x27;re signed in to FitGap', html=False)
        self.assertContains(response, 'student@example.com')
        self.assertNotContains(response, 'Confirm password')

    def test_registration_with_roadmap_intent_redirects_to_new_analysis(self):
        response = self.client.post('/account/register/?lang=en&intent=roadmap', data={
            'register-email': 'student@example.com',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'VeryStrongPass123!',
        }, follow=True)

        self.assertRedirects(response, '/analyse/?lang=en')
        self.assertContains(
            response,
            'Your previous analysis could not be restored. Please start a new analysis.',
        )
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_duplicate_email_registration_is_rejected_case_insensitively(self):
        self._create_user(email='student@example.com')
        response = self.client.post('/account/register/?lang=en', data={
            'register-email': 'STUDENT@example.com',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'VeryStrongPass123!',
        })

        self.assertContains(response, 'An account already exists for this email address.')
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_registration_rejects_invalid_email_mismatched_passwords_and_missing_fields(self):
        invalid_response = self.client.post('/account/register/?lang=en', data={
            'register-email': 'not-an-email',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'DifferentPass123!',
        })
        missing_response = self.client.post('/account/register/?lang=en', data={})

        self.assertContains(invalid_response, 'Please enter a valid email address.')
        self.assertContains(invalid_response, 'The two passwords do not match.')
        self.assertNotContains(invalid_response, 'VeryStrongPass123!')
        self.assertNotContains(invalid_response, 'DifferentPass123!')
        self.assertContains(missing_response, 'Please enter your email address.')
        self.assertContains(missing_response, 'Please enter your password.')
        self.assertContains(missing_response, 'Please confirm your password.')
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_registration_uses_django_password_validation(self):
        response = self.client.post('/account/register/?lang=en', data={
            'register-email': 'student@example.com',
            'register-password': 'password',
            'register-confirm_password': 'password',
        })

        self.assertContains(response, 'This password is too common.')
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_valid_login_establishes_authenticated_session(self):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        response = self.client.post('/account/login/?lang=en', data={
            'login-email': 'STUDENT@example.com',
            'login-password': 'VeryStrongPass123!',
        }, follow=True)

        self.assertRedirects(response, '/account/?lang=en')
        self.assertContains(response, 'You&#x27;re signed in to FitGap', html=False)
        self.assertContains(response, 'student@example.com')
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_rejects_invalid_unknown_and_missing_credentials(self):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        wrong_response = self.client.post('/account/login/?lang=en', data={
            'login-email': 'student@example.com',
            'login-password': 'WrongPass123!',
        })
        unknown_response = self.client.post('/account/login/?lang=en', data={
            'login-email': 'unknown@example.com',
            'login-password': 'VeryStrongPass123!',
        })
        missing_response = self.client.post('/account/login/?lang=en', data={})

        self.assertContains(wrong_response, 'The email or password is incorrect.')
        self.assertNotContains(wrong_response, 'WrongPass123!')
        self.assertContains(unknown_response, 'The email or password is incorrect.')
        self.assertNotContains(unknown_response, 'VeryStrongPass123!')
        self.assertContains(missing_response, 'Please enter your email address.')
        self.assertContains(missing_response, 'Please enter your password.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_with_roadmap_intent_redirects_to_new_analysis(self):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        response = self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        }, follow=True)

        self.assertRedirects(response, '/analyse/?lang=en')
        self.assertContains(
            response,
            'Your previous analysis could not be restored. Please start a new analysis.',
        )

    def test_authenticated_account_page_shows_state_and_logout(self):
        self._login_user()
        response = self.client.get('/account/?lang=en')

        self._assert_authenticated_drawer(response)
        self.assertContains(response, 'You&#x27;re signed in to FitGap', html=False)
        self.assertContains(response, 'student@example.com')
        self.assertContains(response, 'Your account can unlock personalised learning roadmaps.')
        self.assertContains(response, 'Start New Analysis →')
        self.assertContains(response, 'Log out')
        self.assertNotContains(response, 'Confirm password')

    def test_chinese_authenticated_account_page_renders(self):
        self._login_user(email='student@example.com')
        response = self.client.get('/account/?lang=zh')

        self.assertContains(response, '你已登录 FitGap')
        self.assertContains(response, '你的账号可以解锁个性化学习路线。')
        self.assertContains(response, '开始新的分析 →')
        self.assertContains(response, '退出登录')

    def test_logout_ends_session_without_deleting_user(self):
        self._login_user()
        response = self.client.post('/account/?lang=en', data={
            'account_action': 'logout',
        }, follow=True)

        self.assertRedirects(response, '/?lang=en')
        self.assertContains(response, 'Signed out successfully.')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_english_input_page(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertContains(response, 'CV and Job Description Input')
        self.assertContains(response, 'Interface and Output Language')
        self.assertContains(response, 'English interface and output')
        self.assertContains(response, 'AI Career Skill-Gap Assistant')
        self.assertContains(
            response,
            '<strong class="d-inline-block fs-5 fw-bold mb-3 text-dark">AI Career Skill-Gap Assistant</strong>',
            html=True,
        )
        self.assertContains(response, 'See Your Skill Gaps in Just Three Steps. Know What to Do Next.')
        self.assertContains(
            response,
            '<h1 id="hero-heading" class="display-5 fw-bold mb-3 fitgap-blue-emphasis" style="color: #1D63ED;">See Your Skill Gaps in Just Three Steps. Know What to Do Next.</h1>',
            html=True,
        )
        self.assertContains(
            response,
            'Not sure how far you are from your target role or what to learn next? Upload your CV and a job description to uncover your skill gaps, verify the evidence, and',
        )
        self.assertContains(
            response,
            '<strong class="fitgap-blue-emphasis fw-bold" style="color: #1D63ED;">build the right skills faster to move closer to the job you want.</strong>',
            html=True,
        )
        self.assertContains(response, 'Language:')
        self.assertContains(response, '<strong aria-current="page" class="text-dark">English</strong>', html=True)
        self._assert_guest_drawer(response)
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">Step 1 · Upload or paste your CV</h3>',
            html=True,
        )
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">Step 2 · Add your target job description</h3>',
            html=True,
        )
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">Step 3 · Choose your language and view your results</h3>',
            html=True,
        )
        self.assertContains(response, 'font-size: clamp(1.75rem, 4vw, 2.5rem);')
        self.assertContains(response, 'Upload CV')
        self.assertContains(response, 'Upload Job Description')
        self.assertContains(response, 'Supported formats: PDF, DOCX and TXT')
        self.assertContains(response, 'The extracted text can be reviewed and edited before analysis.')
        self.assertContains(response, 'Choose file')
        self.assertContains(response, 'No file selected')
        self.assertContains(response, 'View analysis results')
        self.assertNotContains(response, 'View Prototype Results')
        self.assertNotContains(response, 'prototype result')
        self.assertContains(response, 'href="/analyse/?lang=zh"')

    def test_chinese_input_page(self):
        response = self.client.get('/analyse/?lang=zh')

        self.assertContains(response, '简历和职位描述输入')
        self.assertContains(response, '界面和输出语言')
        self.assertContains(response, '简体中文界面和输出')
        self.assertContains(response, 'AI 求职技能差距助手')
        self.assertContains(
            response,
            '<strong class="d-inline-block fs-5 fw-bold mb-3 text-dark">AI 求职技能差距助手</strong>',
            html=True,
        )
        self.assertContains(response, '看清技能差距，仅需三步，知道下一步怎么做。')
        self.assertContains(
            response,
            '<h1 id="hero-heading" class="display-5 fw-bold mb-3 fitgap-blue-emphasis" style="color: #1D63ED;">看清技能差距，仅需三步，知道下一步怎么做。</h1>',
            html=True,
        )
        self.assertContains(response, '不知道自己离目标岗位还有多远，也不知道下一步该学什么？上传简历和职位描述，快速识别技能差距、核实判断依据，')
        self.assertContains(
            response,
            '<strong class="fitgap-blue-emphasis fw-bold" style="color: #1D63ED;">更高效地补齐关键技能，向理想岗位更进一步。</strong>',
            html=True,
        )
        self.assertContains(response, '语言：')
        self.assertContains(response, '<strong aria-current="page" class="text-dark">简体中文</strong>', html=True)
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">第一步 · 上传或粘贴你的简历</h3>',
            html=True,
        )
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">第二步 · 输入你的目标职位描述</h3>',
            html=True,
        )
        self.assertContains(
            response,
            '<h3 class="workflow-step-heading fw-bold mb-3">第三步 · 选择界面与输出语言，然后查看分析结果</h3>',
            html=True,
        )
        self.assertContains(response, 'color: #1D63ED;')
        self.assertContains(response, '上传简历')
        self.assertContains(response, '上传职位描述')
        self.assertContains(response, '支持格式：PDF、DOCX 和 TXT')
        self.assertContains(response, '分析前可以检查和修改提取的文本。')
        self.assertContains(response, '选择文件')
        self.assertContains(response, '未选择文件')
        self.assertContains(response, '查看分析结果')
        self.assertNotContains(response, '查看原型结果')
        self.assertContains(response, 'href="/analyse/?lang=en"')

    def test_fitgap_brand_logo_renders_from_static_asset(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertContains(response, 'FitGap')
        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')
        self.assertContains(response, 'alt="FitGap - AI Skill-Gap Analysis"')
        self.assertContains(response, 'aria-label="FitGap"')

    def test_results_page_renders_fitgap_logo_and_state_preserving_language_controls(self):
        response = self._results_response('en')

        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')
        self.assertContains(response, 'alt="FitGap - AI Skill-Gap Analysis"')
        self.assertContains(response, 'aria-label="FitGap"')
        self._assert_guest_drawer(response)
        self.assertContains(response, 'action="/results/full-analysis/?lang=en"')
        self.assertContains(response, 'action="/results/full-analysis/?lang=zh"')
        self.assertContains(response, 'name="analysis_payload"')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_results_page_renders_fitgap_logo_and_state_preserving_language_controls(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        results_response = self._results_response('en')
        response = self._post_ai_prioritisation(results_response, 'en')

        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')
        self.assertContains(response, 'alt="FitGap - AI Skill-Gap Analysis"')
        self.assertContains(response, 'aria-label="FitGap"')
        self._assert_guest_drawer(response)
        self.assertContains(response, 'action="/results/ai-results/?lang=en"')
        self.assertContains(response, 'action="/results/ai-results/?lang=zh"')
        self.assertContains(response, 'name="analysis_payload"')

    def test_input_template_loads_static_template_tag(self):
        template_source = Path('analysis/templates/analysis/input.html').read_text()

        self.assertIn('{% load static %}', template_source)
        self.assertIn("{% static 'analysis/fitgap-logo.svg' %}", template_source)

    def test_fitgap_svg_static_asset_is_discoverable(self):
        asset_path = finders.find('analysis/fitgap-logo.svg')

        self.assertIsNotNone(asset_path)
        self.assertTrue(asset_path.endswith('analysis/static/analysis/fitgap-logo.svg'))
        content = Path(asset_path).read_text()
        self.assertIn('<title id="fitgap-logo-title">FitGap</title>', content)

    def test_persistence_iteration_adds_only_analysis_record_migration_and_model(self):
        migration_files = sorted(Path('analysis/migrations').glob('*.py'))
        model_source = Path('analysis/models.py').read_text()

        self.assertEqual(
            [path.name for path in migration_files],
            ['0001_initial.py', '0002_analysisrecord_display_name.py', '__init__.py'],
        )
        self.assertIn('class AnalysisRecord', model_source)
        self.assertNotIn('SavedRoadmap', model_source)
        self.assertNotIn('SkillProgress', model_source)

    def test_textareas_still_render_on_input_page(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertContains(response, 'name="cv_text"')
        self.assertContains(response, 'name="job_description_text"')

    def test_header_has_no_fake_navigation_links(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertNotContains(response, 'Features')
        self.assertNotContains(response, 'Pricing')
        self.assertNotContains(response, 'Products')
        self.assertNotContains(response, 'About')
        self.assertNotContains(response, 'Login')
        self.assertNotContains(response, 'Sign up')

    def test_native_file_inputs_still_exist_and_are_visually_hidden(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertContains(response, 'type="file"', count=2)
        self.assertContains(response, 'name="cv_file"')
        self.assertContains(response, 'name="job_description_file"')
        self.assertContains(response, 'class="visually-hidden document-upload-input"', count=2)

    def test_accepted_file_extensions_remain_unchanged(self):
        response = self.client.get('/analyse/?lang=en')
        accept_value = '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain'

        self.assertContains(response, f'accept="{accept_value}"', count=2)

    def test_cv_and_job_description_custom_controls_have_distinct_identifiers(self):
        response = self.client.get('/analyse/?lang=en')

        self.assertContains(response, 'id="id_cv_file_filename"')
        self.assertContains(response, 'id="id_job_description_file_filename"')
        self.assertContains(response, 'data-file-input="id_cv_file"')
        self.assertContains(response, 'data-file-input="id_job_description_file"')

    def test_existing_analysis_workflow_remains_intact_after_hero_addition(self):
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python SQL Django',
            'output_language': 'en',
        })

        self.assertContains(response, 'Analysis Results')
        self.assertContains(response, '67%')
        self.assertContains(response, 'Complete a beginner Django tutorial and build a small CRUD web application.')

    def test_ai_section_and_english_button_render_on_results_page(self):
        response = self._results_response('en')

        self.assertContains(response, 'AI Recommended Next Steps')
        self.assertContains(
            response,
            'Use AI to prioritise your verified skill gaps based on the job requirements and supporting evidence.',
        )
        self.assertContains(response, 'Focus on the skill gaps that matter most and decide what to work on first.')
        self.assertContains(response, '✨ Prioritise My Skill Gaps with AI →')
        self.assertContains(response, 'background: #F4F7FF; border: 1px solid #D7E3FF;')
        self.assertContains(response, 'color: #1D63ED;')
        self.assertContains(response, 'action="/results/ai-prioritise/?lang=en"')

    def test_chinese_ai_button_renders_on_results_page(self):
        response = self._results_response('zh')

        self.assertContains(response, 'AI 推荐的下一步')
        self.assertContains(response, '找出最值得优先补齐的技能，明确下一步重点。')
        self.assertContains(response, '✨ AI 帮我确定优先级 →')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_results_page_english_to_chinese_language_switch_preserves_state(self, mock_prioritise):
        response = self._results_response('en')
        switched_response = self._switch_full_analysis_language(response, 'zh')

        mock_prioritise.assert_not_called()
        self.assertTemplateUsed(switched_response, 'analysis/results.html')
        self.assertContains(switched_response, '分析结果')
        self.assertContains(switched_response, '匹配技能')
        self.assertContains(switched_response, '缺失技能')
        self.assertContains(switched_response, 'Django')
        self.assertContains(switched_response, 'REST APIs')
        self.assertContains(switched_response, '40%')
        self.assertContains(switched_response, 'action="/results/full-analysis/?lang=en"')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_results_page_chinese_to_english_language_switch_preserves_state(self, mock_prioritise):
        response = self._results_response('zh')
        switched_response = self._switch_full_analysis_language(response, 'en')

        mock_prioritise.assert_not_called()
        self.assertTemplateUsed(switched_response, 'analysis/results.html')
        self.assertContains(switched_response, 'Analysis Results')
        self.assertContains(switched_response, 'Matched Skills')
        self.assertContains(switched_response, 'Missing Skills')
        self.assertContains(switched_response, 'Django')
        self.assertContains(switched_response, 'REST APIs')
        self.assertContains(switched_response, '40%')

    def test_results_page_language_switch_does_not_rerun_deterministic_analysis(self):
        response = self._results_response('en')

        with patch('analysis.views.extract_skills') as mock_extract_skills:
            switched_response = self._switch_full_analysis_language(response, 'zh')

        mock_extract_skills.assert_not_called()
        self.assertContains(switched_response, '分析结果')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_api_is_not_called_when_normal_results_page_first_loads(self, mock_prioritise):
        self._results_response('en')

        mock_prioritise.assert_not_called()

    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_api_is_called_only_after_dedicated_post(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is required for backend work.'},
        ]
        results_response = self._results_response('en')
        response = self._post_ai_prioritisation(results_response, 'en')

        mock_prioritise.assert_called_once()
        self.assertContains(response, 'Django is required for backend work.')
        self.assertTemplateUsed(response, 'analysis/ai_results.html')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_verified_missing_skills_are_passed_to_ai_service(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        results_response = self._results_response('en')

        self._post_ai_prioritisation(results_response, 'en')

        missing_skill_details = mock_prioritise.call_args.args[0]
        self.assertEqual([item['skill'] for item in missing_skill_details], ['Django', 'REST APIs', 'JavaScript'])
        self.assertEqual(missing_skill_details[0]['cv_evidence'], [])
        self.assertIn('Django', missing_skill_details[0]['jd_evidence'][0]['excerpt'])

    @patch('analysis.views.prioritise_skill_gaps')
    def test_successful_structured_ai_result_displays_correctly(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required for backend work.'},
            {'skill': 'REST APIs', 'priority': 'medium', 'reason': 'REST APIs support the service responsibilities.'},
        ]
        results_response = self._results_response('en')
        response = self._post_ai_prioritisation(results_response, 'en')

        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'HIGH PRIORITY')
        self.assertContains(response, 'MEDIUM PRIORITY')
        self.assertContains(response, 'Why this is a priority')
        self.assertContains(response, '1 · Django')
        self.assertContains(response, '2 · REST APIs')
        self.assertContains(response, 'Django is explicitly required for backend work.')
        self.assertContains(response, 'REST APIs support the service responsibilities.')
        self.assertContains(response, '← Back to Full Analysis')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_successful_ai_result_is_not_rendered_inline_on_results_page(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required for backend work.'},
        ]
        results_response = self._results_response('en')
        response = self._post_ai_prioritisation(results_response, 'en')

        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertNotContains(results_response, 'Django is explicitly required for backend work.')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_chinese_ai_results_page_renders(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        results_response = self._results_response('zh')
        response = self._post_ai_prioritisation(results_response, 'zh')

        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'AI 推荐的下一步')
        self.assertContains(response, '基于已验证的技能差距和目标职位要求，AI 已为你识别最值得优先处理的技能。')
        self.assertContains(response, '高优先级')
        self.assertContains(response, '为什么这是优先项')
        self.assertContains(response, '← 返回完整分析结果')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_results_page_displays_registration_gate_for_learning_roadmap(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        response = self._post_ai_prioritisation(self._results_response('en'), 'en')

        mock_roadmap.assert_not_called()
        self.assertContains(response, 'Turn Your Priorities into Action')
        self.assertContains(
            response,
            'You&#x27;ve identified your highest-priority skill gaps. Create a free FitGap account to unlock your personalised learning roadmap, save this analysis, and return to it later.',
            html=False,
        )
        self.assertContains(response, 'ACCOUNT ACCESS REQUIRED')
        self.assertContains(response, 'Get a personalised learning roadmap')
        self.assertContains(response, 'See exactly what to learn and in what order')
        self.assertContains(response, 'Create Free Account &amp; Build My Roadmap →', html=False)
        self.assertContains(response, 'Already have an account? Sign in')
        self.assertContains(response, 'No payment required.')
        self.assertContains(response, 'action="/account/roadmap-continuity/?lang=en"')
        self.assertContains(response, 'name="target" value="register"')
        self.assertContains(response, 'name="target" value="login"')
        self.assertContains(response, 'name="analysis_payload"')
        self.assertNotContains(response, 'action="/results/ai-learning-roadmap/?lang=en"')
        self.assertNotContains(response, '✨ Build My AI Learning Roadmap →')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_chinese_learning_roadmap_cta_renders(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        response = self._post_ai_prioritisation(self._results_response('zh'), 'zh')

        self.assertContains(response, '把优先级变成具体行动')
        self.assertContains(response, '需要账号权限')
        self.assertContains(response, '你已经找到了最值得优先补齐的技能。创建免费 FitGap 账号，即可解锁个性化 AI 学习路线，保存本次分析，并在之后随时回来继续查看。')
        self.assertContains(response, '获得个性化 AI 学习路线')
        self.assertContains(response, '免费注册并生成学习路线 →')
        self.assertContains(response, '已有账号？登录')
        self.assertContains(response, '无需付费。')
        self.assertContains(response, 'action="/account/roadmap-continuity/?lang=zh"')
        self.assertContains(response, 'name="target" value="register"')
        self.assertContains(response, 'name="target" value="login"')
        self.assertNotContains(response, 'action="/results/ai-learning-roadmap/?lang=zh"')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_following_roadmap_account_gate_does_not_call_roadmap_service(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        response = self._post_ai_prioritisation(self._results_response('en'), 'en')

        self.assertContains(response, 'action="/account/roadmap-continuity/?lang=en"')
        account_response = self._post_roadmap_auth_start(response, 'en', 'register')

        mock_roadmap.assert_not_called()
        self.assertEqual(account_response.status_code, 302)
        self.assertEqual(account_response['Location'], '/account/register/?lang=en&intent=roadmap')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_roadmap_account_action_stores_temporary_continuity_state(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        response = self._post_roadmap_auth_start(ai_response, 'en', 'register')
        continuity = self.client.session.get('pending_roadmap_continuity')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/account/register/?lang=en&intent=roadmap')
        self.assertIsInstance(continuity, dict)
        self.assertEqual(continuity['language'], 'en')
        self.assertEqual(continuity['analysis_payload'], ai_response.context['analysis_payload'])
        self.assertNotIn('cv_text', response['Location'])
        self.assertNotIn('job_description_text', response['Location'])
        self.assertNotIn('Python SQL Git', response['Location'])

    @patch('analysis.views.prioritise_skill_gaps')
    def test_continuity_state_is_session_scoped(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'register')
        other_client = Client()

        self.assertIn('pending_roadmap_continuity', self.client.session)
        self.assertNotIn('pending_roadmap_continuity', other_client.session)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_login_with_roadmap_intent_restores_authenticated_page_three_without_gemini(self, mock_prioritise, mock_roadmap):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django original priority.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'login')
        mock_prioritise.reset_mock()
        mock_roadmap.reset_mock()
        response = self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        })

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'Django original priority.')
        self.assertContains(response, '✨ Build My AI Learning Roadmap →')
        self.assertNotContains(response, 'ACCOUNT ACCESS REQUIRED')
        self.assertContains(response, 'Signed in successfully. Continue with your learning roadmap.')
        self.assertNotIn('pending_roadmap_continuity', self.client.session)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_registration_with_roadmap_intent_restores_authenticated_page_three_without_gemini(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'REST APIs', 'priority': 'medium', 'reason': 'REST APIs original priority.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'register')
        mock_prioritise.reset_mock()
        mock_roadmap.reset_mock()
        response = self.client.post('/account/register/?lang=en&intent=roadmap', data={
            'register-email': 'newstudent@example.com',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'VeryStrongPass123!',
        })

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'REST APIs original priority.')
        self.assertContains(response, '✨ Build My AI Learning Roadmap →')
        self.assertNotContains(response, 'ACCOUNT ACCESS REQUIRED')
        self.assertEqual(get_user_model().objects.count(), 1)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_chinese_continuity_preserves_chinese_page_three(self, mock_prioritise):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是原来的优先级。'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('zh'), 'zh')
        self._post_roadmap_auth_start(ai_response, 'zh', 'login')
        mock_prioritise.reset_mock()
        response = self.client.post('/account/login/?lang=zh&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        })

        mock_prioritise.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'AI 推荐的下一步')
        self.assertContains(response, 'Django 是原来的优先级。')
        self.assertContains(response, '✨ 生成我的 AI 学习路线 →')
        self.assertContains(response, '登录成功。继续生成你的学习路线。')

    def test_missing_continuity_safely_falls_back_to_new_analysis(self):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        response = self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        }, follow=True)

        self.assertRedirects(response, '/analyse/?lang=en')
        self.assertContains(response, 'Your previous analysis could not be restored. Please start a new analysis.')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_malformed_continuity_safely_falls_back_without_gemini(self, mock_prioritise, mock_roadmap):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        session = self.client.session
        session['pending_roadmap_continuity'] = {'analysis_payload': 'not-a-valid-signed-payload', 'language': 'en'}
        session.save()
        response = self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        }, follow=True)

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertRedirects(response, '/analyse/?lang=en')
        self.assertContains(response, 'Your previous analysis could not be restored. Please start a new analysis.')
        self.assertNotIn('pending_roadmap_continuity', self.client.session)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_start_new_analysis_clears_pending_continuity(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'register')

        self.assertIn('pending_roadmap_continuity', self.client.session)
        self.client.get('/analyse/?lang=en')
        self.assertNotIn('pending_roadmap_continuity', self.client.session)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_logout_clears_pending_continuity(self, mock_prioritise):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        self.client.logout()
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'register')
        self._login_user(email='other@example.com')

        self.client.post('/account/?lang=en', data={'account_action': 'logout'})
        self.assertNotIn('pending_roadmap_continuity', self.client.session)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_authenticated_page_two_creates_analysis_record(self, mock_prioritise, mock_roadmap):
        self._login_user()
        response = self._results_response('en')
        record = AnalysisRecord.objects.get()

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/results.html')
        self.assertEqual(record.user.email, 'student@example.com')
        self.assertEqual(record.status, AnalysisRecord.STATUS_ANALYSIS_COMPLETED)
        self.assertEqual(record.analysis_snapshot['matched_skills'], ['Python', 'SQL'])
        self.assertEqual(record.analysis_snapshot['missing_skills'], ['Django', 'REST APIs', 'JavaScript'])
        self.assertEqual(self.client.session['current_analysis_record_id'], record.id)

    def test_guest_page_two_does_not_create_analysis_record(self):
        self._results_response('en')

        self.assertEqual(AnalysisRecord.objects.count(), 0)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_authenticated_page_three_updates_same_analysis_record(self, mock_prioritise):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        results_response = self._results_response('en')
        record_id = AnalysisRecord.objects.get().id
        response = self._post_ai_prioritisation(results_response, 'en')
        record = AnalysisRecord.objects.get()

        mock_prioritise.assert_called_once()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertEqual(record.id, record_id)
        self.assertEqual(AnalysisRecord.objects.count(), 1)
        self.assertEqual(record.status, AnalysisRecord.STATUS_PRIORITIES_COMPLETED)
        self.assertEqual(record.priority_snapshot['status'], 'success')
        self.assertEqual(record.priority_snapshot['priorities'][0]['skill'], 'Django')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_authenticated_page_four_updates_same_analysis_record(self, mock_prioritise, mock_roadmap):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        record_id = AnalysisRecord.objects.get().id
        response = self._post_learning_roadmap(ai_response, 'en')
        record = AnalysisRecord.objects.get()

        mock_roadmap.assert_called_once()
        self.assertTemplateUsed(response, 'analysis/learning_roadmap.html')
        self.assertEqual(record.id, record_id)
        self.assertEqual(AnalysisRecord.objects.count(), 1)
        self.assertEqual(record.status, AnalysisRecord.STATUS_ROADMAP_COMPLETED)
        self.assertEqual(record.roadmap_snapshot['skills'][0]['skill'], 'Django')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_one_authenticated_journey_creates_only_one_record(self, mock_prioritise):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._switch_ai_results_language(response, 'zh')

        self.assertEqual(AnalysisRecord.objects.count(), 1)

    def test_start_new_analysis_keeps_old_record_and_clears_active_pointer(self):
        self._login_user()
        self._results_response('en')
        old_record = AnalysisRecord.objects.get()

        self.client.get('/analyse/?lang=en')

        self.assertEqual(AnalysisRecord.objects.count(), 1)
        self.assertEqual(AnalysisRecord.objects.get(), old_record)
        self.assertNotIn('current_analysis_record_id', self.client.session)

    def test_second_authenticated_journey_uses_new_record(self):
        self._login_user()
        self._results_response('en', cv_text='Python', job_description_text='Python Django')
        first_record = AnalysisRecord.objects.get()
        self.client.get('/analyse/?lang=en')
        self._results_response('en', cv_text='SQL', job_description_text='SQL REST APIs')

        self.assertEqual(AnalysisRecord.objects.count(), 2)
        self.assertNotEqual(self.client.session['current_analysis_record_id'], first_record.id)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_guest_page_three_does_not_create_persistent_record_before_auth(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]

        self._post_ai_prioritisation(self._results_response('en'), 'en')

        self.assertEqual(AnalysisRecord.objects.count(), 0)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_guest_login_continuity_creates_one_priorities_record_without_gemini(self, mock_prioritise, mock_roadmap):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django original priority.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'login')
        mock_prioritise.reset_mock()
        response = self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        })
        record = AnalysisRecord.objects.get()

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertEqual(record.status, AnalysisRecord.STATUS_PRIORITIES_COMPLETED)
        self.assertEqual(record.priority_snapshot['priorities'][0]['reason'], 'Django original priority.')
        self.assertEqual(self.client.session['current_analysis_record_id'], record.id)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_guest_register_continuity_creates_one_priorities_record_without_gemini(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'REST APIs', 'priority': 'medium', 'reason': 'REST APIs original priority.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'register')
        mock_prioritise.reset_mock()
        response = self.client.post('/account/register/?lang=en&intent=roadmap', data={
            'register-email': 'newstudent@example.com',
            'register-password': 'VeryStrongPass123!',
            'register-confirm_password': 'VeryStrongPass123!',
        })
        record = AnalysisRecord.objects.get()

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertEqual(AnalysisRecord.objects.count(), 1)
        self.assertEqual(record.status, AnalysisRecord.STATUS_PRIORITIES_COMPLETED)
        self.assertEqual(record.priority_snapshot['priorities'][0]['skill'], 'REST APIs')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_continuity_refresh_or_retry_does_not_duplicate_record(self, mock_prioritise):
        self._create_user(email='student@example.com', password='VeryStrongPass123!')
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django original priority.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._post_roadmap_auth_start(ai_response, 'en', 'login')
        self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        })
        self.client.post('/account/login/?lang=en&intent=roadmap', data={
            'login-email': 'student@example.com',
            'login-password': 'VeryStrongPass123!',
        })

        self.assertEqual(AnalysisRecord.objects.count(), 1)

    def test_history_requires_authentication(self):
        response = self.client.get('/account/analyses/?lang=zh')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/account/login/?lang=zh')

    def test_history_empty_state_renders_in_english_and_chinese(self):
        self._login_user()
        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')

        self.assertTemplateUsed(english_response, 'analysis/history.html')
        self.assertContains(english_response, 'My Analyses')
        self.assertContains(english_response, 'You have not saved any analyses yet.')
        self.assertContains(chinese_response, '我的分析')
        self.assertContains(chinese_response, '你还没有保存任何分析记录。')

    def test_history_displays_only_current_user_records_newest_first(self):
        user_a = self._create_user(email='a@example.com')
        user_b = self._create_user(email='b@example.com')
        older = AnalysisRecord.objects.create(user=user_a, target_role='Older A')
        newer = AnalysisRecord.objects.create(user=user_a, target_role='Newer A')
        AnalysisRecord.objects.create(user=user_b, target_role='Private B')
        self.client.login(username='a@example.com', password='StrongPass123!')
        response = self.client.get('/account/analyses/?lang=en')
        content = response.content.decode()

        self.assertContains(response, 'Older A')
        self.assertContains(response, 'Newer A')
        self.assertNotContains(response, 'Private B')
        self.assertLess(content.index('Newer A'), content.index('Older A'))
        self.assertIn(older, AnalysisRecord.objects.filter(user=user_a))
        self.assertIn(newer, AnalysisRecord.objects.filter(user=user_a))

    def test_authenticated_drawer_links_to_my_analyses_and_guest_drawer_does_not(self):
        guest_response = self.client.get('/?lang=en')
        self.assertNotContains(guest_response, 'My Analyses')
        self.assertNotContains(guest_response, 'href="/account/analyses/?lang=en"')

        self._login_user()
        auth_response = self.client.get('/?lang=en')
        self.assertContains(auth_response, 'My Analyses')
        self.assertContains(auth_response, 'href="/account/analyses/?lang=en"')

    def test_chinese_authenticated_drawer_links_to_my_analyses(self):
        self._login_user()
        response = self.client.get('/?lang=zh')

        self.assertContains(response, '我的分析')
        self.assertContains(response, 'href="/account/analyses/?lang=zh"')

    def test_session_record_pointer_validates_user_ownership(self):
        owner = self._create_user(email='owner@example.com')
        intruder = self._create_user(email='intruder@example.com')
        other_record = AnalysisRecord.objects.create(user=owner, target_role='Owner Record')
        self.client.login(username='intruder@example.com', password='StrongPass123!')
        session = self.client.session
        session['current_analysis_record_id'] = other_record.id
        session.save()
        self._results_response('en')

        self.assertEqual(AnalysisRecord.objects.filter(user=owner).count(), 1)
        self.assertEqual(AnalysisRecord.objects.filter(user=intruder).count(), 1)
        self.assertNotEqual(self.client.session['current_analysis_record_id'], other_record.id)

    def test_analysis_record_does_not_store_uploaded_file_or_raw_auth_data(self):
        self._login_user(password='VeryStrongPass123!')
        self._results_response(
            'en',
            cv_text='Python experience with private profile content.',
            job_description_text='Python Django role description.',
        )
        record = AnalysisRecord.objects.get()
        stored = str(record.analysis_snapshot)

        self.assertNotIn('cv.pdf', stored)
        self.assertNotIn('jd.docx', stored)
        self.assertNotIn('VeryStrongPass123!', stored)

    def test_analysis_snapshot_does_not_store_full_raw_cv_or_jd_text(self):
        self._login_user()
        raw_cv = 'Private CV introduction without recognised skill. Python.'
        raw_jd = 'Confidential job description paragraph without recognised skill. Django.'
        self._results_response('en', cv_text=raw_cv, job_description_text=raw_jd)
        record = AnalysisRecord.objects.get()
        stored = str(record.analysis_snapshot)

        self.assertNotIn(raw_cv, stored)
        self.assertNotIn(raw_jd, stored)
        self.assertIn('Python', record.analysis_snapshot['cv_skills'])
        self.assertIn('Django', record.analysis_snapshot['job_description_skills'])

    def test_expected_analysis_record_migration_exists(self):
        self.assertTrue(os.path.exists('analysis/migrations/0001_initial.py'))

    def test_no_unrelated_business_models_added(self):
        model_names = {model.__name__ for model in AnalysisRecord._meta.apps.get_app_config('analysis').get_models()}

        self.assertEqual(model_names, {'AnalysisRecord'})

    def test_analysis_record_has_optional_display_name(self):
        field = AnalysisRecord._meta.get_field('display_name')

        self.assertEqual(field.max_length, 160)
        self.assertTrue(field.blank)

    def test_existing_record_without_display_name_still_uses_target_role(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, target_role='Backend Developer')
        self.client.login(username='student@example.com', password='StrongPass123!')
        response = self.client.get('/account/analyses/?lang=en')

        self.assertContains(response, 'Backend Developer')

    def test_default_title_uses_current_language_when_target_role_is_system_fallback(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, target_role='未命名分析')
        AnalysisRecord.objects.create(user=user, target_role='Untitled Analysis')
        self.client.login(username='student@example.com', password='StrongPass123!')

        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')

        self.assertContains(english_response, 'Untitled Analysis', count=2)
        self.assertNotContains(english_response, '未命名分析')
        self.assertContains(chinese_response, '未命名分析', count=2)

    def test_switching_history_language_changes_only_default_fallback_title(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, target_role='Untitled Analysis')
        self.client.login(username='student@example.com', password='StrongPass123!')

        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')

        self.assertContains(english_response, 'Untitled Analysis')
        self.assertContains(chinese_response, '未命名分析')

    def test_user_defined_display_name_is_never_translated(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, target_role='Untitled Analysis', display_name='Shanghai AI PM')
        self.client.login(username='student@example.com', password='StrongPass123!')

        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')

        self.assertContains(english_response, 'Shanghai AI PM')
        self.assertContains(chinese_response, 'Shanghai AI PM')
        self.assertNotContains(chinese_response, '未命名分析')

    def test_meaningful_target_role_is_not_automatically_translated(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, target_role='Junior Data Analyst')
        self.client.login(username='student@example.com', password='StrongPass123!')

        response = self.client.get('/account/analyses/?lang=zh')

        self.assertContains(response, 'Junior Data Analyst')
        self.assertNotContains(response, '初级数据分析师')

    def test_status_values_remain_canonical_and_render_in_current_language(self):
        user = self._create_user()
        record = AnalysisRecord.objects.create(user=user, status=AnalysisRecord.STATUS_PRIORITIES_COMPLETED)
        self.client.login(username='student@example.com', password='StrongPass123!')

        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')
        record.refresh_from_db()

        self.assertEqual(record.status, 'priorities_completed')
        self.assertContains(english_response, 'AI priorities completed')
        self.assertContains(chinese_response, 'AI 优先级已完成')

    def test_history_language_metadata_is_human_readable(self):
        user = self._create_user()
        AnalysisRecord.objects.create(user=user, language='zh')
        self.client.login(username='student@example.com', password='StrongPass123!')

        english_response = self.client.get('/account/analyses/?lang=en')
        chinese_response = self.client.get('/account/analyses/?lang=zh')

        self.assertContains(english_response, 'Chinese')
        self.assertNotContains(english_response, '>ZH<', html=False)
        self.assertContains(chinese_response, '中文')

    def test_history_list_shows_management_actions(self):
        self._login_user()
        record = AnalysisRecord.objects.create(user=get_user_model().objects.get(email='student@example.com'), target_role='Backend Role')
        response = self.client.get('/account/analyses/?lang=en')

        self.assertContains(response, 'data-history-menu-button')
        self.assertContains(response, 'aria-label="More actions"')
        self.assertContains(response, 'Rename')
        self.assertContains(response, 'Delete')
        self.assertContains(response, f'/account/analyses/{record.id}/?lang=en')
        self.assertContains(response, f'/account/analyses/{record.id}/delete/?lang=en')
        self.assertNotContains(response, f'action="/account/analyses/{record.id}/rename/?lang=en"')
        self.assertNotContains(response, 'name="display_name"')
        self.assertNotContains(response, 'btn-outline-danger')
        self.assertNotContains(response, 'Share')
        self.assertNotContains(response, 'Archive')
        self.assertNotContains(response, 'Pin')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_history_list_triggers_zero_gemini_calls(self, mock_prioritise, mock_roadmap):
        self._login_user()
        AnalysisRecord.objects.create(user=get_user_model().objects.get(email='student@example.com'))

        self.client.get('/account/analyses/?lang=en')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()

    def test_owner_can_open_saved_record_detail(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            target_role='Backend Developer',
            analysis_snapshot={
                'match_score': 50,
                'match_score_explanation': '1 of 2 recognised job-description skills were found in the CV.',
                'matched_skills': ['Python'],
                'missing_skills': ['Django'],
            },
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        self.assertTemplateUsed(response, 'analysis/history_detail.html')
        self.assertContains(response, 'Backend Developer')
        self.assertContains(response, 'Saved Analysis')
        self.assertContains(response, '50%')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Django')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_history_detail_uses_database_snapshot_only(self, mock_prioritise, mock_roadmap):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            priority_snapshot={
                'status': 'success',
                'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Saved English priority.'}],
            },
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertContains(response, 'Saved English priority.')
        self.assertContains(response, 'HIGH PRIORITY')

    def test_user_b_cannot_open_user_a_record(self):
        user_a = self._create_user(email='a@example.com')
        self._create_user(email='b@example.com')
        record = AnalysisRecord.objects.create(user=user_a, target_role='Private A')
        self.client.login(username='b@example.com', password='StrongPass123!')
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, 'Private A', status_code=404)

    def test_analysis_only_record_shows_missing_priority_and_roadmap_messages(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            status=AnalysisRecord.STATUS_ANALYSIS_COMPLETED,
            analysis_snapshot={'match_score': 0, 'matched_skills': [], 'missing_skills': ['Django']},
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        self.assertContains(response, 'AI priorities were not generated for this analysis.')
        self.assertContains(response, 'A learning roadmap was not generated for this analysis.')

    def test_priorities_completed_record_shows_missing_roadmap_message(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            status=AnalysisRecord.STATUS_PRIORITIES_COMPLETED,
            priority_snapshot={
                'status': 'success',
                'priorities': [{'skill': 'REST APIs', 'priority': 'medium', 'reason': 'Saved reason.'}],
            },
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        self.assertContains(response, 'Saved reason.')
        self.assertContains(response, 'A learning roadmap was not generated for this analysis.')

    def test_roadmap_completed_record_displays_saved_roadmap(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            status=AnalysisRecord.STATUS_ROADMAP_COMPLETED,
            roadmap_snapshot=_sample_roadmap(['Django']),
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=en')

        self.assertContains(response, 'Saved Learning Roadmap')
        self.assertContains(response, 'Create one observable Django feature today.')
        self.assertContains(response, 'Django mini project with Git history and README')

    def test_detail_language_switch_preserves_same_record_without_retranslating_saved_ai_text(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(
            user=user,
            priority_snapshot={
                'status': 'success',
                'priorities': [{'skill': 'Django', 'priority': 'high', 'reason': 'Saved English priority only.'}],
            },
        )
        response = self.client.get(f'/account/analyses/{record.id}/?lang=zh')

        self.assertContains(response, '已保存的 AI 优先级建议')
        self.assertContains(response, 'Saved English priority only.')
        self.assertContains(response, f'href="/account/analyses/{record.id}/?lang=en"')

    def test_owner_can_rename_display_name_only(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        snapshot = {'matched_skills': ['Python']}
        record = AnalysisRecord.objects.create(user=user, target_role='Original Target', analysis_snapshot=snapshot)
        response = self.client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={
            'display_name': '  MSc Backend Plan  ',
        })
        record.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'/account/analyses/{record.id}/?lang=en')
        self.assertEqual(record.display_name, 'MSc Backend Plan')
        self.assertEqual(record.target_role, 'Original Target')
        self.assertEqual(record.analysis_snapshot, snapshot)

    def test_empty_and_overlong_rename_are_rejected(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user, target_role='Original Target')

        empty_response = self.client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={'display_name': '   '})
        long_response = self.client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={'display_name': 'x' * 161})
        record.refresh_from_db()

        self.assertEqual(empty_response.status_code, 400)
        self.assertContains(empty_response, 'Please enter an analysis name.', status_code=400)
        self.assertEqual(long_response.status_code, 400)
        self.assertContains(long_response, 'Analysis name must be 160 characters or fewer.', status_code=400)
        self.assertEqual(record.display_name, '')

    def test_user_b_cannot_rename_user_a_record(self):
        user_a = self._create_user(email='a@example.com')
        self._create_user(email='b@example.com')
        record = AnalysisRecord.objects.create(user=user_a, target_role='Private A')
        self.client.login(username='b@example.com', password='StrongPass123!')
        response = self.client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={'display_name': 'Hacked'})
        record.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(record.display_name, '')

    def test_rename_requires_post_and_csrf(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user)

        get_response = self.client.get(f'/account/analyses/{record.id}/rename/?lang=en')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username='student@example.com', password='StrongPass123!')
        csrf_response = csrf_client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={'display_name': 'Name'})

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(csrf_response.status_code, 403)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_rename_triggers_zero_gemini_calls(self, mock_prioritise, mock_roadmap):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user)

        self.client.post(f'/account/analyses/{record.id}/rename/?lang=en', data={'display_name': 'Saved Plan'})

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()

    def test_delete_confirmation_get_does_not_delete_record(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user, target_role='Delete Candidate')
        response = self.client.get(f'/account/analyses/{record.id}/delete/?lang=en')

        self.assertTemplateUsed(response, 'analysis/history_delete.html')
        self.assertContains(response, 'Delete this analysis?')
        self.assertEqual(AnalysisRecord.objects.count(), 1)

    def test_owner_can_delete_own_record_without_deleting_user_or_other_records(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user, target_role='Delete Me')
        other_record = AnalysisRecord.objects.create(user=user, target_role='Keep Me')
        response = self.client.post(f'/account/analyses/{record.id}/delete/?lang=en')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/account/analyses/?lang=en')
        self.assertFalse(AnalysisRecord.objects.filter(id=record.id).exists())
        self.assertTrue(AnalysisRecord.objects.filter(id=other_record.id).exists())
        self.assertTrue(get_user_model().objects.filter(email='student@example.com').exists())

    def test_user_b_cannot_delete_user_a_record(self):
        user_a = self._create_user(email='a@example.com')
        self._create_user(email='b@example.com')
        record = AnalysisRecord.objects.create(user=user_a, target_role='Private A')
        self.client.login(username='b@example.com', password='StrongPass123!')
        response = self.client.post(f'/account/analyses/{record.id}/delete/?lang=en')

        self.assertEqual(response.status_code, 404)
        self.assertTrue(AnalysisRecord.objects.filter(id=record.id).exists())

    def test_delete_actual_action_requires_post_and_csrf(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username='student@example.com', password='StrongPass123!')
        csrf_response = csrf_client.post(f'/account/analyses/{record.id}/delete/?lang=en')

        self.assertEqual(csrf_response.status_code, 403)
        self.assertTrue(AnalysisRecord.objects.filter(id=record.id).exists())

    def test_deleting_active_record_clears_current_analysis_pointer(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user)
        session = self.client.session
        session['current_analysis_record_id'] = record.id
        session.save()

        self.client.post(f'/account/analyses/{record.id}/delete/?lang=en')

        self.assertNotIn('current_analysis_record_id', self.client.session)

    def test_deleting_inactive_record_keeps_unrelated_active_pointer(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        active_record = AnalysisRecord.objects.create(user=user)
        inactive_record = AnalysisRecord.objects.create(user=user)
        session = self.client.session
        session['current_analysis_record_id'] = active_record.id
        session.save()

        self.client.post(f'/account/analyses/{inactive_record.id}/delete/?lang=en')

        self.assertEqual(self.client.session['current_analysis_record_id'], active_record.id)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_delete_triggers_zero_gemini_calls(self, mock_prioritise, mock_roadmap):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user)

        self.client.post(f'/account/analyses/{record.id}/delete/?lang=en')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()

    def test_chinese_history_management_ui_renders(self):
        self._login_user()
        user = get_user_model().objects.get(email='student@example.com')
        record = AnalysisRecord.objects.create(user=user, target_role='未命名分析')
        list_response = self.client.get('/account/analyses/?lang=zh')
        detail_response = self.client.get(f'/account/analyses/{record.id}/?lang=zh')
        delete_response = self.client.get(f'/account/analyses/{record.id}/delete/?lang=zh')

        self.assertContains(list_response, '打开')
        self.assertContains(list_response, '重命名')
        self.assertContains(list_response, '删除')
        self.assertContains(detail_response, '重命名分析')
        self.assertContains(detail_response, '这次分析尚未生成 AI 优先级建议。')
        self.assertContains(delete_response, '删除这条分析记录？')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_unauthenticated_direct_roadmap_post_is_blocked_before_gemini(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        response = self._post_learning_roadmap(ai_response, 'en')

        mock_roadmap.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/account/?lang=en&intent=roadmap')
        self.assertNotContains(response, 'My AI Learning Roadmap', status_code=302)

    @patch('analysis.views.prioritise_skill_gaps')
    def test_authenticated_page_three_renders_real_roadmap_cta(self, mock_prioritise):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        response = self._post_ai_prioritisation(self._results_response('en'), 'en')

        self.assertContains(response, '1 · Django')
        self.assertContains(response, 'Turn Your Priorities into Action')
        self.assertContains(
            response,
            'You&#x27;ve identified your highest-priority gaps. Turn them into a focused, personalised learning roadmap.',
            html=False,
        )
        self.assertContains(response, '✨ Build My AI Learning Roadmap →')
        self.assertContains(response, 'action="/results/ai-learning-roadmap/?lang=en"')
        self.assertNotContains(response, 'ACCOUNT ACCESS REQUIRED')
        self.assertNotContains(response, 'Create Free Account')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_authenticated_chinese_page_three_renders_real_roadmap_cta(self, mock_prioritise):
        self._login_user()
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        response = self._post_ai_prioritisation(self._results_response('zh'), 'zh')

        self.assertContains(response, '1 · Django')
        self.assertContains(response, '把优先级变成具体行动')
        self.assertContains(response, '你已经找到了最值得优先补齐的技能。现在把它们转化为聚焦、个性化的学习路线。')
        self.assertContains(response, '✨ 生成我的 AI 学习路线 →')
        self.assertContains(response, 'action="/results/ai-learning-roadmap/?lang=zh"')
        self.assertNotContains(response, '需要账号权限')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_learning_roadmap_endpoint_invokes_service_after_explicit_post(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()
        response = self._post_learning_roadmap(ai_response, 'en')

        mock_roadmap.assert_called_once()
        self.assertTemplateUsed(response, 'analysis/learning_roadmap.html')
        self.assertContains(response, 'My AI Learning Roadmap')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_learning_roadmap_call_receives_minimised_state(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()

        self._post_learning_roadmap(ai_response, 'en')

        roadmap_results = mock_roadmap.call_args.args[0]
        self.assertEqual(roadmap_results['cv_skills'], ['Python', 'SQL', 'Git'])
        self.assertEqual(roadmap_results['ai_prioritisation']['priorities'][0]['skill'], 'Django')
        self.assertIn('missing_skill_details', roadmap_results)
        self.assertNotIn('cv_text', roadmap_results)
        self.assertNotIn('job_description_text', roadmap_results)

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_valid_learning_roadmap_renders_page_four(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
            {'skill': 'REST APIs', 'priority': 'medium', 'reason': 'REST APIs support service work.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django', 'REST APIs'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()
        response = self._post_learning_roadmap(ai_response, 'en')

        self.assertTemplateUsed(response, 'analysis/learning_roadmap.html')
        self._assert_authenticated_drawer(response)
        self.assertContains(response, 'My AI Learning Roadmap')
        self.assertContains(response, 'MINIMUM VIABLE LEARNING PATH')
        self.assertContains(response, 'IMMEDIATE NEXT ACTION')
        self.assertContains(response, 'Create one observable Django feature today.')
        self.assertContains(response, 'CORE GAP-CLOSING EFFORT')
        self.assertContains(response, '12-18 hours')
        self.assertContains(response, 'SUGGESTED PACE')
        self.assertContains(response, 'About 1-2 weeks at 2 hours per day.')
        self.assertContains(response, 'CAN WAIT / OPTIONAL')
        self.assertContains(response, 'Machine Learning can wait')
        self.assertContains(response, 'ROADMAP STRATEGY')
        self.assertContains(response, '1. Django')
        self.assertContains(response, '6-8 hours')
        self.assertContains(response, 'Target')
        self.assertContains(response, 'Build and explain a practical Django feature')
        self.assertContains(response, 'Evidence target')
        self.assertContains(response, 'Django mini project with Git history and README')
        self.assertContains(response, 'Good enough when')
        self.assertContains(response, 'Core steps')
        self.assertContains(response, 'Build a Django mini feature')
        self.assertContains(response, '4-6 hours')
        self.assertContains(response, '<details', html=False)
        self.assertContains(response, '<summary class="fw-semibold" style="color: #1D63ED;">View detailed roadmap</summary>', html=False)
        self.assertContains(response, 'Proof details')
        self.assertContains(response, 'Minimum features')
        self.assertContains(response, 'working feature')
        self.assertContains(response, 'GitLab repository')
        self.assertContains(response, 'Interview talking points')
        self.assertContains(response, 'Design decision')
        self.assertContains(response, 'CV usage guidance')
        self.assertContains(response, 'future Django project evidence')
        self.assertContains(response, 'src="/static/analysis/fitgap-logo.svg"')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_chinese_learning_roadmap_page_labels_render(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('zh'), 'zh')
        self._login_user()
        response = self._post_learning_roadmap(ai_response, 'zh')

        self.assertContains(response, '我的 AI 学习路线')
        self.assertContains(response, '最小可行学习路径')
        self.assertContains(response, '立即开始')
        self.assertContains(response, '核心补齐投入')
        self.assertContains(response, '建议节奏')
        self.assertContains(response, '可以稍后补充')
        self.assertContains(response, '路线策略')
        self.assertContains(response, '证据目标')
        self.assertContains(response, '达到可用水平的标准')
        self.assertContains(response, '证明细节')
        self.assertContains(response, '面试讨论要点')
        self.assertContains(response, '简历使用建议')
        self.assertContains(response, '← 返回 AI 优先级')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_learning_roadmap_language_switch_preserves_roadmap_without_ai_calls(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()
        roadmap_response = self._post_learning_roadmap(ai_response, 'en')
        mock_prioritise.reset_mock()
        mock_roadmap.reset_mock()

        with patch('analysis.views.extract_skills') as mock_extract_skills:
            switched_response = self._switch_learning_roadmap_language(roadmap_response, 'zh')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        mock_extract_skills.assert_not_called()
        self.assertTemplateUsed(switched_response, 'analysis/learning_roadmap.html')
        self.assertContains(switched_response, '我的 AI 学习路线')
        self.assertContains(switched_response, 'Django mini project')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_learning_roadmap_back_to_ai_priorities_preserves_priorities_without_ai_call(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.return_value = _sample_roadmap(['Django'])
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()
        roadmap_response = self._post_learning_roadmap(ai_response, 'en')
        mock_prioritise.reset_mock()
        mock_roadmap.reset_mock()
        response = self.client.post('/results/ai-results/?lang=en', data={
            'analysis_payload': roadmap_response.context['analysis_payload'],
            'output_language': 'en',
        })

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, '1 · Django')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_learning_roadmap_failure_stays_on_page_three_with_priorities(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        mock_roadmap.side_effect = LearningRoadmapUnavailable
        ai_response = self._post_ai_prioritisation(self._results_response('en'), 'en')
        self._login_user()
        response = self._post_learning_roadmap(ai_response, 'en')

        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, '1 · Django')
        self.assertContains(
            response,
            'AI learning roadmap is temporarily unavailable. Your prioritised skill gaps are still available above, and you can try generating the roadmap again.',
        )

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_chinese_learning_roadmap_failure_message_renders(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        mock_roadmap.side_effect = LearningRoadmapUnavailable
        ai_response = self._post_ai_prioritisation(self._results_response('zh'), 'zh')
        self._login_user()
        response = self._post_learning_roadmap(ai_response, 'zh')

        self.assertContains(response, 'AI 学习路线暂时不可用。你仍可查看上方已经生成的技能优先级，并可以稍后再次尝试生成学习路线。')

    @patch('analysis.views.generate_learning_roadmap')
    def test_roadmap_endpoint_skips_service_when_no_priorities_exist(self, mock_roadmap):
        results_response = self._results_response('en')
        self._login_user()
        response = self._post_learning_roadmap(results_response, 'en')

        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/ai_results.html')
        self.assertContains(response, 'No AI priority skills are available for roadmap generation.')

    @patch('analysis.views.generate_learning_roadmap')
    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_results_english_to_chinese_language_switch_preserves_priority_data(self, mock_prioritise, mock_roadmap):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required for backend work.'},
            {'skill': 'REST APIs', 'priority': 'medium', 'reason': 'REST APIs support service responsibilities.'},
        ]
        results_response = self._results_response('en')
        ai_response = self._post_ai_prioritisation(results_response, 'en')
        mock_prioritise.reset_mock()
        mock_roadmap.reset_mock()
        switched_response = self._switch_ai_results_language(ai_response, 'zh')

        mock_prioritise.assert_not_called()
        mock_roadmap.assert_not_called()
        self.assertTemplateUsed(switched_response, 'analysis/ai_results.html')
        self.assertContains(switched_response, 'AI 推荐的下一步')
        self.assertContains(switched_response, '基于已验证的技能差距和目标职位要求，AI 已为你识别最值得优先处理的技能。')
        self.assertContains(switched_response, '高优先级')
        self.assertContains(switched_response, '中优先级')
        self.assertContains(switched_response, '为什么这是优先项')
        self.assertContains(switched_response, '1 · Django')
        self.assertContains(switched_response, '2 · REST APIs')
        self.assertContains(switched_response, 'Django is explicitly required for backend work.')
        self.assertContains(switched_response, 'action="/account/roadmap-continuity/?lang=zh"')
        self.assertContains(switched_response, 'name="target" value="register"')
        self.assertContains(switched_response, 'name="target" value="login"')
        self.assertContains(switched_response, '← 返回完整分析结果')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_results_chinese_to_english_language_switch_preserves_priority_data(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django 是核心后端框架要求。'},
        ]
        results_response = self._results_response('zh')
        ai_response = self._post_ai_prioritisation(results_response, 'zh')
        mock_prioritise.reset_mock()
        switched_response = self._switch_ai_results_language(ai_response, 'en')

        mock_prioritise.assert_not_called()
        self.assertTemplateUsed(switched_response, 'analysis/ai_results.html')
        self.assertContains(switched_response, 'AI Recommended Next Steps')
        self.assertContains(
            switched_response,
            'Based on your verified skill gaps and target job requirements, AI has identified the skills you should prioritise first.',
        )
        self.assertContains(switched_response, 'HIGH PRIORITY')
        self.assertContains(switched_response, 'Why this is a priority')
        self.assertContains(switched_response, '1 · Django')
        self.assertContains(switched_response, 'Django 是核心后端框架要求。')
        self.assertContains(switched_response, '← Back to Full Analysis')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_ai_results_language_switch_does_not_rerun_deterministic_analysis(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        results_response = self._results_response('en')
        ai_response = self._post_ai_prioritisation(results_response, 'en')

        with patch('analysis.views.extract_skills') as mock_extract_skills:
            switched_response = self._switch_ai_results_language(ai_response, 'zh')

        mock_extract_skills.assert_not_called()
        self.assertContains(switched_response, 'AI 推荐的下一步')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_back_to_full_analysis_still_works_after_ai_language_switch(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required.'},
        ]
        results_response = self._results_response('en')
        ai_response = self._post_ai_prioritisation(results_response, 'en')
        switched_ai_response = self._switch_ai_results_language(ai_response, 'zh')
        response = self.client.post('/results/full-analysis/?lang=zh', data={
            'analysis_payload': switched_ai_response.context['analysis_payload'],
            'output_language': 'zh',
        })

        self.assertTemplateUsed(response, 'analysis/results.html')
        self.assertContains(response, '分析结果')
        self.assertContains(response, '匹配技能')
        self.assertContains(response, '缺失技能')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_back_navigation_returns_to_full_analysis_without_ai_call(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is explicitly required for backend work.'},
        ]
        results_response = self._results_response('en')
        ai_response = self._post_ai_prioritisation(results_response, 'en')
        mock_prioritise.reset_mock()
        response = self.client.post('/results/full-analysis/?lang=en', data={
            'analysis_payload': ai_response.context['analysis_payload'],
            'output_language': 'en',
        })

        mock_prioritise.assert_not_called()
        self.assertTemplateUsed(response, 'analysis/results.html')
        self.assertContains(response, 'Analysis Results')
        self.assertContains(response, 'Matched Skills')
        self.assertContains(response, 'Missing Skills')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_simulated_api_exception_triggers_english_fallback(self, mock_prioritise):
        mock_prioritise.side_effect = AIPrioritisationUnavailable
        results_response = self._results_response('en')
        response = self._post_ai_prioritisation(results_response, 'en')

        self.assertContains(
            response,
            'AI prioritisation is temporarily unavailable. You can still review your verified skill gaps and evidence above.',
        )
        self.assertContains(response, 'Matched Skills')
        self.assertContains(response, 'Missing Skills')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_simulated_api_exception_triggers_chinese_fallback(self, mock_prioritise):
        mock_prioritise.side_effect = AIPrioritisationUnavailable
        results_response = self._results_response('zh')
        response = self._post_ai_prioritisation(results_response, 'zh')

        self.assertContains(response, 'AI 优先级分析暂时不可用，你仍可查看上方已识别的技能差距和证据。')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_zero_missing_skills_does_not_call_ai_api(self, mock_prioritise):
        results_response = self._results_response(
            'en',
            cv_text='Python SQL Django',
            job_description_text='Python SQL Django',
        )
        response = self._post_ai_prioritisation(results_response, 'en')

        mock_prioritise.assert_not_called()
        self.assertContains(response, 'No missing skills were identified for AI prioritisation.')

    @patch('analysis.views.prioritise_skill_gaps')
    def test_one_or_two_missing_skills_are_handled(self, mock_prioritise):
        mock_prioritise.return_value = [
            {'skill': 'Django', 'priority': 'high', 'reason': 'Django is the only verified gap.'},
        ]
        results_response = self._results_response(
            'en',
            cv_text='Python SQL',
            job_description_text='Python SQL Django',
        )
        response = self._post_ai_prioritisation(results_response, 'en')

        mock_prioritise.assert_called_once()
        self.assertContains(response, 'Django is the only verified gap.')

    def test_english_results_page(self):
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })

        self.assertContains(response, 'Analysis Results')
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
        response = self.client.post('/analyse/?lang=en', data={
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
        response = self.client.post('/analyse/?lang=zh', data={
            'cv_text': 'Python SQL Git',
            'job_description_text': 'Python Django SQL',
            'output_language': 'zh',
        })

        self.assertContains(response, '分析结果')
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
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': '<script>alert(1)</script> Used GitLab safely.',
            'job_description_text': 'Git is required.',
            'output_language': 'en',
        })
        content = response.content.decode()

        self.assertIn('<mark>GitLab</mark>', content)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', content)
        self.assertNotIn('<script>alert(1)</script>', content)

    def test_english_no_missing_skills_recommendation_message(self):
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL Django',
            'job_description_text': 'Python Django SQL',
            'output_language': 'en',
        })

        self.assertContains(
            response,
            'No learning recommendations are needed because no recognised job-description skills are missing.',
        )

    def test_chinese_no_missing_skills_recommendation_message(self):
        response = self.client.post('/analyse/?lang=zh', data={
            'cv_text': 'Python SQL Django',
            'job_description_text': 'Python Django SQL',
            'output_language': 'zh',
        })

        self.assertContains(response, '没有需要生成的学习建议，因为未发现缺失的岗位技能。')

    def test_realistic_input_generates_rule_based_recommendations(self):
        response = self.client.post('/analyse/?lang=en', data={
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
        response = self.client.post('/analyse/?lang=en', data={
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
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'communication teamwork',
            'output_language': 'en',
        })

        self.assertContains(response, '0%')
        self.assertContains(response, 'No recognised job-description skills were found')

    def test_chinese_zero_job_description_skill_explanation(self):
        response = self.client.post('/analyse/?lang=zh', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'communication teamwork',
            'output_language': 'zh',
        })

        self.assertContains(response, '0%')
        self.assertContains(response, '岗位描述中未识别出技能')

    def test_language_preservation_after_post(self):
        response = self.client.post('/analyse/?lang=en', data={
            'cv_text': 'Python SQL',
            'job_description_text': 'Python Django',
            'output_language': 'zh',
        })

        self.assertContains(response, '分析结果')
        self.assertContains(response, 'href="/analyse/?lang=zh"')

    def test_chinese_required_field_validation_messages(self):
        response = self.client.post('/analyse/?lang=zh', data={
            'cv_text': '',
            'job_description_text': '',
            'output_language': 'zh',
        })

        self.assertContains(response, '请先粘贴简历文本再继续。')
        self.assertContains(response, '请先粘贴职位描述文本再继续。')
        self.assertContains(response, '简历和职位描述输入')

    def test_invalid_language_falls_back_to_english(self):
        response = self.client.get('/analyse/?lang=unsupported')

        self.assertContains(response, 'CV and Job Description Input')
        self.assertContains(response, 'View analysis results')

    def test_run_another_analysis_preserves_selected_language(self):
        response = self.client.post('/analyse/?lang=zh', data={
            'cv_text': 'Python',
            'job_description_text': 'Django',
            'output_language': 'zh',
        })

        self.assertContains(response, 'href="/analyse/?lang=zh"')
        self.assertContains(response, '再次分析')
