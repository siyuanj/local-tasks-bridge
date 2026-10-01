# Developer tasks for Local Tasks Bridge. Run `make` or `make help` for the list.
# Compatible with the GNU Make 3.81 that ships with macOS.

SHELL := /bin/bash

PYTHON ?= python3
ARCH ?= $(shell uname -m)
PACKAGE_ARCH ?= all
BUILD_DIR ?= build
SWIFTC ?= swiftc
MACOS_MIN ?= 13.0
# bash used for `bash -n`; /bin/bash is 3.2 on macOS, the version users run.
LINT_BASH ?= /bin/bash
# Set to 1 (as CI does) to fail `make lint` when shellcheck or actionlint is missing.
LINT_REQUIRE ?= 0
# Extra arguments, for example: make install INSTALL_ARGS="--embed-python --no-open"
INSTALL_ARGS ?=
UNINSTALL_ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help test test-e2e lint helpers app app-universal python package install uninstall clean

help: ## Show this list of targets
	@printf 'Local Tasks Bridge developer targets:\n\n'
	@awk 'BEGIN { FS = ":.*## " } /^[a-z0-9-]+:.*## / { printf "  make %-14s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf '\nVariables: PYTHON=%s ARCH=%s PACKAGE_ARCH=%s\n' '$(PYTHON)' '$(ARCH)' '$(PACKAGE_ARCH)'

test: ## Run all Python tests (unit and end-to-end)
	$(PYTHON) -B -m unittest discover -s tests -t .

test-e2e: ## Run only the end-to-end tests (test_e2e*.py)
	$(PYTHON) -B -m unittest discover -s tests -t . -p 'test_e2e*.py'

lint: ## bash -n and shellcheck on every shell script, actionlint, Python syntax
	@status=0; \
	scripts=(); \
	while IFS= read -r file; do \
	  [ -f "$$file" ] || continue; \
	  case "$$file" in \
	    *.sh) scripts+=("$$file") ;; \
	    *) if head -n 1 "$$file" 2>/dev/null | grep -Eq '^#!.*[/ ](ba)?sh([[:space:]]|$$)'; then scripts+=("$$file"); fi ;; \
	  esac; \
	done < <(if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
	           git ls-files --cached --others --exclude-standard; \
	         else \
	           find . -type f ! -path './.git/*' ! -path './build/*' ! -path './dist/*' | sed 's|^\./||'; \
	         fi | LC_ALL=C sort -u); \
	for file in "$${scripts[@]}"; do \
	  $(LINT_BASH) -n "$$file" || status=1; \
	done; \
	printf 'bash -n (%s): %s scripts\n' "$(LINT_BASH)" "$${#scripts[@]}"; \
	if command -v shellcheck >/dev/null 2>&1; then \
	  shellcheck "$${scripts[@]}" && printf 'shellcheck: clean\n' || status=1; \
	elif [ "$(LINT_REQUIRE)" = "1" ]; then \
	  printf 'shellcheck is required but not installed.\n' >&2; status=1; \
	else \
	  printf 'shellcheck not found; skipped (brew install shellcheck).\n'; \
	fi; \
	if command -v actionlint >/dev/null 2>&1; then \
	  actionlint && printf 'actionlint: clean\n' || status=1; \
	elif [ "$(LINT_REQUIRE)" = "1" ]; then \
	  printf 'actionlint is required but not installed.\n' >&2; status=1; \
	else \
	  printf 'actionlint not found; skipped (brew install actionlint).\n'; \
	fi; \
	python_files=(engine/*.py); \
	while IFS= read -r file; do python_files+=("$$file"); done < <(find tests -name '*.py' 2>/dev/null | LC_ALL=C sort); \
	$(PYTHON) -B -c 'import sys; [compile(open(p, "rb").read(), p, "exec") for p in sys.argv[1:]]' "$${python_files[@]}" \
	  && printf 'Python syntax: %s files\n' "$${#python_files[@]}" || status=1; \
	exit $$status

helpers: ## Compile the two Reminders helpers into build/helpers for ARCH
	@mkdir -p $(BUILD_DIR)/helpers
	$(SWIFTC) -O -target $(ARCH)-apple-macos$(MACOS_MIN) -o $(BUILD_DIR)/helpers/ltb-reminders-export macos/Helpers/RemindersExport.swift
	$(SWIFTC) -O -target $(ARCH)-apple-macos$(MACOS_MIN) -o $(BUILD_DIR)/helpers/ltb-reminders-apply macos/Helpers/RemindersApply.swift

app: ## Build "Local Tasks Bridge.app" for ARCH into build/ (no embedded Python)
	scripts/build-app.sh --output $(BUILD_DIR) --arch $(ARCH)

app-universal: ## Build a universal (arm64 + x86_64) app into build/
	scripts/build-app.sh --output $(BUILD_DIR) --arch universal

python: ## Download and prune the embedded Python into build/python/ARCH
	scripts/fetch-python.sh --arch $(ARCH) --output $(BUILD_DIR)/python/$(ARCH)

package: ## Build release zips, SHA256SUMS and release-manifest.json into dist/
	scripts/package-release.sh --arch $(PACKAGE_ARCH)

install: ## Build this checkout and install it into ~/Applications
	./install.sh --from-source $(INSTALL_ARGS)

uninstall: ## Remove the installed app, its login item and the ltb link
	./install.sh --uninstall $(UNINSTALL_ARGS)

clean: ## Remove build outputs and dist/ (keeps downloads in build/cache)
	@if [ -d "$(BUILD_DIR)" ]; then find "$(BUILD_DIR)" -mindepth 1 -maxdepth 1 ! -name cache -exec rm -rf {} +; fi
	rm -rf dist
