import json
import logging
import os
import re

from .ai_prioritisation import ALLOWED_PRIORITIES, GEMINI_MODEL

try:
    from google import genai
except ImportError:  # pragma: no cover - exercised in environments without the optional package.
    genai = None


ALLOWED_STAGES = {'now', 'next', 'later'}
MAX_ROADMAP_SKILLS = 3
MAX_STEPS_PER_SKILL = 5
MAX_MINIMUM_FEATURES = 8
MAX_SUGGESTED_EVIDENCE = 6
MAX_INTERVIEW_TALKING_POINTS = 4
MAX_LOGGED_API_MESSAGE_LENGTH = 500
logger = logging.getLogger(__name__)

ROADMAP_RESPONSE_SCHEMA = {
    'type': 'object',
    'required': ['summary', 'skills'],
    'properties': {
        'summary': {
            'type': 'object',
            'required': [
                'start_with',
                'then',
                'later',
                'strategy',
                'total_estimated_hours',
                'suggested_pace',
                'immediate_next_action',
            ],
            'properties': {
                'start_with': {'type': 'string'},
                'then': {'type': 'string'},
                'later': {'type': 'string'},
                'strategy': {'type': 'string'},
                'total_estimated_hours': {'type': 'string'},
                'suggested_pace': {'type': 'string'},
                'immediate_next_action': {
                    'type': 'object',
                    'required': ['skill', 'action', 'estimated_hours', 'completion_criteria'],
                    'properties': {
                        'skill': {'type': 'string'},
                        'action': {'type': 'string'},
                        'estimated_hours': {'type': 'string'},
                        'completion_criteria': {'type': 'string'},
                    },
                },
            },
        },
        'skills': {
            'type': 'array',
            'items': {
                'type': 'object',
                'required': [
                    'skill',
                    'priority',
                    'stage',
                    'why_now',
                    'target_competency',
                    'steps',
                    'evidence_outcome',
                ],
                'properties': {
                    'skill': {'type': 'string'},
                    'priority': {'type': 'string'},
                    'stage': {'type': 'string'},
                    'why_now': {'type': 'string'},
                    'target_competency': {'type': 'string'},
                    'steps': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'required': [
                                'step_number',
                                'title',
                                'learning_objective',
                                'topics',
                                'action',
                                'why_this_step',
                                'estimated_hours',
                                'completion_criteria',
                            ],
                            'properties': {
                                'step_number': {'type': 'integer'},
                                'title': {'type': 'string'},
                                'learning_objective': {'type': 'string'},
                                'topics': {'type': 'array', 'items': {'type': 'string'}},
                                'action': {'type': 'string'},
                                'why_this_step': {'type': 'string'},
                                'estimated_hours': {'type': 'string'},
                                'completion_criteria': {'type': 'string'},
                            },
                        },
                    },
                    'evidence_outcome': {
                        'type': 'object',
                        'required': [
                            'deliverable',
                            'recruitment_value',
                            'what_it_demonstrates',
                            'minimum_features',
                            'suggested_evidence',
                            'interview_talking_points',
                            'cv_usage_guidance',
                        ],
                        'properties': {
                            'deliverable': {'type': 'string'},
                            'recruitment_value': {'type': 'string'},
                            'what_it_demonstrates': {'type': 'string'},
                            'minimum_features': {
                                'type': 'array',
                                'items': {'type': 'string'},
                            },
                            'suggested_evidence': {
                                'type': 'array',
                                'items': {'type': 'string'},
                            },
                            'interview_talking_points': {
                                'type': 'array',
                                'items': {'type': 'string'},
                            },
                            'cv_usage_guidance': {'type': 'string'},
                        },
                    },
                },
            },
        },
    },
}


class LearningRoadmapUnavailable(Exception):
    """Raised when AI roadmap generation cannot safely produce validated output."""


def _fail(reason):
    return LearningRoadmapUnavailable(reason)


def _normalise_skill(skill):
    return str(skill).strip().lower()


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise _fail(f'missing or empty {field_name}')
    return value.strip()


def _require_text_list(value, max_items, field_name):
    if not isinstance(value, list):
        raise _fail(f'{field_name} is not a list')

    if not value:
        raise _fail(f'{field_name} is empty')

    if len(value) > max_items:
        raise _fail(f'{field_name} exceeds maximum of {max_items}')

    return [
        _require_text(item, f'{field_name}[{index}]')
        for index, item in enumerate(value)
    ]


