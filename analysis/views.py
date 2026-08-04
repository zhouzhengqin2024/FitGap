from django.shortcuts import render

from .forms import AnalysisInputForm
from .services import compare_skills, extract_skills


def _build_mock_results(output_language):
    language_labels = dict(AnalysisInputForm.OUTPUT_LANGUAGE_CHOICES)

    return {
        'match_score': 65,
        'learning_recommendations': [
            {
                'skill': 'Django',
                'recommendation': 'Complete a beginner Django tutorial and build one small CRUD app.',
            },
            {
                'skill': 'REST APIs',
                'recommendation': 'Learn HTTP methods, status codes, and practise creating API endpoints.',
            },
        ],
        'output_language': language_labels.get(output_language, output_language),
    }


def input_view(request):
    form = AnalysisInputForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        cv_text = form.cleaned_data['cv_text']
        job_description_text = form.cleaned_data['job_description_text']
        results = _build_mock_results(form.cleaned_data['output_language'])
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
                'results': results,
            },
        )

    return render(
        request,
        'analysis/input.html',
        {
            'form': form,
        },
    )
