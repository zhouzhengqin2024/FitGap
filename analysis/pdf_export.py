from io import BytesIO
from xml.sax.saxutils import escape

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )
except ImportError:  # pragma: no cover - depends on deployment environment packages.
    colors = None
    TA_CENTER = None
    TA_LEFT = None
    A4 = None
    ParagraphStyle = None
    mm = None
    pdfmetrics = None
    UnicodeCIDFont = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None

PDF_CJK_FONT_NAME = 'STSong-Light'
PDF_LATIN_FONT_NAME = 'Helvetica'
PDF_LATIN_BOLD_FONT_NAME = 'Helvetica-Bold'
PDF_ACCENT = '#1D63ED'
PDF_TEXT = '#1F2937'
PDF_MUTED = '#5F6B7A'


def _register_cjk_pdf_font():
    if pdfmetrics is None:
        raise ImproperlyConfigured('ReportLab is required for PDF export.')

    try:
        pdfmetrics.getFont(PDF_CJK_FONT_NAME)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_CJK_FONT_NAME))


def _is_chinese_report(text):
    return text.get('html_lang') == 'zh-Hans'


def _contains_cjk(value):
    return any('\u4e00' <= character <= '\u9fff' for character in str(value or ''))


def _font_names(is_chinese):
    if is_chinese:
        return {
            'regular': PDF_CJK_FONT_NAME,
            'bold': PDF_CJK_FONT_NAME,
            'footer': PDF_CJK_FONT_NAME,
        }

    return {
        'regular': PDF_LATIN_FONT_NAME,
        'bold': PDF_LATIN_BOLD_FONT_NAME,
        'footer': PDF_LATIN_FONT_NAME,
    }


def _styles(text):
    is_chinese = _is_chinese_report(text)
    fonts = _font_names(is_chinese)
    return {
        'title': ParagraphStyle(
            'FitGapTitle',
            fontName=fonts['bold'],
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor(PDF_ACCENT),
            spaceAfter=3 * mm,
        ),
        'subtitle': ParagraphStyle(
            'FitGapSubtitle',
            fontName=fonts['regular'],
            fontSize=14,
            leading=21,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#26364D'),
            spaceAfter=9 * mm,
        ),
        'section': ParagraphStyle(
            'FitGapSection',
            fontName=fonts['bold'],
            fontSize=16,
            leading=22,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_ACCENT),
            spaceBefore=12 * mm,
            spaceAfter=5 * mm,
        ),
        'skill': ParagraphStyle(
            'FitGapSkill',
            fontName=fonts['bold'],
            fontSize=12,
            leading=18,
            alignment=TA_LEFT,
            textColor=colors.HexColor('#26364D'),
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        'source_label': ParagraphStyle(
            'FitGapSourceLabel',
            fontName=fonts['bold'],
            fontSize=10.5,
            leading=15 if not is_chinese else 16,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_ACCENT),
            spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
        ),
        'body': ParagraphStyle(
            'FitGapBody',
            fontName=fonts['regular'],
            fontSize=10.5 if not is_chinese else 11,
            leading=15.5 if not is_chinese else 18,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_TEXT),
            spaceAfter=1.8 * mm,
        ),
        'muted': ParagraphStyle(
            'FitGapMuted',
            fontName=fonts['regular'],
            fontSize=9.5 if not is_chinese else 10.5,
            leading=14 if not is_chinese else 17,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_MUTED),
            spaceAfter=1.5 * mm,
        ),
        'footer': ParagraphStyle(
            'FitGapFooter',
            fontName=fonts['footer'],
            fontSize=7.5 if not is_chinese else 8,
            leading=10 if not is_chinese else 12,
            alignment=TA_LEFT,
            textColor=colors.HexColor('#697586'),
        ),
        'cjk_body': ParagraphStyle(
            'FitGapCJKBody',
            fontName=PDF_CJK_FONT_NAME,
            fontSize=11,
            leading=18,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_TEXT),
            spaceAfter=1.8 * mm,
        ),
        'cjk_muted': ParagraphStyle(
            'FitGapCJKMuted',
            fontName=PDF_CJK_FONT_NAME,
            fontSize=10.5,
            leading=17,
            alignment=TA_LEFT,
            textColor=colors.HexColor(PDF_MUTED),
            spaceAfter=1.5 * mm,
        ),
    }


def _paragraph(value, style):
    text = escape(str(value or '')).replace('\n', '<br/>')
    return Paragraph(text, style)


def _section(story, title, styles):
    story.append(_paragraph(title, styles['section']))


