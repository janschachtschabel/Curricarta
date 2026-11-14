"""The commands an operator runs to measure a document's quality, in the order run - each held once, here:
the dress rehearsal (tests/quality/test_rehearsal.py) runs every one of them word for word, so a command
that no longer does what its line says turns it red; the README's section "Güte messen" holds the same
lines (tests/quality/test_handout.py).

Each is written as the deployment runs it, from the repository's root: behind ``PREFIX``, with ``-T`` -
without it exec gives the command a terminal, which merges its words to the operator (stderr) into its
data (stdout), and a redirected sheet or report would hold log lines. "Word for word" means: the
rehearsal holds that each line begins with ``PREFIX`` and runs the rest of it in ``backend/``, as the
worker's image does. ``> file`` and ``< file`` are the shell's, and the files lie under
``data/gold-local/`` alone (app/quality/sheet.py ``LOCAL_FOLDER``). The words in angle brackets are what
the operator fills in."""

PREFIX = "docker compose -f deploy/docker-compose.yml exec -T worker "

_RUN = {
    "estimate": "python -m app.pipeline.estimate <Dokument-ID>",
    "usage": "python -m app.quality.usage_report <Dokument-ID> --label <Kennung> --raw",
    "draw_statements": (
        "python -m app.quality.sample <Dokument-ID> --kind statement --label <Kennung> --account <Konto>"
    ),
    "draw_blocks": (
        "python -m app.quality.sample <Dokument-ID> --kind block --label <Kennung> --account <Konto>"
    ),
    "sheet_statements": (
        "python -m app.quality.sheet --sample <Aussagen-Stichprobe> --base-url <Adresse>"
        " > data/gold-local/<Kennung>-aussagen.csv"
    ),
    "sheet_blocks": (
        "python -m app.quality.sheet --sample <Block-Stichprobe> --base-url <Adresse>"
        " > data/gold-local/<Kennung>-bloecke.csv"
    ),
    "judge_statements": (
        "python -m app.quality.judge --sample <Aussagen-Stichprobe> --account <Konto>"
        " < data/gold-local/<Kennung>-aussagen.csv"
    ),
    "judge_blocks": (
        "python -m app.quality.judge --sample <Block-Stichprobe> --account <Konto>"
        " < data/gold-local/<Kennung>-bloecke.csv"
    ),
    "report": "python -m app.quality.report --sample <Aussagen-Stichprobe> --sample <Block-Stichprobe>",
    "replay": "python -m app.pipeline.replay <Dokument-ID>",
    "report_replayed": (
        "python -m app.quality.report --sample <Aussagen-Stichprobe> --sample <Block-Stichprobe> --replayed"
    ),
    "mem_report": "python -m app.quality.mem_report <Dokument-ID> --label <Kennung>",
    "mem_report_endpoint": (
        "python -m app.quality.mem_report <Dokument-ID> --label <Kennung> --endpoint-counts"
    ),
}
COMMANDS = {name: PREFIX + line for name, line in _RUN.items()}
