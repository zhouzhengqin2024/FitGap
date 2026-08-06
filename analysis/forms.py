from django import forms

from .translations import get_translations


class AnalysisInputForm(forms.Form):
    LANGUAGE_ENGLISH = 'en'
    LANGUAGE_SIMPLIFIED_CHINESE = 'zh'

    OUTPUT_LANGUAGE_CHOICES = [
        (LANGUAGE_ENGLISH, 'English'),
        (LANGUAGE_SIMPLIFIED_CHINESE, 'Simplified Chinese'),
    ]

    cv_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'visually-hidden document-upload-input',
                'accept': '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain',
            }
        ),
    )
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
    job_description_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'visually-hidden document-upload-input',
                'accept': '.pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain',
            }
        ),
    )
    job_description_text = forms.CharField(
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
        choices=OUTPUT_LANGUAGE_CHOICES,
        initial=LANGUAGE_ENGLISH,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, language=LANGUAGE_ENGLISH, **kwargs):
        super().__init__(*args, **kwargs)
        text = get_translations(language)

        self.fields['cv_file'].label = text['cv_upload_label']
        self.fields['cv_file'].help_text = text['supported_upload_formats']
        self.fields['cv_text'].label = text['cv_label']
        self.fields['cv_text'].widget.attrs['placeholder'] = text['cv_placeholder']
        self.fields['cv_text'].error_messages['required'] = text['cv_required']

        self.fields['job_description_file'].label = text['job_description_upload_label']
        self.fields['job_description_file'].help_text = text['supported_upload_formats']
        self.fields['job_description_text'].label = text['job_description_label']
        self.fields['job_description_text'].widget.attrs['placeholder'] = text['job_description_placeholder']
        self.fields['job_description_text'].error_messages['required'] = text['job_description_required']

        self.fields['output_language'].label = text['output_language_label']
        self.fields['output_language'].choices = [
            (self.LANGUAGE_ENGLISH, text['language_english_choice']),
            (self.LANGUAGE_SIMPLIFIED_CHINESE, text['language_chinese_choice']),
        ]
        self.fields['output_language'].initial = language
        self.fields['output_language'].error_messages['required'] = text['output_language_required']
