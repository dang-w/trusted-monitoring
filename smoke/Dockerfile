# Sandbox image for the smoke test: a plain Python image with a non-root user.
FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 1000 agent
USER agent
WORKDIR /home/agent
