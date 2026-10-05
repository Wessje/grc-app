# AGENTS.md

Guidance for AI coding agents working in this repository.

## About the project

This is a **GRC (Governance, Risk & Compliance) tool** for managing:

- **Risks** – things that could go wrong, with likelihood, impact, owner, and treatment status.
- **Controls** – safeguards that reduce risk (e.g. MFA, backups, access reviews), mapped to the risks they address and, where relevant, to frameworks such as ISO 27001, NIST CSF, or SOC 2.
- **Assessments** – periodic reviews of risks and controls, recording findings, evidence, and outcomes.

The project is at an early stage. The build plan for the first feature (the risk register) is in `docs/plan.md`.

## Tech stack

- **Python 3.14** with **Django** (web framework) and **SQLite** (a database stored in a single local file, `grc.db`).
- Server-rendered HTML pages using Django templates, styled with one plain CSS file. No JavaScript framework.
- Each GRC module is its own Django "app" (folder): `risks` now; later e.g. `controls`, `assessments`, `vendors` (TPRM), `bia`.
- Use Django's built-in features (ORM, forms, migrations, authentication, admin) instead of adding extra libraries.
- Secret settings (`SECRET_KEY`, `DEBUG`) are read from `.env`; `.env.example` shows which settings are needed.
- Risks are archived, never deleted.

## Running the app

All commands are run from the project folder in Terminal. The virtual environment (`.venv`) is a private copy of Python for this project; activate it each time you open a new Terminal window.

```bash
# One-time setup
python3 -m venv .venv                 # create the virtual environment
source .venv/bin/activate             # activate it
pip install -r requirements.txt       # install Django and other libraries
cp .env.example .env                  # create your local settings file, then edit it
python manage.py migrate              # create/update the database tables
python manage.py createsuperuser      # create your login account

# Every time
source .venv/bin/activate             # activate the virtual environment
python manage.py runserver            # start the app at http://127.0.0.1:8000

# Useful extras
python manage.py makemigrations       # after changing a model: generate a migration
python manage.py migrate              # apply migrations to the database
python manage.py load_sample_risks    # load made-up sample risks
python manage.py test                 # run the automated tests
```

Stop the running app with `Ctrl + C`.

## About the user

The owner is a **Cyber GRC professional with limited coding experience**. They understand GRC concepts well, but not necessarily programming terms. Use GRC terminology freely; explain technical terminology.

## How to work

### Explain changes in plain language
- After every change, summarise in plain language **what** changed, **why**, and **how to try it out**.
- Avoid jargon. When a technical term is unavoidable, explain it briefly (e.g. "a *database migration* is a script that updates the structure of the database").
- Where it helps, relate concepts to GRC equivalents (e.g. "input validation works like a control that stops bad data getting in").

### Keep code simple
- Prefer clear, readable code over clever or compact code.
- Use descriptive names (`calculate_risk_score`, not `calc_rs`).
- Keep functions short and focused on one task.
- Avoid unnecessary libraries, frameworks, or abstractions. Only add a dependency when it clearly saves effort, and explain why.

### Add comments to code
- Start each file with a short comment explaining what the file is for.
- Comment each function to explain what it does, its inputs, and its output.
- Add comments explaining the *reasoning* behind non-obvious logic (e.g. how a risk score is calculated).

### Propose a plan before large changes
- For anything beyond a small, contained fix (e.g. new features, new files, database changes, adding dependencies, restructuring code), **first propose a plan and wait for approval**.
- A plan should list: the goal, the steps, the files that will be added or changed, and any risks or trade-offs.
- Small fixes (typos, a single-line bug fix) can be made directly, but should still be explained.

## Security and data handling

This tool will hold sensitive risk and control information, so follow good security practice:

- Never commit secrets, passwords, or API keys. Store them in `.env` files (already excluded by `.gitignore`).
- Never commit real organisational risk data; use made-up sample data for testing. The database file (`grc.db`) must stay excluded by `.gitignore`.
- Validate user input and use parameterised database queries.
- Point out any security implications of a change.