def _source_style(value, styles, fallback_key='body'):
    if _contains_cjk(value):
        return styles['cjk_muted'] if fallback_key == 'muted' else styles['cjk_body']
    return styles[fallback_key]


def _simple_list(items, styles, placeholder, numbered=False):
    clean_items = [item for item in items if item]

    if not clean_items:
        return _paragraph(placeholder, styles['muted'])

    flowables = []
    for index, item in enumerate(clean_items, start=1):
        marker = f'{index}. ' if numbered else '- '
        flowables.append(_paragraph(f'{marker}{item}', _source_style(item, styles)))

    return flowables


def _append_list(story, items, styles, placeholder, numbered=False):
    flowables = _simple_list(items, styles, placeholder, numbered=numbered)
    if isinstance(flowables, list):
        story.extend(flowables)
    else:
        story.append(flowables)


def _evidence_excerpt(evidence):
    if isinstance(evidence, dict):
        return evidence.get('excerpt', '')
    return evidence


def _add_evidence_group(story, detail, text, styles):
    skill = detail.get('skill', '')
    cv_items = [_evidence_excerpt(item) for item in detail.get('cv_evidence') or []]
    jd_items = [_evidence_excerpt(item) for item in detail.get('jd_evidence') or []]
    story.append(_paragraph(skill, styles['skill']))
    story.append(_paragraph(text['evidence_from_cv'], styles['source_label']))
    _append_list(story, cv_items, styles, text['no_configured_cv_occurrence'])
    story.append(Spacer(1, 4.5 * mm))
    story.append(_paragraph(text['evidence_from_job_description'], styles['source_label']))
    _append_list(story, jd_items, styles, text['no_supporting_excerpt'])
    story.append(Spacer(1, 6 * mm))


def _add_priority_blocks(story, priority_snapshot, text, styles):
    if priority_snapshot.get('status') != 'success':
        story.append(_paragraph(text['saved_priorities_unavailable'], styles['muted']))
        return

    has_content = False
    for priority in priority_snapshot.get('priorities') or []:
        if not priority.get('skill') and not priority.get('reason'):
            continue
        has_content = True
        story.append(_paragraph(priority.get('skill', ''), styles['skill']))
        story.append(_paragraph(priority.get('reason', ''), styles['body']))
        story.append(Spacer(1, 5 * mm))

    if not has_content:
        story.append(_paragraph(text['saved_priorities_unavailable'], styles['muted']))


def _add_roadmap_blocks(story, roadmap_snapshot, text, styles):
    summary = roadmap_snapshot.get('summary') or {}
    immediate_action = summary.get('immediate_next_action') or {}
    has_content = False

    if immediate_action:
        has_content = True
        story.append(_paragraph(immediate_action.get('skill', ''), styles['skill']))
        story.append(_paragraph(text['roadmap_action'], styles['source_label']))
        story.append(_paragraph(immediate_action.get('action', ''), styles['body']))
        story.append(_paragraph(text['roadmap_done_when'], styles['source_label']))
        story.append(_paragraph(immediate_action.get('completion_criteria', ''), styles['body']))
        story.append(Spacer(1, 6 * mm))

    for skill in roadmap_snapshot.get('skills') or []:
        has_content = True
        skill_name = skill.get('skill', '')
        story.append(_paragraph(skill_name, styles['skill']))
        story.append(_paragraph(text['roadmap_action'], styles['source_label']))
        story.append(_paragraph(skill.get('target_outcome', ''), styles['body']))
        story.append(_paragraph(text['roadmap_done_when'], styles['source_label']))
        story.append(_paragraph(skill.get('verification_standard', ''), styles['body']))
        story.append(_paragraph(text['roadmap_core_steps'], styles['source_label']))
        for step in skill.get('core_steps') or []:
            title = step.get('title', '')
            action = step.get('action', '')
            if title or action:
                step_number = step.get('step_number', '')
                prefix = f'{step_number}. ' if step_number else '- '
                step_text = f'{title} - {action}'.strip(' -')
                story.append(_paragraph(f'{prefix}{step_text}', _source_style(step_text, styles)))
        evidence_target = skill.get('evidence_target', '')
        if evidence_target:
            story.append(_paragraph(text['roadmap_evidence_target'], styles['source_label']))
            story.append(_paragraph(evidence_target, styles['muted']))
        story.append(Spacer(1, 7 * mm))

    if not has_content:
        story.append(_paragraph(text['saved_roadmap_unavailable'], styles['muted']))


