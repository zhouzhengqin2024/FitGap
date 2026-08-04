from django.shortcuts import render

from .forms import AnalysisInputForm


def input_view(request):
    form = AnalysisInputForm(request.POST or None)
    submitted = False

    if request.method == 'POST' and form.is_valid():
        # Keep this step non-persistent until analysis logic is added.
        submitted = True
        form = AnalysisInputForm()

    return render(
        request,
        'analysis/input.html',
        {
            'form': form,
            'submitted': submitted,
        },
    )
