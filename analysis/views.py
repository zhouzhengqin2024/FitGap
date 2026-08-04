from django.shortcuts import render

from .forms import AnalysisInputForm
from .services import compare_skills, extract_skills
from .translations import get_translations, normalise_language


def _get_selected_language(request):
    posted_language = request.POST.get('output_language')
    query_language = request.GET.get('lang')
    return normalise_language(posted_language or query_language)


def _build_mock_results(output_language, form, text):
    language_labels = dict(form.fields['output_language'].choices)
    return {
        'match_score': 65,
        'learning_recommendations': [
            {
                'skill': 'Django',
                'recommendation': text['recommendation_django'],
            },
            {
                'skill': 'REST APIs',
                'recommendation': text['recommendation_rest_apis'],
            },
        ],
        'output_language': language_labels.get(output_language, output_language),
    }


def input_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    form = AnalysisInputForm(request.POST or None, language=language)

    if request.method == 'POST' and form.is_valid():
        cv_text = form.cleaned_data['cv_text']
        job_description_text = form.cleaned_data['job_description_text']
        language = form.cleaned_data['output_language']
        text = get_translations(language)
        results = _build_mock_results(language, form, text)
        cv_skills = extract_skills(cv_text)
        job_description_skills = extract_skills(job_description_text)
        skill_comparison = compare_skills(cv_skills, job_description_skills)

        results['cv_skills'] = cv_skills
        results['job_description_skills'] = job_description_skills
        results.update(skill_comparison)

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
