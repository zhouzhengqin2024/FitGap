# FitGap

## AI-Assisted Skill-Gap Analysis and Learning Recommendations for International Students

FitGap is a bilingual web application developed as an MSc IT+ individual project at the University of Glasgow.

The system helps users compare a CV with a target job description, identify recognised skill matches and gaps, prioritise missing skills, and generate a personalised learning roadmap.

## Live Application

Production deployment:

https://fitgap-ai.up.railway.app/

---

## Core Features

- CV and job-description text input
- PDF, DOCX and TXT document extraction
- English and Simplified Chinese interface
- Deterministic skill extraction and normalisation
- Matched and missing skill identification
- Evidence-based skill-gap explanation
- Explainable match score
- Gemini-assisted skill prioritisation
- Gemini-assisted personalised learning roadmap
- Low-coverage AI fallback
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

Gemini is used for higher-level decision support, including:

1. prioritising identified skill gaps; and
2. generating personalised learning roadmaps.

This separation was chosen to improve explainability, predictability and testability while reducing reliance on generative AI for factual matching.

---

## Technology Stack

- Python
- Django
- HTML / CSS
- Bootstrap
- SQLite for local development
- PostgreSQL for production
- Google Gemini API
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
- `ai_prioritisation.py` — Gemini Call #1 for skill-gap prioritisation
- `ai_learning_roadmap.py` — Gemini Call #2 for learning-roadmap generation
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

Cross-domain testing exposed limitations in the original IT-focused skill catalogue, which led to redesign of the skill extraction and normalisation approach.

Further testing also showed that a job description with very low deterministic skill coverage should not be treated as a genuine zero match. A separate low-coverage AI-assisted workflow was therefore introduced.

---

## Testing

The final automated test suite contains:

**333 passing tests**

Run the test suite with:

```bash
python manage.py test
```

For complete setup instructions, see SoftwarePrereqs.txt.
For the project module and AI-assistance listing, see CodeList.txt.
