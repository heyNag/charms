.PHONY: dev-deps test test-tooling test-plugins syntax lint shellcheck links validate whitespace \
	check coverage ci doctor groq-test

AUDIO ?=
PYTHON ?= python3
SHELL_SCRIPTS = scripts/*.sh packages/*/skills/*/scripts/*.sh

# Install exactly what requirements-dev.txt pins, into the current environment.
# pip check then fails if a pinned package needs one that the file does not
# list. Use a fresh virtual environment: pip check looks at every package in it.
dev-deps:
	$(PYTHON) -m pip install --no-deps --requirement requirements-dev.txt
	$(PYTHON) -m pip check

test: test-tooling test-plugins

# The release and validation tooling. Needs Python 3.11 or newer and the
# development dependencies.
test-tooling:
	@echo "testing tests"
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

# The plugins themselves. Standard library only, so this also runs on the
# oldest Python the plugins support: make test-plugins PYTHON=python3.9
test-plugins:
	@set -e; \
	for test_dir in packages/*/tests; do \
		[ -d "$$test_dir" ] || continue; \
		echo "testing $$test_dir"; \
		PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s "$$test_dir" -p 'test_*.py'; \
	done

syntax:
	@files="$$(find packages scripts tests -path '*/__pycache__' -prune -o -name '*.py' -print)"; \
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/check-python-syntax.py $$files
	bash -n $(SHELL_SCRIPTS)

lint:
	$(PYTHON) -m ruff check .

# ShellCheck comes with the development dependencies, as a program next to the
# interpreter they were installed for. One on PATH serves otherwise.
shellcheck:
	@program="$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')/shellcheck"; \
	[ -x "$$program" ] || program="$$(command -v shellcheck || true)"; \
	if [ -z "$$program" ]; then \
		echo "shellcheck is not installed. fix: make dev-deps" >&2; \
		exit 1; \
	fi; \
	echo "$$program $(SHELL_SCRIPTS)"; \
	"$$program" $(SHELL_SCRIPTS)

# The links between the documents. Links to other sites are not followed.
links:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/check-doc-links.py

validate:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_plugins.py

whitespace:
	git diff --check

check: test syntax lint shellcheck links validate whitespace

# Runs every test once more, under coverage.py, and fails when the total falls
# below the floor in pyproject.toml. Child processes are measured too. It is
# not part of `make check`, which would then run the tests twice.
coverage:
	@$(PYTHON) -m coverage erase
	@set -e; \
	for test_dir in tests packages/*/tests; do \
		[ -d "$$test_dir" ] || continue; \
		echo "measuring $$test_dir"; \
		PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m coverage run -m unittest discover -s "$$test_dir" -p 'test_*.py'; \
	done
	@$(PYTHON) -m coverage combine --quiet
	@$(PYTHON) -m coverage report

ci: check

doctor:
	$(PYTHON) packages/watch-video/skills/watch-video/scripts/doctor.py

groq-test:
	@if [ -z "$(AUDIO)" ]; then \
		echo "usage: make groq-test AUDIO=path/to/audio.mp3"; \
		exit 2; \
	fi
	./scripts/test-groq.sh "$(AUDIO)"
