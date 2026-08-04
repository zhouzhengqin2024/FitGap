from django.shortcuts import render

from .forms import AnalysisInputForm


def _build_mock_results(output_language):
    language_labels = dict(AnalysisInputForm.OUTPUT_LANGUAGE_CHOICES)

    return {
        'match_score': 65,
        'matched_skills': ['Python', 'SQL', 'Git'],
        'missing_skills': ['Django', 'REST APIs'],
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
        results = _build_mock_results(form.cleaned_data['output_language'])
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
