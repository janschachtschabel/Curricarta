# Contributing

Curricarta is in an early stage; interfaces and the data model still change. Issues and questions are
welcome. For larger changes, open an issue first so the direction can be agreed on.

## Working on the code

- Setup, tests and the local Compose stack are described in the [README](README.md) (German).
- Code, comments and commit messages are English. The user interface and its texts are German and go
  through the i18n layer (`frontend/src/i18n/de.ts`).
- Tests first: a change comes with a test that failed before it.
- Before a pull request, in `backend/`: `ruff check .`, `ruff format --check .`,
  `mypy` (its files are listed in `pyproject.toml`), `pytest`; in `frontend/`: `eslint .`, `vue-tsc -b`,
  `vitest run`.
- The interface keeps to WCAG 2.2 AA: keyboard operation, visible focus, loading, empty and error states.

## Dependencies

- Lifting a backend package: change `backend/pyproject.toml` if its bound moves, run `uv lock` in
  `backend/`, then write both exports again with the two `uv export` commands of the README (they stand in
  the head of `deploy/requirements-api.txt` and `deploy/requirements-convert.txt`). The tests in
  `backend/tests/deploy/` (above all `test_requirements_export.py`) keep the exports equal to the lock.
  Frontend: change `frontend/package.json` and its lock, then `npm test`, `npm run lint`, `npm run build`.
- `.github/workflows/audit.yml` audits both exports with `pip-audit` (OSV) and the npm lock with
  `npm audit` (what ships from moderate on, the development tools from high on): weekly, by hand, and in
  every pull request that changes a lock, an export or the allowlist.
- An advisory that does not apply or cannot be lifted yet goes into `deploy/audit-allowlist.toml` with its
  id, package, reason, the date it was added and a review date at most 90 days later; its id is passed to
  `pip-audit` as `--ignore-vuln` on both audit steps of the workflow (a test keeps each step equal to the
  list). Once the review date has
  passed, a test fails: lift the package, or give a new reason and a new date.
- Dependabot opens security pull requests for the backend only. They change `uv.lock` alone and stay red
  on the export guard: check out the branch, run the two `uv export` commands, and push the exports to it.

## Data

- No curriculum texts of third parties and no data fetched from MEM-Schule in the repository, an image
  or the CI. Test fixtures are synthetic (`backend/tools/mem_synth.py`); a guard test enforces it.
- No secrets, tokens or personal data in code, tests, logs or issues.

## Licence

Contributions are accepted under the licence of the part they change: Apache-2.0 for code, CC BY 4.0
for the ontology and the project's own data, and the licences [NOTICE](NOTICE) names for the parts by
others.
