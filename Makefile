.PHONY: test syntax doctor install install-dry-run groq-test clean-artifacts build-root-indexes build-marketplace build-skillshare-hub build-claude-custom-skill build-packages verify-skill-metadata verify-packages verify-source-clean release-dry-run public-check ci-local

AUDIO ?=
PYTHON ?= python3
SKILL ?=

test:
	@set -e; \
	if [ -d tests ]; then \
		echo "testing tests"; \
		PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_*.py'; \
	fi; \
	for test_dir in packages/*/tests; do \
		[ -d "$$test_dir" ] || continue; \
		echo "testing $$test_dir"; \
		PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s "$$test_dir" -p 'test_*.py'; \
	done

syntax:
	@files="$$(find packages scripts -path '*/__pycache__' -prune -o -name '*.py' -print)"; \
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/check-python-syntax.py $$files
	bash -n scripts/*.sh packages/*/skills/*/scripts/*.sh
	@if command -v node >/dev/null 2>&1 && [ -f .opencode/plugins/agent-tools.js ]; then \
		node --check .opencode/plugins/agent-tools.js; \
	fi

doctor:
	$(PYTHON) packages/watch-video/skills/watch-video/scripts/doctor.py

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

clean-artifacts:
	rm -rf .dist

build-marketplace:
	./scripts/build-marketplace.sh

build-skillshare-hub:
	$(PYTHON) scripts/build-skillshare-hub.py

build-root-indexes:
	./scripts/build-root-indexes.sh

build-claude-custom-skill:
	./scripts/build-claude-custom-skill.sh

build-packages:
	./scripts/build-packages.sh

verify-skill-metadata:
	$(PYTHON) scripts/verify-skill-metadata.py

verify-packages:
	./scripts/verify-packages.sh

verify-source-clean:
	@set -e; \
	tmp_dir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp_dir"' EXIT; \
	cp .claude-plugin/marketplace.json "$$tmp_dir/marketplace.json.before"; \
	cp skillshare-hub.json "$$tmp_dir/skillshare-hub.json.before"; \
	find skills commands -mindepth 1 -maxdepth 1 -type l -print -exec readlink {} \; | sort > "$$tmp_dir/root-indexes.before"; \
	$(MAKE) build-root-indexes build-marketplace build-skillshare-hub >/dev/null; \
	diff -u "$$tmp_dir/marketplace.json.before" .claude-plugin/marketplace.json; \
	diff -u "$$tmp_dir/skillshare-hub.json.before" skillshare-hub.json; \
	find skills commands -mindepth 1 -maxdepth 1 -type l -print -exec readlink {} \; | sort > "$$tmp_dir/root-indexes.after"; \
	diff -u "$$tmp_dir/root-indexes.before" "$$tmp_dir/root-indexes.after"; \
	echo "source package indexes are current"

release-dry-run:
	@if [ -z "$(SKILL)" ]; then \
		echo "usage: make release-dry-run SKILL=watch-video"; \
		exit 2; \
	fi
	$(PYTHON) scripts/bump-skill-version.py "$(SKILL)" --dry-run

public-check:
	$(MAKE) test
	$(MAKE) syntax
	$(MAKE) clean-artifacts
	$(MAKE) build-packages
	$(MAKE) verify-skill-metadata
	$(MAKE) verify-packages
	$(MAKE) verify-source-clean
	git diff --check
	$(MAKE) install-dry-run

ci-local: public-check