def _safe_api_message(message, sensitive_fragments):
    if not isinstance(message, str) or not message.strip():
        return None

    safe_message = ' '.join(message.split())
    api_key = os.environ.get('GEMINI_API_KEY')

    if api_key:
        safe_message = safe_message.replace(api_key, '[redacted]')

    safe_message = re.sub(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', '[redacted-email]', safe_message)
    safe_message = re.sub(r'\+?\d[\d\s().-]{7,}\d', '[redacted-phone]', safe_message)

    if len(safe_message) > MAX_LOGGED_API_MESSAGE_LENGTH:
        return '[omitted unsafe or overly long API message]'

    unsafe_markers = [
        'analysis_payload',
        'contents=',
        'response_json_schema=',
        'responseJsonSchema',
        'GEMINI_API_KEY',
    ]
    if any(marker in safe_message for marker in unsafe_markers):
        return '[omitted unsafe or overly long API message]'

    for fragment in sensitive_fragments:
        if fragment and len(fragment) > 20 and fragment in safe_message:
            return '[omitted unsafe or overly long API message]'

    return safe_message


def _safe_api_error_metadata(exc, roadmap_input):
    """Return concise API error metadata without request payloads or secrets."""
    sensitive_fragments = [
        evidence
        for item in roadmap_input.get('priority_gaps', [])
        for evidence in item.get('jd_evidence', [])
        if isinstance(evidence, str)
    ]
    message = _safe_api_message(getattr(exc, 'message', None), sensitive_fragments)

    metadata = {
        'status': getattr(exc, 'code', None),
        'code': getattr(exc, 'status', None),
    }

    if message:
        metadata['message'] = message

    return metadata


def build_learning_roadmap_input(results):
    """Build privacy-minimised structured data for roadmap generation."""
    missing_details = {
        _normalise_skill(item['skill']): item
        for item in results.get('missing_skill_details', [])
    }

    priority_gaps = []
    for item in results.get('ai_prioritisation', {}).get('priorities', []):
        missing_detail = missing_details.get(_normalise_skill(item['skill']), {})
        priority_gaps.append({
            'skill': item['skill'],
            'priority': item['priority'],
            'priority_reason': item['reason'],
            'jd_evidence': [
                evidence['excerpt']
                for evidence in missing_detail.get('jd_evidence', [])
                if evidence.get('excerpt')
            ],
            'cv_evidence': None,
        })

    return {
        'existing_skills': results.get('cv_skills', []),
        'priority_gaps': priority_gaps,
    }


def validate_learning_roadmap(response_data, verified_priority_skills):
    """Validate roadmap output against the existing validated priority skills."""
    if not isinstance(response_data, dict):
        raise _fail('response root is not an object')

    summary = response_data.get('summary')
    skills = response_data.get('skills')

    if not isinstance(summary, dict):
        raise _fail('summary is missing or not an object')

    if not isinstance(skills, list):
        raise _fail('skills is missing or not a list')

    if not skills:
        raise _fail('skills is empty')

    if len(skills) > MAX_ROADMAP_SKILLS:
        raise _fail(f'skills exceeds maximum of {MAX_ROADMAP_SKILLS}')

    validated_summary = {
        key: _require_text(summary.get(key), f'summary.{key}')
        for key in ['start_with', 'then', 'later', 'strategy', 'total_estimated_hours', 'suggested_pace']
    }
    verified_lookup = {
        _normalise_skill(skill): skill
        for skill in verified_priority_skills
    }
    seen_skills = set()
    validated_skills = []

    for skill_index, skill_item in enumerate(skills):
        if not isinstance(skill_item, dict):
            raise _fail(f'skills[{skill_index}] is not an object')

        normalised_skill = _normalise_skill(skill_item.get('skill'))
        priority = _require_text(skill_item.get('priority'), f'skills[{skill_index}].priority').lower()
        stage = _require_text(skill_item.get('stage'), f'skills[{skill_index}].stage').lower()

        if normalised_skill not in verified_lookup:
            raise _fail(f'skills[{skill_index}].skill is not a validated priority skill')

        if normalised_skill in seen_skills:
            raise _fail(f'duplicate roadmap skill: {verified_lookup[normalised_skill]}')

        if priority not in ALLOWED_PRIORITIES or stage not in ALLOWED_STAGES:
            raise _fail(f'invalid priority or stage for {verified_lookup[normalised_skill]}')

        steps = skill_item.get('steps')
        if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS_PER_SKILL:
            raise _fail(f'steps for {verified_lookup[normalised_skill]} are missing, empty, or excessive')

        validated_steps = []
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise _fail(f'steps[{step_index}] for {verified_lookup[normalised_skill]} is not an object')

            topics = step.get('topics')
            if not isinstance(topics, list) or not topics:
                raise _fail(f'steps[{step_index}].topics for {verified_lookup[normalised_skill]} is missing or empty')

            try:
                step_number = int(step.get('step_number'))
            except (TypeError, ValueError) as exc:
                raise _fail(f'steps[{step_index}].step_number for {verified_lookup[normalised_skill]} is invalid') from exc

            validated_steps.append({
                'step_number': step_number,
                'title': _require_text(step.get('title'), f'steps[{step_index}].title'),
                'learning_objective': _require_text(
                    step.get('learning_objective'),
                    f'steps[{step_index}].learning_objective',
                ),
                'topics': [
                    _require_text(topic, f'steps[{step_index}].topics[{topic_index}]')
                    for topic_index, topic in enumerate(topics)
                ],
                'action': _require_text(step.get('action'), f'steps[{step_index}].action'),
                'why_this_step': _require_text(step.get('why_this_step'), f'steps[{step_index}].why_this_step'),
                'estimated_hours': _require_text(step.get('estimated_hours'), f'steps[{step_index}].estimated_hours'),
                'completion_criteria': _require_text(
                    step.get('completion_criteria'),
                    f'steps[{step_index}].completion_criteria',
                ),
            })

        evidence_outcome = skill_item.get('evidence_outcome')
        if not isinstance(evidence_outcome, dict):
            raise _fail(f'evidence_outcome for {verified_lookup[normalised_skill]} is missing or not an object')

        seen_skills.add(normalised_skill)
        validated_skills.append({
            'skill': verified_lookup[normalised_skill],
            'priority': priority,
            'stage': stage,
            'why_now': _require_text(skill_item.get('why_now'), f'skills[{skill_index}].why_now'),
            'target_competency': _require_text(
                skill_item.get('target_competency'),
                f'skills[{skill_index}].target_competency',
            ),
            'steps': validated_steps,
            'evidence_outcome': {
                'deliverable': _require_text(evidence_outcome.get('deliverable'), 'evidence_outcome.deliverable'),
                'recruitment_value': _require_text(
                    evidence_outcome.get('recruitment_value'),
                    'evidence_outcome.recruitment_value',
                ),
                'what_it_demonstrates': _require_text(
                    evidence_outcome.get('what_it_demonstrates'),
                    'evidence_outcome.what_it_demonstrates',
                ),
                'minimum_features': _require_text_list(
                    evidence_outcome.get('minimum_features'),
                    MAX_MINIMUM_FEATURES,
                    'evidence_outcome.minimum_features',
                ),
                'suggested_evidence': _require_text_list(
                    evidence_outcome.get('suggested_evidence'),
                    MAX_SUGGESTED_EVIDENCE,
                    'evidence_outcome.suggested_evidence',
                ),
                'interview_talking_points': _require_text_list(
                    evidence_outcome.get('interview_talking_points'),
                    MAX_INTERVIEW_TALKING_POINTS,
                    'evidence_outcome.interview_talking_points',
                ),
                'cv_usage_guidance': _require_text(
                    evidence_outcome.get('cv_usage_guidance'),
                    'evidence_outcome.cv_usage_guidance',
                ),
            },
        })

    immediate_next_action = summary.get('immediate_next_action')
    if not isinstance(immediate_next_action, dict):
        raise _fail('summary.immediate_next_action is missing or not an object')

    immediate_skill = _normalise_skill(immediate_next_action.get('skill'))
    if immediate_skill not in seen_skills:
        raise _fail('immediate_next_action.skill is not a validated roadmap skill')

    validated_summary['immediate_next_action'] = {
        'skill': verified_lookup[immediate_skill],
        'action': _require_text(immediate_next_action.get('action'), 'immediate_next_action.action'),
        'estimated_hours': _require_text(
            immediate_next_action.get('estimated_hours'),
            'immediate_next_action.estimated_hours',
        ),
        'completion_criteria': _require_text(
            immediate_next_action.get('completion_criteria'),
            'immediate_next_action.completion_criteria',
        ),
    }

    return {
        'summary': validated_summary,
        'skills': validated_skills,
    }


def _extract_response_text(response):
    output_text = getattr(response, 'text', '')

    if output_text:
        return output_text

    raise _fail('Gemini response text is empty')


def generate_learning_roadmap(results, language='en'):
    """Use Gemini to generate a validated roadmap for existing priority gaps."""
    roadmap_input = build_learning_roadmap_input(results)

    if not roadmap_input['priority_gaps']:
        return None

    api_key = os.environ.get('GEMINI_API_KEY')

    if not api_key or genai is None:
        logger.warning('Learning roadmap unavailable: missing API key or Gemini SDK unavailable')
        raise _fail('missing API key or Gemini SDK unavailable')

    selected_language = 'Simplified Chinese' if language == 'zh' else 'English'
    verified_priority_skills = [item['skill'] for item in roadmap_input['priority_gaps']]
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                'Create a concrete, personalised learning roadmap only for the verified priority gaps supplied. '
                'Do not add new skills, invent CV experience, invent job requirements, guarantee employment, or '
                'invent academic citations. Use technically accurate terminology; for example, describe Django '
                'with its Model-Template-View structure rather than inaccurately calling it MVC. Avoid duplicated '
                'phrases and exaggerated claims. Use prerequisite sequencing, progressive complexity, active '
                'learning, demonstration of competence, and evidence-based outcomes. Maintain the order: learn, '
                'practise, build, verify, then preserve evidence. Build on existing verified skills where useful, '
                'but do not reteach skills the user already demonstrably has except as context. '
                'Make the summary execution-focused: total_estimated_hours should be an approximate range, '
                'suggested_pace should be practical, and immediate_next_action should be the first concrete task '
                'the user can do today, normally from the first step of the highest-priority skill. '
                'Machine-readable fields must stay canonical English regardless of output language: priority must '
                'be exactly one of high, medium, low; stage must be exactly one of now, next, later. Do not translate '
                'these two field values into Chinese or any other language. User-facing prose fields should use the '
                'selected output language. '
                'Allocate depth by priority: high priority usually needs 3-5 detailed steps, medium priority 2-4 '
                'steps, and low priority 1-2 focused steps or a clear recommendation to delay it. '
                'Each action must describe something observable the learner physically does, such as creating, '
                'implementing, debugging, testing, explaining, comparing, documenting, or refactoring. Completion '
                'criteria must show independent competence and should not be merely watching a tutorial or saying '
                'the user understands the topic. '
                'Evidence outcomes are critical: choose role-relevant deliverables that could support a portfolio, '
                'GitHub or GitLab profile, interview discussion, technical screening, or recruiter review. Avoid '
                'generic beginner artifacts such as hello-world apps, copied tutorial projects, trivial todo lists, '
                'or a basic personal blog when a more role-relevant artifact is possible. Explain recruitment_value '
                'realistically without promising interviews, jobs, recruiter approval, production scale, or business '
                'impact. For cv_usage_guidance, never transform a planned learning task into existing CV experience; '
                'only explain how it could be used after the user has actually completed and tested the work. '
                f'Write roadmap prose in {selected_language}; keep technical skill names natural.\n\n'
                + json.dumps(roadmap_input, ensure_ascii=False)
            ),
            config={
                'response_mime_type': 'application/json',
                'response_json_schema': ROADMAP_RESPONSE_SCHEMA,
            },
        )
    except Exception as exc:
        metadata = _safe_api_error_metadata(exc, roadmap_input)
        logger.warning(
            'Learning roadmap Gemini request failed: %s status=%s code=%s message="%s"',
            exc.__class__.__name__,
            metadata.get('status') or 'unknown',
            metadata.get('code') or 'unknown',
            metadata.get('message') or 'unavailable',
        )
        raise _fail('Gemini request failed') from exc

    try:
        response_data = json.loads(_extract_response_text(response))
    except (TypeError, ValueError) as exc:
        logger.warning('Learning roadmap JSON parsing failed: %s', exc.__class__.__name__)
        raise _fail('JSON parsing failed') from exc

    try:
        return validate_learning_roadmap(response_data, verified_priority_skills)
    except LearningRoadmapUnavailable as exc:
        logger.warning('Learning roadmap validation failed: %s', exc)
        raise
