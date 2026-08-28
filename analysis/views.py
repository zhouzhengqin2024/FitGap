import copy

from django.contrib import messages
from django.contrib.auth import login, logout
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import AnalysisRecord
from .ai_learning_roadmap import LearningRoadmapUnavailable, generate_learning_roadmap
from .ai_prioritisation import AIPrioritisationUnavailable, prioritise_skill_gaps
from .document_extraction import DocumentExtractionError, extract_document_text
from .forms import AccountLoginForm, AccountRegistrationForm, AnalysisInputForm, AnalysisRenameForm
from .pdf_export import build_analysis_record_pdf
from .services import (
    build_skill_evidence_details,
    calculate_match_score,
    compare_skills,
    extract_skills,
    generate_learning_recommendations,
)
from .translations import get_translations, normalise_language
from .translations import SUPPORTED_LANGUAGE_OPTIONS

PENDING_ROADMAP_CONTINUITY_KEY = 'pending_roadmap_continuity'
CURRENT_ANALYSIS_RECORD_KEY = 'current_analysis_record_id'

STATUS_ORDER = {
    AnalysisRecord.STATUS_STARTED: 0,
    AnalysisRecord.STATUS_ANALYSIS_COMPLETED: 1,
    AnalysisRecord.STATUS_PRIORITIES_COMPLETED: 2,
    AnalysisRecord.STATUS_ROADMAP_COMPLETED: 3,
}


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


def _language_selector_context(language, url_builder, method='get', payload=''):
    options = []

    for option in SUPPORTED_LANGUAGE_OPTIONS:
        item = option.copy()
        item['url'] = url_builder(option['code'])
        item['active'] = option['code'] == language
        options.append(item)

    current_option = next(option for option in options if option['active'])
    return {
        'current_language_option': current_option,
        'language_options': options,
        'language_selector_method': method,
        'language_selector_payload': payload,
    }


def _with_language_selector(context, language, url_builder, method='get', payload=''):
    context.update(_language_selector_context(language, url_builder, method=method, payload=payload))
    return context


def _default_target_role(language):
    return '未命名分析' if language == 'zh' else 'Untitled Analysis'


def _is_system_fallback_title(value):
    return value.strip() in {'', 'Untitled Analysis', '未命名分析'}


def _meaningful_target_role(record):
    target_role = (record.target_role or '').strip()
    return '' if _is_system_fallback_title(target_role) else target_role


def _record_display_title(record, language):
    display_name = (record.display_name or '').strip()
    if display_name:
        return display_name

    target_role = _meaningful_target_role(record)
    if target_role:
        return target_role

    return _default_target_role(language)


def _clear_current_analysis_record(request):
    request.session.pop(CURRENT_ANALYSIS_RECORD_KEY, None)


def _get_current_analysis_record(request):
    if not request.user.is_authenticated:
        return None

    record_id = request.session.get(CURRENT_ANALYSIS_RECORD_KEY)
    if not record_id:
        return None

    record = AnalysisRecord.objects.filter(id=record_id, user=request.user).first()
    if record is None:
        _clear_current_analysis_record(request)
    return record


def _get_owned_analysis_record_or_404(request, record_id):
    return get_object_or_404(AnalysisRecord, id=record_id, user=request.user)


def _get_or_create_current_analysis_record(request, language):
    if not request.user.is_authenticated:
        return None

    record = _get_current_analysis_record(request)
    if record is None:
        record = AnalysisRecord.objects.create(
            user=request.user,
            language=language,
            target_role=_default_target_role(language),
        )
        request.session[CURRENT_ANALYSIS_RECORD_KEY] = record.id
    return record


def _advance_record_status(record, status):
    if STATUS_ORDER[status] > STATUS_ORDER.get(record.status, 0):
        record.status = status


def _analysis_snapshot(results):
    return {
        'cv_skills': results.get('cv_skills', []),
        'job_description_skills': results.get('job_description_skills', []),
        'matched_skills': results.get('matched_skills', []),
        'missing_skills': results.get('missing_skills', []),
        'match_score': results.get('match_score', 0),
        'match_score_explanation': results.get('match_score_explanation', ''),
        'matched_skill_details': results.get('matched_skill_details', []),
        'missing_skill_details': results.get('missing_skill_details', []),
        'learning_recommendations': results.get('learning_recommendations', []),
    }


