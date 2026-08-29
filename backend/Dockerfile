# --- builder: install dependencies into a standalone venv with uv ---
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
# uv.lock pins every dependency, transitives included, so this image, CI, and a native
# venv all resolve to the same versions — no silent re-resolve like the one that pulled in
# anthropic 1.x and broke every `temperature=0` call site.
# `--locked`, not `--frozen`: both install strictly from the lock, but only --locked also
# errors when the lock is stale relative to pyproject.toml. --frozen skips that check, so a
# dependency added to pyproject without regenerating the lock would build green and simply
# be missing at runtime.
# `--no-install-project` installs dependencies only: the app is imported from /app at
# runtime rather than installed as a package, and skipping it keeps this layer cached
# across source-only changes.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-cache

# --- final: copy venv + source, run as non-root ---
FROM python:3.13-slim AS final

RUN useradd --create-home appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
