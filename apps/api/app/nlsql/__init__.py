"""Open-ended text-to-SQL agent (plan P1).

A model authors real ``SELECT`` SQL over the full ``treated_incident_reports``
table, made safe by a read-only DB role (KTD-1), a layered validator, and an
execute-observe-repair loop. This graduates from the bounded allow-list filter
in ``app/derived/`` (the "basics") to open-ended, model-authored SQL.

Local-first: P1 ships no public route. Drive it via ``python -m app.nlsql.cli``.
"""