def _persist_analysis_snapshot(request, language, results):
    record = _get_or_create_current_analysis_record(request, language)
    if record is None:
        return None

    record.language = language
    record.analysis_snapshot = _analysis_snapshot(results)
    _advance_record_status(record, AnalysisRecord.STATUS_ANALYSIS_COMPLETED)
    record.save()
    return record


def _persist_priority_snapshot(request, language, results):
    record = _get_or_create_current_analysis_record(request, language)
    if record is None:
        return None

    if not record.analysis_snapshot:
        record.analysis_snapshot = _analysis_snapshot(results)
    record.language = language
    record.priority_snapshot = results.get('ai_prioritisation', {})
    _advance_record_status(record, AnalysisRecord.STATUS_PRIORITIES_COMPLETED)
    record.save()
    return record


def _persist_roadmap_snapshot(request, language, results):
    record = _get_or_create_current_analysis_record(request, language)
    if record is None:
        return None

    if not record.analysis_snapshot:
        record.analysis_snapshot = _analysis_snapshot(results)
    if not record.priority_snapshot:
        record.priority_snapshot = results.get('ai_prioritisation', {})
    record.language = language
    record.roadmap_snapshot = results.get('learning_roadmap', {})
    _advance_record_status(record, AnalysisRecord.STATUS_ROADMAP_COMPLETED)
    record.save()
    return record


def _history_record_item(record, language, text):
    status_labels = {
        AnalysisRecord.STATUS_STARTED: text['analysis_status_started'],
        AnalysisRecord.STATUS_ANALYSIS_COMPLETED: text['analysis_status_analysis_completed'],
        AnalysisRecord.STATUS_PRIORITIES_COMPLETED: text['analysis_status_priorities_completed'],
        AnalysisRecord.STATUS_ROADMAP_COMPLETED: text['analysis_status_roadmap_completed'],
    }
    return {
        'record': record,
        'title': _record_display_title(record, language),
        'target_role': _meaningful_target_role(record),
        'status_label': status_labels.get(record.status, record.status),
        'language_label': text[f"analysis_language_{record.language}"],
        'rename_form': AnalysisRenameForm(
            initial={'display_name': record.display_name or record.target_role},
            language=language,
        ),
    }


def _saved_record_context(record, language, text, rename_form=None):
    analysis_snapshot = copy.deepcopy(record.analysis_snapshot or {})
    priority_snapshot = copy.deepcopy(record.priority_snapshot or {})
    roadmap_snapshot = copy.deepcopy(record.roadmap_snapshot or {})

    if priority_snapshot.get('status') == 'success':
        _add_ai_priority_labels(priority_snapshot.get('priorities', []), text)
    _add_roadmap_labels(roadmap_snapshot, text)

    return {
        'record': record,
        'title': _record_display_title(record, language),
        'target_role': _meaningful_target_role(record),
        'status_label': _history_record_item(record, language, text)['status_label'],
        'language_label': text[f"analysis_language_{record.language}"],
        'analysis_snapshot': analysis_snapshot,
        'priority_snapshot': priority_snapshot,
        'roadmap_snapshot': roadmap_snapshot,
        'rename_form': rename_form or AnalysisRenameForm(
            initial={'display_name': record.display_name or record.target_role},
            language=language,
        ),
    }


def _apply_language_labels(results, language, text):
    results['output_language'] = (
        text['language_chinese_choice']
        if language == 'zh'
        else text['language_english_choice']
    )

    if results.get('job_description_skills') is not None and results.get('matched_skills') is not None:
        results['match_score_explanation'] = _build_match_score_explanation(
            text,
            results['matched_skills'],
            results['job_description_skills'],
        )

    ai_prioritisation = results.get('ai_prioritisation')

    if ai_prioritisation and ai_prioritisation.get('status') == 'success':
        _add_ai_priority_labels(ai_prioritisation.get('priorities', []), text)

    _add_roadmap_labels(results.get('learning_roadmap'), text)

    return results