def _draw_footer(canvas, doc, disclaimer, styles, is_chinese):
    canvas.saveState()
    footer_font = PDF_CJK_FONT_NAME if is_chinese else PDF_LATIN_FONT_NAME
    canvas.setFont(footer_font, 8)
    canvas.setFillColor(colors.HexColor('#697586'))
    canvas.line(doc.leftMargin, 17 * mm, A4[0] - doc.rightMargin, 17 * mm)
    footer = _paragraph(disclaimer, styles['footer'])
    footer_width = A4[0] - doc.leftMargin - doc.rightMargin - 18 * mm
    footer.wrapOn(canvas, footer_width, 12 * mm)
    footer.drawOn(canvas, doc.leftMargin, 6 * mm)
    canvas.drawRightString(A4[0] - doc.rightMargin, 8 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def build_analysis_record_pdf(record, text, exported_at=None):
    """Build a zero-Gemini PDF report from an existing AnalysisRecord snapshot."""
    _register_cjk_pdf_font()
    exported_at = exported_at or timezone.now()
    is_chinese = _is_chinese_report(text)
    styles = _styles(text)
    analysis_snapshot = record.analysis_snapshot or {}
    priority_snapshot = record.priority_snapshot or {}
    roadmap_snapshot = record.roadmap_snapshot or {}
    analysis_mode = analysis_snapshot.get('analysis_mode', 'structured')
    match_score_available = analysis_snapshot.get('match_score_available', True)
    analysis_mode_label = (
        text['analysis_mode_low_coverage_ai']
        if analysis_mode == 'low_coverage_ai'
        else text['analysis_mode_structured']
    )
    match_score_value = (
        f"{analysis_snapshot.get('match_score', 0)}%"
        if match_score_available
        else text['match_score_unavailable']
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=24 * mm,
        leftMargin=24 * mm,
        topMargin=24 * mm,
        bottomMargin=30 * mm,
        title=text['pdf_report_title'],
    )

    report_subtitle = text.get('pdf_report_subtitle', '')
    target_role = (record.display_name or record.target_role or '').strip()
    story = [
        _paragraph('FitGap', styles['title']),
        _paragraph(report_subtitle, styles['subtitle']),
        _paragraph(f"{text['pdf_exported_label']} {timezone.localtime(exported_at).strftime('%Y-%m-%d %H:%M')}", styles['body']),
        _paragraph(f"{text['target_role_label']} {target_role or text['pdf_section_unavailable']}", styles['body']),
        _paragraph(f"{text['analysis_mode_label']} {analysis_mode_label}", styles['body']),
        _paragraph(
            f"{text['match_score']}: {match_score_value}"
            if match_score_available
            else text['match_score_unavailable_display'],
            styles['body'],
        ),
    ]

    _section(story, text['pdf_skill_gap_summary'], styles)
    if analysis_snapshot:
        explanation = analysis_snapshot.get('match_score_explanation')
        if explanation:
            story.append(_paragraph(explanation, styles['body']))
            story.append(Spacer(1, 3 * mm))
        story.append(_paragraph(text['pdf_matched_skills'], styles['skill']))
        _append_list(story, analysis_snapshot.get('matched_skills', []), styles, text['no_matched_skills'])
        story.append(Spacer(1, 5 * mm))
        story.append(_paragraph(text['pdf_missing_skills'], styles['skill']))
        _append_list(story, analysis_snapshot.get('missing_skills', []), styles, text['no_missing_skills'])
    else:
        story.append(_paragraph(text['saved_analysis_unavailable'], styles['muted']))

    _section(story, text['evidence'], styles)
    evidence_details = (
        (analysis_snapshot.get('matched_skill_details') or [])
        + (analysis_snapshot.get('missing_skill_details') or [])
    )
    if evidence_details:
        for detail in evidence_details:
            _add_evidence_group(story, detail, text, styles)
    else:
        story.append(_paragraph(text['pdf_section_unavailable'], styles['muted']))

    _section(story, text['pdf_priorities_heading'], styles)
    _add_priority_blocks(story, priority_snapshot, text, styles)

    _section(story, text['pdf_roadmap_heading'], styles)
    _add_roadmap_blocks(story, roadmap_snapshot, text, styles)

    doc.build(
        story,
        onFirstPage=lambda canvas, document: _draw_footer(
            canvas,
            document,
            text['pdf_footer_disclaimer'],
            styles,
            is_chinese,
        ),
        onLaterPages=lambda canvas, document: _draw_footer(
            canvas,
            document,
            text['pdf_footer_disclaimer'],
            styles,
            is_chinese,
        ),
    )
    return buffer.getvalue()
