import json
import os

try:
    from google import genai
except ImportError:  # pragma: no cover - exercised in environments without the optional package.
    genai = None


GEMINI_MODEL = 'gemini-3.6-flash'
ALLOWED_PRIORITIES = {'high', 'medium', 'low'}
MAX_AI_PRIORITIES = 3

PRIORITISATION_RESPONSE_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['priorities'],
    'properties': {
        'priorities': {
            'type': 'array',
            'maxItems': MAX_AI_PRIORITIES,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['skill', 'priority', 'reason'],
                'properties': {
                    'skill': {'type': 'string'},
                    'priority': {'type': 'string', 'enum': sorted(ALLOWED_PRIORITIES)},
                    'reason': {'type': 'string'},
                },
            },
        },
    },
}


class AIPrioritisationUnavailable(Exception):
    """Raised when AI prioritisation cannot safely produce validated output."""


def _normalise_skill(skill):
    return str(skill).strip().lower()


def build_ai_gap_input(missing_skill_details):
    """Build the minimal verified skill-gap data sent to the AI model."""
    return [
        {
            'skill': item['skill'],
            'jd_evidence': [
                evidence['excerpt']
                for evidence in item.get('jd_evidence', [])
                if evidence.get('excerpt')
            ],
            'cv_evidence': None,
        }
        for item in missing_skill_details
    ]


def validate_ai_priorities(response_data, verified_missing_skills):
    """Validate AI priorities against deterministic missing skills."""
    if not isinstance(response_data, dict):
        raise AIPrioritisationUnavailable

    priorities = response_data.get('priorities')

    if not isinstance(priorities, list) or not priorities:
        raise AIPrioritisationUnavailable

    if len(priorities) > MAX_AI_PRIORITIES:
        raise AIPrioritisationUnavailable

    verified_lookup = {
        _normalise_skill(skill): skill
        for skill in verified_missing_skills
    }
    seen_skills = set()
    validated_priorities = []

    for item in priorities:
        if not isinstance(item, dict):
            raise AIPrioritisationUnavailable

        skill = item.get('skill')
        priority = str(item.get('priority', '')).strip().lower()
        reason = str(item.get('reason', '')).strip()
        normalised_skill = _normalise_skill(skill)

        if normalised_skill not in verified_lookup:
            raise AIPrioritisationUnavailable

        if priority not in ALLOWED_PRIORITIES or not reason:
            raise AIPrioritisationUnavailable

        if normalised_skill in seen_skills:
            raise AIPrioritisationUnavailable

        seen_skills.add(normalised_skill)
        validated_priorities.append({
            'skill': verified_lookup[normalised_skill],
            'priority': priority,
            'reason': reason,
        })

    if not validated_priorities:
        raise AIPrioritisationUnavailable

    return validated_priorities


def _extract_response_text(response):
    output_text = getattr(response, 'text', '')

    if output_text:
        return output_text

    raise AIPrioritisationUnavailable


def prioritise_skill_gaps(missing_skill_details, language='en'):
    """Use the Gemini API to rank verified missing skills only."""
    if not missing_skill_details:
        return []

    api_key = os.environ.get('GEMINI_API_KEY')

    if not api_key or genai is None:
        raise AIPrioritisationUnavailable

    selected_language = 'Simplified Chinese' if language == 'zh' else 'English'
    gap_input = build_ai_gap_input(missing_skill_details)
    verified_missing_skills = [item['skill'] for item in missing_skill_details]
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                'Rank only the verified missing skills supplied by FitGap. '
                'Do not add, remove, rename, or reclassify skills. '
                'Do not invent CV experience or job requirements. '
                f'Write concise reasons in {selected_language}.\n\n'
                + json.dumps({
                    'verified_missing_skills': gap_input,
                    'max_results': MAX_AI_PRIORITIES,
                    'allowed_priorities': sorted(ALLOWED_PRIORITIES),
                }, ensure_ascii=False)
            ),
            config={
                'response_mime_type': 'application/json',
                'response_json_schema': PRIORITISATION_RESPONSE_SCHEMA,
            },
        )
    except Exception as exc:
        raise AIPrioritisationUnavailable from exc

    try:
        response_data = json.loads(_extract_response_text(response))
    except (TypeError, ValueError) as exc:
        raise AIPrioritisationUnavailable from exc

    return validate_ai_priorities(response_data, verified_missing_skills)