def _render_results(request, language, results, text):
    results = _apply_language_labels(results, language, text)
    payload = _sign_results(results)

    return render(
        request,
        'analysis/results.html',
        _with_language_selector(
            {
            'analysis_payload': payload,
            'language': language,
            'results': results,
            'text': text,
            },
            language,
            lambda code: f'/results/full-analysis/?lang={code}',
            method='post',
            payload=payload,
        ),
    )


def _render_ai_results(request, language, results, text):
    results = _apply_language_labels(results, language, text)
    payload = _sign_results(results)

    return render(
        request,
        'analysis/ai_results.html',
        _with_language_selector(
            {
            'analysis_payload': payload,
            'language': language,
            'results': results,
            'text': text,
            },
            language,
            lambda code: f'/results/ai-results/?lang={code}',
            method='post',
            payload=payload,
        ),
    )


def _render_learning_roadmap(request, language, results, text):
    results = _apply_language_labels(results, language, text)
    payload = _sign_results(results)

    return render(
        request,
        'analysis/learning_roadmap.html',
        _with_language_selector(
            {
            'analysis_payload': payload,
            'export_record': _get_current_analysis_record(request),
            'language': language,
            'results': results,
            'text': text,
            },
            language,
            lambda code: f'/results/learning-roadmap/?lang={code}',
            method='post',
            payload=payload,
        ),
    )


def _add_ai_priority_labels(priorities, text):
    for item in priorities:
        item['priority_label'] = text[f"ai_priority_{item['priority']}"]
    return priorities


def _add_roadmap_labels(roadmap, text):
    if not roadmap:
        return roadmap

    for item in roadmap.get('skills', []):
        item['priority_label'] = text[f"ai_priority_{item['priority']}"]
        item['stage_label'] = text[f"roadmap_{item['stage']}"]

    return roadmap


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


def _build_roadmap_status(status, text):
    message_key = 'roadmap_no_priorities' if status == 'empty' else 'roadmap_unavailable'
    return {
        'status': status,
        'message': text[message_key],
    }


def _account_url(language, roadmap_intent=False):
    url = f'/account/?lang={language}'
    if roadmap_intent:
        url += '&intent=roadmap'
    return url


def _intent_query(roadmap_intent=False):
    return '&intent=roadmap' if roadmap_intent else ''


def _account_login_url(language, roadmap_intent=False):
    return f'/account/login/?lang={language}{_intent_query(roadmap_intent)}'


def _account_register_url(language, roadmap_intent=False):
    return f'/account/register/?lang={language}{_intent_query(roadmap_intent)}'


def _post_auth_redirect_url(language, roadmap_intent=False):
    if roadmap_intent:
        return f'/analyse/?lang={language}'
    return _account_url(language)


def _clear_pending_roadmap_continuity(request):
    request.session.pop(PENDING_ROADMAP_CONTINUITY_KEY, None)


def _valid_roadmap_continuity_results(payload):
    try:
        results = signing.loads(payload, max_age=3600)
    except signing.BadSignature:
        return None

    if results.get('ai_prioritisation', {}).get('status') != 'success':
        return None

    return results


def _restore_pending_roadmap_continuity(request, language, text):
    state = request.session.get(PENDING_ROADMAP_CONTINUITY_KEY)

    if not isinstance(state, dict):
        _clear_pending_roadmap_continuity(request)
        messages.warning(request, text['account_continuity_restore_failed'])
        return redirect(f'/analyse/?lang={language}')

    payload = state.get('analysis_payload')
    if not isinstance(payload, str):
        _clear_pending_roadmap_continuity(request)
        messages.warning(request, text['account_continuity_restore_failed'])
        return redirect(f'/analyse/?lang={language}')

    results = _valid_roadmap_continuity_results(payload)
    if results is None:
        _clear_pending_roadmap_continuity(request)
        messages.warning(request, text['account_continuity_restore_failed'])
        return redirect(f'/analyse/?lang={language}')

    _clear_pending_roadmap_continuity(request)
    _persist_priority_snapshot(request, language, results)
    messages.success(request, text['account_continue_roadmap'])
    return _render_ai_results(request, language, results, text)


def landing_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    return render(
        request,
        'analysis/landing.html',
        _with_language_selector({
            'language': language,
            'text': text,
        }, language, lambda code: f'/?lang={code}'),
    )


