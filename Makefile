SHELL := /bin/bash
-include local.mk

.PHONY: help iso test lint workflow-lint public-audit compose-check setup-image test-iso
help:
	@printf '%s\n' \
	  'Mindflayer Elderbrain' \
	  '  make iso APPLIANCE_VERSION=1.0.0 APPLIANCE_RELEASE_SEQUENCE=1 SSH_PUBLIC_KEY=~/.ssh/id_ed25519.pub  Build appliance ISO' \
	  '  make test                                      Run unit/static tests' \
	  '  make workflow-lint                              Validate all GitHub Actions workflows' \
	  '  make public-audit                               Scan every remote ref and tracked file for secrets' \
	  '  make compose-check                             Validate Compose configuration' \
	  '  make setup-image                               Build setup service image' \
	  '  make test-iso                                  Destructive QEMU test on a temporary disk' \
	  '' \
	  'Build dependencies: bash, curl, git, gpg, xorriso, rsync, tar, unsquashfs, sha256sum' \
	  'QEMU dependencies: qemu-system-x86_64, qemu-img, ssh, ssh-keygen'

iso:
	@APPLIANCE_VERSION="$(APPLIANCE_VERSION)" APPLIANCE_RELEASE_SEQUENCE="$(APPLIANCE_RELEASE_SEQUENCE)" SSH_PUBLIC_KEY="$(SSH_PUBLIC_KEY)" \
	  SMTP_CONFIG="$(SMTP_CONFIG)" UPDATE_SOURCE_CONFIG="$(UPDATE_SOURCE_CONFIG)" \
	  UPDATE_PUBLIC_KEY="$(UPDATE_PUBLIC_KEY)" DEV_ALLOW_NO_SSH_KEY="$(DEV_ALLOW_NO_SSH_KEY)" \
	  DEV_ALLOW_DIRTY_WORKTREE="$(DEV_ALLOW_DIRTY_WORKTREE)" ./iso/build.sh

test:
	@cd setup && npm test
	@python3 -m unittest discover -s test -t . -p 'test_*.py' -q
	@./test/static.sh

lint: workflow-lint
	@cd setup && npm run lint
	@./test/static.sh

workflow-lint:
	@./test/actionlint.sh
	@if ./test/actionlint.sh test/fixtures/actionlint-invalid-context.yml >/dev/null 2>&1; then \
	  echo 'actionlint accepted the invalid runtime-context regression fixture' >&2; exit 1; \
	fi

public-audit:
	@./release/public-audit.sh

compose-check:
	@docker compose --env-file config/defaults/appliance.env -f compose/compose.yaml config --quiet

setup-image:
	@docker build -t elderbrain-setup:dev setup

test-iso:
	@./test/qemu/test-iso.sh
