from django.shortcuts import render

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

        return render(
            request,
            'analysis/results.html',
            {
                'language': language,
                'results': results,
                'text': text,
            },
        )

    return render(
        request,
        'analysis/input.html',
        {
            'form': form,
            'language': language,
            'text': text,
        },
    )
