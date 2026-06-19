.PHONY: test syntax doctor install install-dry-run groq-test mcp-build build-claude-plugin build-codex-skill build-packages verify-packages verify-generated-clean ci-local

AUDIO ?=
PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s packages/watch-video/tests -p 'test_*.py'

syntax:
	python3 -m py_compile packages/watch-video/scripts/*.py
	bash -n scripts/*.sh

doctor:
	$(PYTHON) packages/watch-video/scripts/doctor.py

install:
	./scripts/install-all.sh

install-dry-run:
	DRY_RUN=1 ./scripts/install-all.sh

groq-test:
	@if [ -z "$(AUDIO)" ]; then \
		echo "usage: make groq-test AUDIO=path/to/audio.mp3"; \
		exit 2; \
	fi
	./scripts/test-groq.sh "$(AUDIO)"

mcp-build:
	npm --prefix mcp/watch-video run build

build-claude-plugin:
	./scripts/build-claude-plugin.sh

build-codex-skill:
	./scripts/build-codex-skill.sh

build-packages:
	./scripts/build-packages.sh

verify-packages:
	./scripts/verify-packages.sh

verify-generated-clean:
	@$(MAKE) build-packages >/dev/null
	@if ! git diff --exit-code -- .claude-plugin/marketplace.json plugins codex; then \
		echo "generated package outputs are stale; run make build-packages and commit the results" >&2; \
		exit 1; \
	fi
	@if [ -n "$$(git ls-files --others --exclude-standard -- .claude-plugin/marketplace.json plugins codex)" ]; then \
		git ls-files --others --exclude-standard -- .claude-plugin/marketplace.json plugins codex >&2; \
		echo "generated package outputs are stale; run make build-packages and commit the results" >&2; \
		exit 1; \
	fi

ci-local: test syntax mcp-build build-packages verify-packages verify-generated-clean install-dry-run
