# Contributing

Curricarta is in an early stage; interfaces and the data model still change. Issues and questions are
welcome. For larger changes, open an issue first so the direction can be agreed on.

## Working on the code

- Setup, tests and the local Compose stack are described in the [README](README.md) (German).
- Code, comments and commit messages are English. The user interface and its texts are German and go
  through the i18n layer (`frontend/src/i18n/de.ts`).
- Tests first: a change comes with a test that failed before it.
- Before a pull request, in `backend/`: `ruff check .`, `ruff format --check .`,
  `mypy app tests ../deploy/make-secrets.py`, `pytest`; in `frontend/`: `eslint .`, `vue-tsc -b`,
  `vitest run`.
- The interface keeps to WCAG 2.2 AA: keyboard operation, visible focus, loading, empty and error states.

## Data

- No curriculum texts of third parties and no data fetched from MEM-Schule in the repository, an image
  or the CI. Test fixtures are synthetic (`backend/tools/mem_synth.py`); a guard test enforces it.
- No secrets, tokens or personal data in code, tests, logs or issues.

## Licence

Contributions are accepted under the licence of the part they change: Apache-2.0 for code, CC BY 4.0
for the ontology and the project's own data, and the licences [NOTICE](NOTICE) names for the parts by
others.
