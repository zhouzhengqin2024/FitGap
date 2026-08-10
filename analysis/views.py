from django.core import signing
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .ai_prioritisation import AIPrioritisationUnavailable, prioritise_skill_gaps
from .document_extraction import DocumentExtractionError, extract_document_text
from .forms import AnalysisInputForm
from .services import (
    build_skill_evidence_details,
    calculate_match_score,
    compare_skills,
    extract_skills,
    generate_learning_recommendations,
)
from .translations import get_translations, normalise_language


def _get_selected_language(request):
    posted_language = request.POST.get('output_language')
    query_language = request.GET.get('lang')
    return normalise_language(posted_language or query_language)


def _build_base_results(output_language, form):
    language_labels = dict(form.fields['output_language'].choices)
    return {
        'output_language': language_labels.get(output_language, output_language),
    }


def _build_match_score_explanation(text, matched_skills, job_description_skills):
    job_description_skill_count = len({skill.lower() for skill in job_description_skills})

    if job_description_skill_count == 0:
        return text['match_score_zero_explanation']

    matched_skill_count = len(
        {skill.lower() for skill in matched_skills}.intersection(
            {skill.lower() for skill in job_description_skills}
        )
    )
    return text['match_score_explanation'].format(
        matched_count=matched_skill_count,
        job_description_count=job_description_skill_count,
    )


def _get_extraction_error_message(text, code):
    return text.get(f'{code}_error', text['extraction_failed_error'])


def _sign_results(results):
    return signing.dumps(results, compress=True)


def _render_results(request, language, results, text):
    return render(
        request,
        'analysis/results.html',
        {
            'analysis_payload': _sign_results(results),
            'language': language,
            'results': results,
            'text': text,
        },
    )


def _add_ai_priority_labels(priorities, text):
    for item in priorities:
        item['priority_label'] = text[f"ai_priority_{item['priority']}"]
    return priorities


def _build_ai_status(status, text, priorities=None):
    if status == 'success':
        return {
            'status': status,
            'priorities': priorities or [],
        }

    message_key = 'ai_no_missing_skills' if status == 'empty' else 'ai_unavailable'
    return {
        'status': status,
        'message': text[message_key],
        'priorities': [],
    }


@require_POST
def extract_document_text_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    uploaded_file = request.FILES.get('document')

    if not uploaded_file:
        return JsonResponse({
            'success': False,
            'error': text['upload_required'],
        }, status=400)

    try:
        extracted_text = extract_document_text(uploaded_file)
    except DocumentExtractionError as exc:
        return JsonResponse({
            'success': False,
            'error': _get_extraction_error_message(text, exc.code),
        }, status=400)

    return JsonResponse({
        'success': True,
        'text': extracted_text,
    })


def input_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    form = AnalysisInputForm(request.POST or None, language=language)

    if request.method == 'POST' and form.is_valid():
        cv_text = form.cleaned_data['cv_text']
        job_description_text = form.cleaned_data['job_description_text']
        language = form.cleaned_data['output_language']
        text = get_translations(language)
        results = _build_base_results(language, form)
        cv_skills = extract_skills(cv_text)
        job_description_skills = extract_skills(job_description_text)
        skill_comparison = compare_skills(cv_skills, job_description_skills)

        results['cv_skills'] = cv_skills
        results['job_description_skills'] = job_description_skills
        results.update(skill_comparison)
        results['match_score'] = calculate_match_score(
            results['matched_skills'],
            job_description_skills,
        )
        results['match_score_explanation'] = _build_match_score_explanation(
            text,
            results['matched_skills'],
            job_description_skills,
        )
        results['learning_recommendations'] = generate_learning_recommendations(
            results['missing_skills'],
            language,
        )
        results.update(build_skill_evidence_details(
            results['matched_skills'],
            results['missing_skills'],
            cv_text,
            job_description_text,
            language,
        ))

        return _render_results(request, language, results, text)

    return render(
        request,
        'analysis/input.html',
        {
            'form': form,
            'language': language,
            'text': text,
        },
    )


@require_POST
def ai_prioritise_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    try:
        results = signing.loads(request.POST.get('analysis_payload', ''), max_age=3600)
    except signing.BadSignature:
        results = {}

    missing_skill_details = results.get('missing_skill_details', [])

    if not missing_skill_details:
        results['ai_prioritisation'] = _build_ai_status('empty', text)
        return _render_results(request, language, results, text)

    try:
        priorities = prioritise_skill_gaps(missing_skill_details, language)
    except AIPrioritisationUnavailable:
        results['ai_prioritisation'] = _build_ai_status('fallback', text)
    else:
        results['ai_prioritisation'] = _build_ai_status(
            'success',
            text,
            _add_ai_priority_labels(priorities, text),
        )

    return _render_results(request, language, results, text)
