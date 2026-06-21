.PHONY: test syntax doctor install install-dry-run groq-test mcp-build clean-generated build-claude-plugin build-codex-skill build-agent-skill build-claude-custom-skill build-packages rebuild-generated verify-packages audit-generated verify-generated-clean ci-local

AUDIO ?=
PYTHON ?= python3

test:
	@set -e; \
	for test_dir in packages/*/tests; do \
		[ -d "$$test_dir" ] || continue; \
		echo "testing $$test_dir"; \
		PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s "$$test_dir" -p 'test_*.py'; \
	done

syntax:
	@files="$$(find packages generated scripts -path '*/__pycache__' -prune -o -name '*.py' -print)"; \
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/check-python-syntax.py $$files
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

clean-generated:
	rm -rf .claude-plugin generated

build-claude-plugin:
	./scripts/build-claude-plugin.sh

build-codex-skill:
	./scripts/build-codex-skill.sh

build-agent-skill:
	./scripts/build-agent-skill.sh

build-claude-custom-skill:
	./scripts/build-claude-custom-skill.sh

build-packages:
	./scripts/build-packages.sh

rebuild-generated: clean-generated build-packages

verify-packages:
	./scripts/verify-packages.sh

audit-generated:
	@set -e; \
	for tool_json in packages/*/tool.json; do \
		package="$$(basename "$$(dirname "$$tool_json")")"; \
		./scripts/audit-generated.sh "$$package"; \
	done

verify-generated-clean:
	@$(MAKE) rebuild-generated >/dev/null
	@if ! git diff --exit-code -- .claude-plugin generated; then \
		echo "generated package outputs are stale; run make rebuild-generated and commit the results" >&2; \
		exit 1; \
	fi
	@if [ -n "$$(git ls-files --others --exclude-standard -- .claude-plugin generated)" ]; then \
		git ls-files --others --exclude-standard -- .claude-plugin generated >&2; \
		echo "generated package outputs are stale; run make rebuild-generated and commit the results" >&2; \
		exit 1; \
	fi

ci-local: test syntax mcp-build rebuild-generated verify-packages audit-generated verify-generated-clean install-dry-run
