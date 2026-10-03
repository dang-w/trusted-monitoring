# Sourced by the wrappers in this directory. Not executable on its own.
#
# The Python environment lives outside the home directory. Inspect writes the text of every error
# into the log, with a traceback that names the files of the installed packages; with the default
# `.venv` inside the repository that text holds the home-directory path, which the scrub check
# refuses (D14.2: an interrupted run's `eval-retry` log carried it in its journal). `uv` reads
# UV_PROJECT_ENVIRONMENT. /opt/homebrew/var belongs to the Homebrew user, so no sudo is needed.
: "${UV_PROJECT_ENVIRONMENT:=/opt/homebrew/var/pail/trusted-monitoring-venv}"
export UV_PROJECT_ENVIRONMENT
