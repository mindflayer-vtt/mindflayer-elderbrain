// Fixed guidance only: never render private journal errors, credentials or paths
// supplied by a failed subprocess as recovery instructions.
export function installationRecovery(stage?: string, firmwareWritten = true): string[] {
  const retain = "Keep the full installation ID and its private recovery records. Do not delete server credentials, erase flash, or enable foreign adoption to bypass a failure.";
  switch (stage) {
    case "preflight":
      return ["Check that the server supports protocol v3, the trusted release is available, and the selected USB cable and port are connected. No firmware write has started.", "Refresh ports and release information after correcting the cause, then start a new installation."];
    case "backup-provisioning":
      return ["Firmware writing has not started. Check USB power and the data cable. Close any serial monitor; the installer requires exclusive access.", "If this board needs manual boot/reset handling, follow its board-specific procedure. Do not erase provisioning to make detection succeed.", "Retry only after confirming the same keypad is connected."];
    case "prepare-provisioning":
      return ["Firmware writing has not started. Check saved Wi-Fi and appliance settings. A foreign keypad requires deliberate adoption; corrupt provisioning requires manual recovery, not adoption.", retain];
    case "register-credential":
      return ["Firmware writing has not started, but a new server credential may already exist. Have an administrator inspect the retained plan and server registration before retrying.", retain];
    case "flash-firmware":
      return ["Firmware may be incomplete. Wait until no host job is active, keep the same keypad connected, and preserve stable USB power.", "Have an administrator inspect the original provisioning backups and chip MAC before a controlled reinstall. Do not copy sectors from another keypad or run a whole-chip erase.", retain];
    case "serial-provisioning":
      return [firmwareWritten
        ? "Firmware was written, but provisioning may or may not have been accepted. Wait until no host job is active, then check whether the keypad reconnects and which identity appears in inventory."
        : "Firmware was not changed, but provisioning may or may not have been accepted. Check whether the keypad reconnects and which identity appears in inventory before retrying.", "Have an administrator inspect the exact retained provisioning plan before retrying; generating another identity can leave an unused server credential.", retain];
    case "verify-online":
      return ["Serial provisioning was accepted, but authenticated online verification did not finish. Check Wi-Fi coverage, saved SSID/password, the reachable appliance address and port, and server health.", "Check inventory for the expected identity and firmware. A connected indicator alone does not prove the saved configuration. This failed job is not automatically marked complete by a later connection.", "Correct connectivity first; do not immediately reflash a keypad that may already be configured.", retain];
    default:
      return ["The last safe stage is unknown. Wait until no host job is active and have an administrator inspect the retained records before any retry.", retain];
  }
}
