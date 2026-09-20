# Known issues

## Offline boot can fail when the RTC predates local TLS certificates

Status: open. Diagnosed on the physical Lenovo ThinkCentre M73 on 2026-09-20;
no corrective code has been implemented yet.

### Observed behavior

With Ethernet unavailable, the appliance remained at the local console without
starting the graphical interface. The retained boot journal showed:

- `systemd-networkd-wait-online` reached its intentional 30-second timeout;
- `elderbrain-stack.service` then failed every 30 seconds in `prepare-admin`;
- OpenSSL rejected the appliance's local administration certificate as not yet
  valid;
- graphics, management, baseline finalization and backup retry did not start
  because they depend on the stack; and
- one fully offline boot accumulated 207 failed stack starts without recovery.

On the following boot, Ethernet acquired DHCP after approximately 155 seconds.
Chrony advanced the system clock by approximately 4,725,579 seconds (55 days) at
161 seconds. The next stack retry succeeded and graphics started at 183 seconds.

The installed Compose file already uses immutable local image IDs with
`pull_policy: never`. Image downloading and the bounded network-online timeout
were therefore not the cause of this failure.

### Root cause

The hardware clock was earlier than the `notBefore` timestamps of both the local
administration CA and leaf certificate. `prepare-admin` performs a normal
`openssl verify` before starting the cached local stack. Without NTP, certificate
time validation could never succeed, so a bad RTC became a hard dependency on
Internet connectivity.

The RTC has since been synchronized. This reduces the immediate likelihood of a
repeat, but does not protect appliances with a depleted CMOS battery, a reset
firmware clock, or a fresh installation whose RTC is substantially behind.

### Required fix

Prefer restoring a conservative, authenticated last-known-good time floor early
in boot, before `prepare-admin` and other certificate consumers. The floor must:

- live in root-owned persistent appliance state and only move forward after a
  trustworthy clock synchronization;
- advance an earlier system clock, never move a plausible clock backwards;
- work without a carrier, DHCP, DNS or an external time source; and
- preserve normal certificate validity and expiry checks after the clock floor
  is established.

Certificate issuance with a deliberate bounded `notBefore` allowance may be an
additional defence, but it does not correct other clock-sensitive services. Do
not fix this by permanently passing `-no_check_time`, broadly ignoring TLS
validity periods, or silently generating a new trust anchor on every bad-clock
boot.

The graphical failure path should also be independent enough from the container
stack to display a local explanation when stack preparation fails. That is a
resilience improvement, not a substitute for making offline startup work.

### Closure evidence

Add a disposable-VM regression that first completes an online installation and
caches the immutable release, then shuts down, disconnects networking, moves the
RTC to before the local certificates' validity window, and boots again. The test
must prove within a bounded time that:

- the cached stack, management bridge and graphical session become active;
- local HTTPS is accepted by the appliance browser using the existing CA;
- no registry, DNS, DHCP or NTP response is required;
- certificate expiry and key/chain validation remain enforced; and
- reconnecting networking permits normal forward synchronization without
  replacing the appliance CA or losing configuration.

Keep this issue open until that complete offline cold-boot test passes.
