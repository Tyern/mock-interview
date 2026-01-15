FROM python:3.11

# Open port 7860 for http service
ENV FAST_API_PORT=7860
EXPOSE 7860

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /bin/uv
# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy the application code
COPY ./assets assets
# Select the bot implementation by uncommenting the appropriate line
COPY \*.py .
# COPY ./bot-gemini.py bot.py
CMD LOCAL_RUN=1 uv run server.py --port ${FAST_API_PORT}
