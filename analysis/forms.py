from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

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


class AccountRegistrationForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, language=AnalysisInputForm.LANGUAGE_ENGLISH, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = get_translations(language)
        self.fields['email'].label = self.text['account_email']
        self.fields['email'].error_messages['required'] = self.text['account_email_required']
        self.fields['email'].error_messages['invalid'] = self.text['account_invalid_email']
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'email',
        })
        self.fields['password'].label = self.text['account_password']
        self.fields['password'].error_messages['required'] = self.text['account_password_required']
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
        })
        self.fields['confirm_password'].label = self.text['account_confirm_password']
        self.fields['confirm_password'].error_messages['required'] = self.text['account_confirm_password_required']
        self.fields['confirm_password'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'new-password',
        })

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        User = get_user_model()

        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(self.text['account_duplicate_email'])

        return email

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', self.text['account_password_mismatch'])

        if email and password:
            User = get_user_model()
            user = User(username=email, email=email)
            try:
                validate_password(password, user)
            except ValidationError as exc:
                self.add_error('password', exc)

        return cleaned_data

    def save(self):
        User = get_user_model()
        email = self.cleaned_data['email']
        return User.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data['password'],
        )


class AccountLoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, language=AnalysisInputForm.LANGUAGE_ENGLISH, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None
        self.text = get_translations(language)
        self.fields['email'].label = self.text['account_email']
        self.fields['email'].error_messages['required'] = self.text['account_email_required']
        self.fields['email'].error_messages['invalid'] = self.text['account_invalid_email']
        self.fields['email'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'email',
        })
        self.fields['password'].label = self.text['account_password']
        self.fields['password'].error_messages['required'] = self.text['account_password_required']
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'autocomplete': 'current-password',
        })

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            self.user = authenticate(
                self.request,
                username=email.strip().lower(),
                password=password,
            )
            if self.user is None:
                raise forms.ValidationError(self.text['account_invalid_credentials'])

        return cleaned_data


class AnalysisRenameForm(forms.Form):
    display_name = forms.CharField(max_length=160)

    def __init__(self, *args, language=AnalysisInputForm.LANGUAGE_ENGLISH, **kwargs):
        super().__init__(*args, **kwargs)
        text = get_translations(language)
        self.fields['display_name'].label = text['analysis_name_label']
        self.fields['display_name'].error_messages['required'] = text['analysis_name_required']
        self.fields['display_name'].error_messages['max_length'] = text['analysis_name_too_long']
        self.fields['display_name'].widget.attrs.update({
            'class': 'form-control',
            'maxlength': '160',
            'aria-label': text['analysis_name_label'],
            'placeholder': text['analysis_name_label'],
        })

    def clean_display_name(self):
        display_name = self.cleaned_data['display_name'].strip()

        if not display_name:
            raise forms.ValidationError(self.fields['display_name'].error_messages['required'])

        return display_name
