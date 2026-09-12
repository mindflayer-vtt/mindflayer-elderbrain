"""Entry point for the separately pinned host esptool environment."""
import esptool
import re
import sys


def require_mac(expected):
    if not re.fullmatch(r"[a-f0-9]{2}(?::[a-f0-9]{2}){5}", expected):
        raise ValueError("Invalid expected keypad MAC")
    # Guard inside the same esptool connection that performs each operation,
    # rather than trusting a separate probe followed by reopening the port.
    for operation in ("chip_id", "flash_id", "read_flash", "write_flash"):
        original = getattr(esptool, operation)
        def checked(esp, args, original=original):
            actual = ":".join(f"{byte:02x}" for byte in esp.read_mac())
            if actual != expected:
                raise esptool.FatalError("Keypad MAC changed since initial inspection; refusing serial operation")
            return original(esp, args)
        setattr(esptool, operation, checked)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--expected-mac":
        if len(sys.argv) < 3:
            raise SystemExit("Expected keypad MAC is required")
        require_mac(sys.argv[2])
        del sys.argv[1:3]
    esptool._main()
