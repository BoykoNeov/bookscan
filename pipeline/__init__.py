"""bookscan processing pipeline.

Staged, per-page, artifact-driven. Every stage is an independently runnable
CLI (``python -m pipeline.stageNN jobs/<job_id>/<page>/``) that reads only the
previous stage's artifacts and writes its own numbered subfolder. All
inter-stage data conforms to ``pipeline.page_model``.

See CLAUDE.md ("the stage contract") for the rules every stage must obey.
"""
