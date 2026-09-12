SHELL := /bin/bash
-include local.mk

.PHONY: help iso test lint compose-check setup-image test-iso
help:
	@printf '%s\n' \
	  'Mindflayer Elderbrain' \
	  '  make iso SSH_PUBLIC_KEY=~/.ssh/id_ed25519.pub  Build Ubuntu 26.04 appliance ISO' \
	  '  make test                                      Run unit/static tests' \
	  '  make compose-check                             Validate Compose configuration' \
	  '  make setup-image                               Build setup service image' \
	  '  make test-iso                                  Destructive QEMU test on a temporary disk' \
	  '' \
	  'Build dependencies: bash, curl, gpg, xorriso, rsync, unsquashfs, sha256sum' \
	  'QEMU dependencies: qemu-system-x86_64, qemu-img, ssh, ssh-keygen'

iso:
	@SSH_PUBLIC_KEY="$(SSH_PUBLIC_KEY)" SMTP_CONFIG="$(SMTP_CONFIG)" DEV_ALLOW_NO_SSH_KEY="$(DEV_ALLOW_NO_SSH_KEY)" ./iso/build.sh

test:
	@cd setup && npm test
	@python3 -m unittest discover -s test -p 'test_*.py' -q
	@./test/static.sh

lint:
	@cd setup && npm run lint
	@./test/static.sh

compose-check:
	@docker compose --env-file config/defaults/appliance.env -f compose/compose.yaml config --quiet

setup-image:
	@docker build -t elderbrain-setup:dev setup

test-iso:
	@./test/qemu/test-iso.sh