def account_entry_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    roadmap_intent = request.GET.get('intent') == 'roadmap'

    if request.method == 'POST' and request.POST.get('account_action') == 'logout':
        _clear_pending_roadmap_continuity(request)
        _clear_current_analysis_record(request)
        logout(request)
        messages.success(request, text['account_signed_out'])
        return redirect(f'/?lang={language}')

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language, roadmap_intent))

    return render(
        request,
        'analysis/account_entry.html',
        _with_language_selector({
            'language': language,
            'roadmap_intent': roadmap_intent,
            'text': text,
        }, language, lambda code: _account_url(code, roadmap_intent)),
    )


def account_login_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    roadmap_intent = request.GET.get('intent') == 'roadmap'
    login_form = AccountLoginForm(language=language, request=request, prefix='login')

    if request.user.is_authenticated:
        return redirect(_account_url(language))

    if request.method == 'POST':
        login_form = AccountLoginForm(request.POST, language=language, request=request, prefix='login')
        if login_form.is_valid():
            login(request, login_form.user)
            if roadmap_intent:
                return _restore_pending_roadmap_continuity(request, language, text)
            else:
                messages.success(request, text['account_signed_in'])
            return redirect(_post_auth_redirect_url(language, roadmap_intent))

    return render(
        request,
        'analysis/account_login.html',
        _with_language_selector({
            'language': language,
            'login_form': login_form,
            'register_url': _account_register_url(language, roadmap_intent),
            'roadmap_intent': roadmap_intent,
            'text': text,
        }, language, lambda code: _account_login_url(code, roadmap_intent)),
    )


def account_register_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)
    roadmap_intent = request.GET.get('intent') == 'roadmap'
    registration_form = AccountRegistrationForm(language=language, prefix='register')

    if request.user.is_authenticated:
        return redirect(_account_url(language))

    if request.method == 'POST':
        registration_form = AccountRegistrationForm(request.POST, language=language, prefix='register')
        if registration_form.is_valid():
            user = registration_form.save()
            login(request, user)
            if roadmap_intent:
                return _restore_pending_roadmap_continuity(request, language, text)
            else:
                messages.success(request, text['account_created'])
            return redirect(_post_auth_redirect_url(language, roadmap_intent))

    return render(
        request,
        'analysis/account_register.html',
        _with_language_selector({
            'language': language,
            'login_url': _account_login_url(language, roadmap_intent),
            'registration_form': registration_form,
            'roadmap_intent': roadmap_intent,
            'text': text,
        }, language, lambda code: _account_register_url(code, roadmap_intent)),
    )


@require_POST
def roadmap_auth_start_view(request):
    language = _get_selected_language(request)
    target = request.POST.get('target')
    payload = request.POST.get('analysis_payload', '')

    if _valid_roadmap_continuity_results(payload) is not None:
        request.session[PENDING_ROADMAP_CONTINUITY_KEY] = {
            'analysis_payload': payload,
            'language': language,
        }

    if target == 'register':
        return redirect(_account_register_url(language, roadmap_intent=True))

    return redirect(_account_login_url(language, roadmap_intent=True))


def analysis_history_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language))

    record_items = [
        _history_record_item(record, language, text)
        for record in AnalysisRecord.objects.filter(user=request.user).order_by('-created_at', '-id')
    ]

    return render(
        request,
        'analysis/history.html',
        _with_language_selector({
            'language': language,
            'record_items': record_items,
            'text': text,
        }, language, lambda code: f'/account/analyses/?lang={code}'),
    )


def analysis_history_detail_view(request, record_id):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language))

    record = _get_owned_analysis_record_or_404(request, record_id)

    return render(
        request,
        'analysis/history_detail.html',
        _with_language_selector({
            'language': language,
            'item': _saved_record_context(record, language, text),
            'text': text,
        }, language, lambda code: f'/account/analyses/{record.id}/?lang={code}'),
    )


def analysis_history_pdf_view(request, record_id):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language))

    record = _get_owned_analysis_record_or_404(request, record_id)
    pdf_content = build_analysis_record_pdf(record, text)
    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="fitgap-report-{record.id}.pdf"'
    return response


