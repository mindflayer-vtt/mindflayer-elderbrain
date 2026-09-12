"""Real loopback NFS/Borg smoke test; requires a disposable VM and nfs-kernel-server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def run(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=180)


def main():
    if sys.argv[1:] != ["--confirm-disposable-vm"] or os.geteuid() != 0:
        raise SystemExit("Requires root and --confirm-disposable-vm; never use on a real appliance")
    run("systemd-detect-virt", "--vm", "--quiet")
    run("systemctl", "is-active", "nfs-server.service")
    sys.path.insert(0, "/opt/mindflayer-elderbrain")
    import backup_archive
    from backup_uploads import UploadStore
    from borg_repository import BorgRepository

    # Only this VM's temporary export is added. Normal appliance settings, SSH
    # access, backup destinations and service data are not changed.
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="elderbrain-nfs-test-", dir="/var/tmp") as directory:
        root = Path(directory)
        export = root / "export"
        export.mkdir()
        state = root / "state"
        state.mkdir()
        mountpoint = root / "mount"
        configuration = Path("/etc/exports.d") / ("elderbrain-test-" + uuid.uuid4().hex + ".exports")
        configuration.parent.mkdir(mode=0o755, exist_ok=True)
        mounted = False
        try:
            with configuration.open("x") as output:
                output.write(f"{export} 127.0.0.1(rw,sync,no_subtree_check,no_root_squash)\n")
            run("exportfs", "-ra")
            repository = BorgRepository(state, Path("/opt/mindflayer-elderbrain"),
                                        identity="nfs-test", mountpoint=mountpoint)
            repository.settings.configure({"kind": "nfs", "host": "127.0.0.1", "export": str(export),
                                           "repository": "repository", "passphrase": "disposable-nfs-test-password"})
            repository.ensure_nfs(repository.settings.read())
            mounted = True
            repository.initialize()
            source = root / "source"
            source.mkdir()
            (source / "configuration.json").write_text('{"fixture":"NFS roundtrip"}')
            (state / "backups").mkdir()
            archive = state / "backups" / ("elderbrain-" + "a" * 32 + ".tar.zst")

            def snapshot(deadline):
                manifest = backup_archive.create(archive, {"elderbrain": source},
                                                 identity="nfs-test", version="nfs-test",
                                                 deadline=deadline)
                return {"archive": str(archive), "preview": backup_archive.preview(manifest)}

            repository.backup(snapshot)
            archives = repository.list_archives()
            assert len(archives) == 1, "Expected one NFS repository archive"
            result = repository.fetch_archive(archives[0]["name"])
            uploaded, _ = UploadStore(state / "uploads").verify(result["id"])
            assert uploaded.read_bytes() == archive.read_bytes(), "Retrieved backup differs"
            kit = json.loads(Path(repository.recovery_kit()["archive"]).read_text())
            assert kit["settings"]["export"] == str(export)
            # An already mounted but different export must never be accepted.
            try:
                repository.ensure_nfs({**repository.settings.read(), "export": str(root / "wrong-export")})
            except ValueError:
                pass
            else:
                raise AssertionError("Wrong NFS export was accepted")
            print("Verified real NFS mount, encrypted Borg backup/retrieval, recovery kit and wrong-export rejection")
        finally:
            # Never let TemporaryDirectory cleanup walk through a live mount.
            if mounted or subprocess.run(["mountpoint", "-q", str(mountpoint)]).returncode == 0:
                try:
                    run("umount", str(mountpoint))
                except Exception:
                    # Prevent recursive cleanup until an operator can unmount it.
                    print(f"Cannot unmount {mountpoint}; test files and export retained for diagnosis", file=sys.stderr, flush=True)
                    os._exit(2)
            configuration.unlink(missing_ok=True)
            run("exportfs", "-ra")


if __name__ == "__main__":
    main()
