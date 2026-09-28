# uv's own base image: ships the uv binary on top of a slim Python matching
# pyproject.toml's requires-python, so `uv sync` needs nothing extra installed.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Dependencies first, in their own layer, so editing application code doesn't
# invalidate the (slow) dependency-install layer on the next build.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Migrations are a deploy step, not something this container does on boot
# (see database.py / main.py's lifespan) — run `uv run alembic upgrade head`
# as the platform's pre-deploy/release command, separately from this CMD.
CMD ["uv", "run", "fastapi", "run", "main.py", "--port", "8000"]
