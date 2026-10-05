# FitGap

## AI-Assisted Skill-Gap Analysis and Learning Recommendations for International Students

FitGap is a bilingual web application developed as an MSc IT+ individual project at the University of Glasgow.

The system helps users compare a CV with a target job description, identify recognised skill matches and gaps, prioritise missing skills, and generate a personalised learning roadmap.

## Live Application

Production deployment:

https://fitgap-ai.up.railway.app/

The current code uses DeepSeek through the OpenAI Python SDK. The migrated flow has been validated locally with the real DeepSeek API; the Railway deployment has not been updated as part of this migration yet.

---

## Core Features

- CV and job-description text input
- PDF, DOCX and TXT document extraction
- English and Simplified Chinese interface
- Deterministic skill extraction and normalisation
- Matched and missing skill identification
- Evidence-based skill-gap explanation
- Explainable match score
- DeepSeek-based prioritisation of verified skill gaps
- Low-coverage AI-assisted prioritisation when no structured JD skills are recognised
- DeepSeek-generated personalised learning roadmap
- User authentication
- Saved analysis history
- PDF roadmap export
- Cross-domain skill support
- Responsive web interface

---

## Design Principle

A central design principle of FitGap is:

> **Facts are deterministic; AI provides decision support.**

Skill matching, recognised evidence and match-score calculation are primarily handled using deterministic logic.

DeepSeek is used for higher-level decision support, including:

1. prioritising identified skill gaps;
2. suggesting candidate learning priorities when no structured JD skills are recognised; and
3. generating personalised learning roadmaps.

Low-coverage AI suggestions do not replace deterministic matching results. AI output is parsed as JSON and checked by local business validators before use.

This separation was chosen to improve explainability, predictability and testability while reducing reliance on generative AI for factual matching.

---

## Technology Stack

- Python
- Django
- HTML / CSS
- Bootstrap
- SQLite for local development
- PostgreSQL for production
- DeepSeek OpenAI-compatible API
- OpenAI Python SDK (`openai>=2.53.0,<2.54`)
- ReportLab
- Gunicorn
- WhiteNoise
- Railway

---

## Project Structure

### `analysis/`

Contains the main FitGap application and business logic.

Important modules include:

- `views.py` — application request handling and user workflow
- `models.py` — persistent analysis records and history
- `services.py` — core analysis services
- `skill_catalogue.py` — canonical skills and aliases
- `skill_candidates.py` — skill candidate identification
- `skill_normalisation.py` — skill normalisation logic
- `ai_prioritisation.py` — two DeepSeek request paths: verified skill-gap prioritisation and low-coverage AI-assisted prioritisation
- `ai_learning_roadmap.py` — one DeepSeek request path for learning-roadmap generation
- `pdf_export.py` — PDF generation from saved analysis results
- `tests.py` — automated test suite

### `config/`

Contains Django project-level configuration, including:

- settings
- URL configuration
- WSGI / ASGI entry points
- production environment configuration

### `requirements.txt`

Lists Python dependencies required by the project.

---

## Current AI Configuration

Install the dependencies from `requirements.txt`. The application connects to `https://api.deepseek.com` using the OpenAI Python SDK and reads these process environment variables:

- `DEEPSEEK_API_KEY` — required for AI requests; inject a real key securely into the local or production process environment.
- `DEEPSEEK_MODEL` — model selection; `.env.example` specifies `deepseek-flash`, which is also the code default when this variable is unset.

`.env.example` contains placeholders only. The application does not automatically load `.env` files; copying the example alone does not inject environment variables. For production deployment, supply the same DeepSeek variables to the application service and install the current requirements.

Requests use Chat Completions JSON mode, a 45-second SDK timeout, zero automatic retries, and non-streaming responses. Existing fallback behaviour preserves deterministic results and previously generated priorities when AI is unavailable.

---

## Student Contribution and AI-Assisted Development

This project was completed as an individual MSc IT+ project.

I was responsible for the overall ownership and direction of the project, including:

- identifying the project problem and target users;
- defining and refining the project scope;
- gathering and prioritising requirements;
- deciding the overall user workflow and product structure;
- making UX and bilingual-interface decisions;
- defining the architectural boundary between deterministic analysis and generative AI;
- deciding which features belonged in the MVP;
- defining acceptance criteria for iterations;
- selecting and prioritising later improvements;
- conducting manual functional and cross-domain testing;
- reviewing system behaviour and identifying failures;
- deciding how identified problems should be addressed;
- evaluating the final product;
- configuring and validating production deployment;
- maintaining Git commits and version history;
- determining when the product was ready for feature freeze.

Generative-AI development tools, particularly ChatGPT and Codex, were used extensively to assist with software implementation.

AI assistance included:

- generating and modifying code;
- suggesting implementation approaches;
- helping create and extend automated tests;
- debugging technical errors;
- supporting deployment troubleshooting;
- assisting with code-level refinements.

The coding implementation was therefore substantially AI-assisted.

However, AI-generated or AI-suggested changes were not treated as independent project decisions. I remained responsible for defining what the system should do, deciding whether proposed changes matched the project requirements, running automated and manual tests, validating user-facing behaviour, selecting which changes to retain, and managing the final integrated product.

This distinction is important: AI tools supported implementation, while the project requirements, product decisions, architectural constraints, testing decisions, iteration priorities, evaluation and final acceptance remained my responsibility.

---

## Major Development Iterations

The system was developed incrementally.

Important later iterations included:

- evidence-based explanations for matched and missing skills;
- document upload and text extraction;
- Gemini-based prioritisation;
- authentication and guest-to-account continuity;
- saved analysis history;
- cross-domain skill extraction and normalisation;
- Gemini timeout and fallback handling;
- low-coverage AI-assisted analysis;
- bilingual PDF roadmap export;
- Railway production deployment;
- PostgreSQL production database;
- cross-platform PDF compatibility improvements.

The Gemini references above describe the historical implementation. The current integration has since migrated to DeepSeek through the OpenAI-compatible API, preserving the existing business contracts and deterministic analysis.

Cross-domain testing exposed limitations in the original IT-focused skill catalogue, which led to redesign of the skill extraction and normalisation approach.

Further testing also showed that a job description with very low deterministic skill coverage should not be treated as a genuine zero match. A separate low-coverage AI-assisted workflow was therefore introduced.

---

## Testing

The latest full automated test run after the DeepSeek migration passed:

**345 tests**, including **69 AI service and boundary tests**. The original submission had 333 passing tests.

AI tests use SDK mocks or a local HTTP mock transport and do not require a real API key or external AI requests. The real DeepSeek API has also been validated locally for prioritisation and learning-roadmap generation.

Run the test suite with:

```bash
python manage.py test
```

For complete setup instructions, see SoftwarePrereqs.txt.
For the project module and AI-assistance listing, see CodeList.txt.
