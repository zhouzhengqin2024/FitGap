from django import forms


class AnalysisInputForm(forms.Form):
    LANGUAGE_ENGLISH = 'en'
    LANGUAGE_SIMPLIFIED_CHINESE = 'zh-hans'

    OUTPUT_LANGUAGE_CHOICES = [
        (LANGUAGE_ENGLISH, 'English'),
        (LANGUAGE_SIMPLIFIED_CHINESE, 'Simplified Chinese'),
    ]

    cv_text = forms.CharField(
        label='CV Text',
        required=True,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Paste the CV text here.',
            }
        ),
        error_messages={
            'required': 'Please paste the CV text before continuing.',
        },
    )
    jd_text = forms.CharField(
        label='Job Description Text',
        required=True,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Paste the job description text here.',
            }
        ),
        error_messages={
            'required': 'Please paste the job description text before continuing.',
        },
    )
    output_language = forms.ChoiceField(
        label='Output Language',
        choices=OUTPUT_LANGUAGE_CHOICES,
        initial=LANGUAGE_ENGLISH,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
