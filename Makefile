.PHONY: test syntax doctor install install-dry-run groq-test clean-artifacts build-root-indexes build-marketplace build-skillshare-hub build-claude-custom-skill build-packages sync-umbrella-version verify-skill-metadata verify-packages verify-source-clean verify-rebuilt-clean release-dry-run release-check public-check ci-local

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
	@if command -v node >/dev/null 2>&1 && [ -f .opencode/plugins/charms.js ]; then \
		node --check .opencode/plugins/charms.js; \
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
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/build-skillshare-hub.py

build-root-indexes:
	./scripts/build-root-indexes.sh

build-claude-custom-skill:
	./scripts/build-claude-custom-skill.sh

build-packages:
	./scripts/build-packages.sh

sync-umbrella-version:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/sync-umbrella-version.py

verify-skill-metadata:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/verify-skill-metadata.py

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

verify-rebuilt-clean:
	@set -e; \
	dirty="$$(git status --porcelain -- .claude-plugin/marketplace.json skillshare-hub.json skills commands)"; \
	if [ -n "$$dirty" ]; then \
		echo "$$dirty" >&2; \
		echo "generated package indexes changed after rebuild; run make build-packages and commit the results" >&2; \
		exit 1; \
	fi; \
	echo "rebuilt package indexes match committed source"

release-dry-run:
	@if [ -z "$(SKILL)" ]; then \
		echo "usage: make release-dry-run SKILL=watch-video"; \
		exit 2; \
	fi
	$(PYTHON) scripts/bump-skill-version.py "$(SKILL)" --dry-run

release-check:
	$(MAKE) test
	$(MAKE) syntax
	$(MAKE) clean-artifacts
	$(MAKE) build-packages
	$(MAKE) verify-skill-metadata
	$(MAKE) verify-packages
	$(MAKE) verify-source-clean
	git diff --check
	$(MAKE) install-dry-run

public-check:
	$(MAKE) release-check
	$(MAKE) verify-rebuilt-clean

ci-local: public-check
