# Interrupted keypad installation

Do not assume a failed job means nothing changed. The UI reports the last stage
saved **before** its operation. An interrupted operation may have completed even
though its success was never recorded. There is no automatic resume or rollback
of keypad flash, and a later online connection does not complete the failed job.

## First steps

1. Record the full installation ID from the failed job's recovery panel. Wait
   until no host job is active; a child flasher can retain the job lock after its
   parent stops. Never remove a lock to force another writer to run.
2. Keep the same keypad, adapter and stable USB power. Do not erase the chip,
   delete credentials, enable adoption as a workaround, or restore another
   keypad's sectors.
3. Preserve the root-private installation directory. With the default appliance
   paths it is `/var/lib/mindflayer-elderbrain/keypad-installations/<full-job-id>`.
   A custom `ELDERBRAIN_STATE_DIR` changes the prefix. A complete appliance backup
   includes these records; use encrypted export when moving secrets off-device.
4. An administrator should inspect these records locally, not paste them into
   chat, logs or an issue. `installation.json` contains the saved settings and,
   if preparation finished, the exact device identity, credential and envelope.
   `serial/hardware.json` contains the inspected chip MAC;
   `serial/original-provisioning/` contains original sectors and checksums.
   `serial/serial.stdout` and `serial/serial.stderr` contain private diagnostics.
   Early failures may leave only some of these files. Preserve all of them.

## Choose the next action from the last stage

| Stage | What may have changed | Next action |
| --- | --- | --- |
| `preflight` | No firmware write | Check server protocol-v3 support, signed release availability and USB selection. Correct the cause, refresh and retry. |
| `backup-provisioning` | Reads/reset only; backups may be incomplete | Check data cable, power, exclusive serial access and board-specific boot/reset handling. Confirm the same keypad before retrying. |
| `prepare-provisioning` | No firmware write or credential registration | Check settings and local/foreign identity classification. Deliberate adoption applies only to a valid foreign configuration; corrupt sectors need manual review. |
| `register-credential` | The new credential may exist on the server | Compare the retained plan with the server's registration before retrying. Do not delete a credential that may be in use. |
| `flash-firmware` | rBoot, metadata or firmware may be partially written | Inspect original provisioning checksums, chip MAC and diagnostics before a controlled reinstall. Do not whole-chip erase. |
| `serial-provisioning` | Firmware was written; settings may have been accepted | Check online identity first and inspect the exact retained plan before retrying. A fresh install of a still-blank keypad can create another identity. |
| `verify-online` | Serial acknowledgement succeeded | Check Wi-Fi coverage, SSID/password, reachable appliance address/port and server health before considering another flash. Confirm authenticated identity, firmware and configuration proof, not just a connected indicator. |
| Missing/unknown | Cannot determine safely | Treat mutation as possible and inspect the retained records before retrying. |

A new installation is a new job, not a continuation of the old one. Local valid
identities are preserved, but an identity generated before a failed initial
provisioning can remain unused on the server. Retain that evidence for manual
review; do not automatically remove credentials as part of a retry.

Physical boot/reset procedures and recovery from interrupted writes still need
validation on each supported keypad board. Native tests and mocked serial
operations do not establish physical recovery readiness.
