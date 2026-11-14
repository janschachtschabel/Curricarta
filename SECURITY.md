# Security

Curricarta is pre-release software. Fixes land on `main`; there are no supported release branches yet.

## Reporting a vulnerability

Please do not open a public issue with the details. Use GitHub's private vulnerability reporting for
this repository (**Security → Report a vulnerability**). If that is not available to you, open an issue
that only asks for a private contact, without the details.

Helpful in a report: the affected route, job or file, the steps to reproduce, and what an attacker
gains. You will get an answer as soon as the report has been read; there is no bounty.

## Scope notes

- The service fetches addresses its accounts name (source register) and a configured SPARQL endpoint.
  Reports about reaching non-public addresses through it (SSRF) are in scope.
- Uploaded and fetched documents are untrusted input to the converter (PDF, DOCX, HTML, archives).
- Credentials are never part of this repository; `deploy/make-secrets.py` creates local ones.
- The locked Python and npm dependencies are audited for known advisories weekly and on every pull request
  that changes a lock (`.github/workflows/audit.yml`).
