.PHONY: test test-tooling test-plugins syntax lint validate whitespace check ci doctor groq-test

AUDIO ?=
PYTHON ?= python3

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
	bash -n scripts/*.sh packages/*/skills/*/scripts/*.sh

lint:
	$(PYTHON) -m ruff check .

validate:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/validate_plugins.py

whitespace:
	git diff --check

check: test syntax lint validate whitespace

ci: check

doctor:
	$(PYTHON) packages/watch-video/skills/watch-video/scripts/doctor.py

groq-test:
	@if [ -z "$(AUDIO)" ]; then \
		echo "usage: make groq-test AUDIO=path/to/audio.mp3"; \
		exit 2; \
	fi
	./scripts/test-groq.sh "$(AUDIO)"
