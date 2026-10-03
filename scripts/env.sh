# Sourced by the wrappers in this directory. Not executable on its own.
#
# The Python environment lives outside the home directory. Inspect writes the text of every error
# into the log, with a traceback that names the files of the installed packages; with the default
# `.venv` inside the repository that text holds the home-directory path, which the scrub check
# refuses (D14.2: an interrupted run's `eval-retry` log carried it in its journal). The same holds
# for the interpreter: a pyenv Python under the home directory puts its standard library into the
# traceback. So `uv` manages the Python too (`uv python install 3.12`), outside the home directory.
# /opt/homebrew/var belongs to the Homebrew user, so no sudo is needed.
: "${UV_PROJECT_ENVIRONMENT:=/opt/homebrew/var/pail/trusted-monitoring-venv}"
: "${UV_PYTHON_INSTALL_DIR:=/opt/homebrew/var/pail/python}"
: "${UV_PYTHON_PREFERENCE:=only-managed}"
export UV_PROJECT_ENVIRONMENT UV_PYTHON_INSTALL_DIR UV_PYTHON_PREFERENCE