@require_POST
def analysis_history_rename_view(request, record_id):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language))

    record = _get_owned_analysis_record_or_404(request, record_id)
    form = AnalysisRenameForm(request.POST, language=language)

    if form.is_valid():
        record.display_name = form.cleaned_data['display_name']
        record.save(update_fields=['display_name', 'updated_at'])
        messages.success(request, text['analysis_renamed'])
        return redirect(f'/account/analyses/{record.id}/?lang={language}')

    return render(
        request,
        'analysis/history_detail.html',
        _with_language_selector({
            'language': language,
            'item': _saved_record_context(record, language, text, rename_form=form),
            'text': text,
        }, language, lambda code: f'/account/analyses/{record.id}/?lang={code}'),
        status=400,
    )


def analysis_history_delete_view(request, record_id):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_login_url(language))

    record = _get_owned_analysis_record_or_404(request, record_id)

    if request.method == 'POST':
        if request.session.get(CURRENT_ANALYSIS_RECORD_KEY) == record.id:
            _clear_current_analysis_record(request)
        record.delete()
        messages.success(request, text['analysis_deleted'])
        return redirect(f'/account/analyses/?lang={language}')

    return render(
        request,
        'analysis/history_delete.html',
        _with_language_selector({
            'language': language,
            'item': _history_record_item(record, language, text),
            'text': text,
        }, language, lambda code: f'/account/analyses/{record.id}/delete/?lang={code}'),
    )


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

    if request.method == 'GET':
        _clear_pending_roadmap_continuity(request)
        _clear_current_analysis_record(request)

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

        _persist_analysis_snapshot(request, language, results)
        return _render_results(request, language, results, text)

    return render(
        request,
        'analysis/input.html',
        _with_language_selector({
            'form': form,
            'language': language,
            'text': text,
        }, language, lambda code: f'/analyse/?lang={code}'),
    )


@require_POST
def full_analysis_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    try:
        results = signing.loads(request.POST.get('analysis_payload', ''), max_age=3600)
    except signing.BadSignature:
        results = {}

    return _render_results(request, language, results, text)


@require_POST
def ai_results_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    try:
        results = signing.loads(request.POST.get('analysis_payload', ''), max_age=3600)
    except signing.BadSignature:
        results = {}

    if results.get('ai_prioritisation', {}).get('status') == 'success':
        return _render_ai_results(request, language, results, text)

    return _render_results(request, language, results, text)


@require_POST
def learning_roadmap_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    try:
        results = signing.loads(request.POST.get('analysis_payload', ''), max_age=3600)
    except signing.BadSignature:
        results = {}

    if results.get('learning_roadmap'):
        return _render_learning_roadmap(request, language, results, text)

    if results.get('ai_prioritisation', {}).get('status') == 'success':
        return _render_ai_results(request, language, results, text)

    return _render_results(request, language, results, text)


@require_POST
def ai_learning_roadmap_view(request):
    language = _get_selected_language(request)
    text = get_translations(language)

    if not request.user.is_authenticated:
        return redirect(_account_url(language, roadmap_intent=True))

    try:
        results = signing.loads(request.POST.get('analysis_payload', ''), max_age=3600)
    except signing.BadSignature:
        results = {}

    if results.get('ai_prioritisation', {}).get('status') != 'success':
        results['learning_roadmap_status'] = _build_roadmap_status('empty', text)
        return _render_ai_results(request, language, results, text)

    try:
        roadmap = generate_learning_roadmap(results, language)
    except LearningRoadmapUnavailable:
        results['learning_roadmap_status'] = _build_roadmap_status('fallback', text)
        return _render_ai_results(request, language, results, text)

    if not roadmap:
        results['learning_roadmap_status'] = _build_roadmap_status('empty', text)
        return _render_ai_results(request, language, results, text)

    results['learning_roadmap'] = roadmap
    results.pop('learning_roadmap_status', None)
    _persist_roadmap_snapshot(request, language, results)
    return _render_learning_roadmap(request, language, results, text)


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
        _persist_priority_snapshot(request, language, results)
        return _render_ai_results(request, language, results, text)

    return _render_results(request, language, results, text)
