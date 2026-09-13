# Public release transition

Do not publish a release or change repository visibility until the private
baseline report identifies one exact, CI-green commit and its full-history audit
has passed. Perform the transition in this order:

1. Confirm local and remote `main` equal the audited commit.
2. Run `make public-audit` again and confirm its commit and pass result.
3. Make `mindflayer-vtt/mindflayer-elderbrain` public.
4. Immediately create or enable the `main` branch ruleset.
5. Require the green `test` status from the **CI** workflow.
6. Require changes through a pull request with at least one approving review.
7. Require review from CODEOWNERS for owned files.
8. Disable force pushes, including for administrators/bypass actors used normally.
9. Disable branch deletion.
10. Open the `appliance-release` GitHub Environment settings.
11. Require at least one approving reviewer for that Environment.
12. Retain exactly one deployment branch policy: branch `main`.
13. Add `APPLIANCE_RELEASE_SIGNING_PRIVATE_KEY` only as an Environment secret.
14. Run the documented public-key derivation check against
    `config/releases/appliance-release-public.pem` without printing the private key.
15. Confirm no repository or organization Actions secret duplicates that signing key.
16. In **Packages → mindflayer-elderbrain-setup → Package settings**, change
    package visibility to public if necessary. Log out of GHCR and verify an
    anonymous manifest inspection/pull of the immutable release digest succeeds.
17. Only after every preceding gate passes, approve and publish the first signed update.

The appliance deliberately has no GitHub credential. Repository visibility and
anonymous GHCR access are therefore release correctness requirements, not merely
distribution preferences.

## First public update: `0.1.1` / sequence 2

Start with the recorded private ISO baseline at `0.1.0`, release sequence `1`.
Make one harmless, visible release-identity change and allow its pull request and
CI to exercise the new protections. Do not use a security behavior change as the
update marker. Dispatch **Appliance release** from the protected `main` commit with:

```text
version: 0.1.1
release_sequence: 2
notes: Public-channel qualification update with an observable release marker.
```

After Environment approval, independently validate publication before involving
the baseline appliance:

1. Confirm tag `v0.1.1` targets the intended commit and the release is stable/latest.
2. Confirm it has exactly `manifest.json`, `manifest.sig`,
   `elderbrain-host.tar.zst`, and `elderbrain-dependencies.tar.zst`.
3. Download the manifest and signature without authentication and verify them
   with `config/releases/appliance-release-public.pem`.
4. Inspect the signed manifest: version `0.1.1`, release sequence `2`, matching
   host version, an immutable Setup digest, and digest-pinned runtime images.
5. With Docker logged out, inspect or pull the Setup image by that exact digest.
6. Fetch every `releases/latest/download/` asset without authentication.

Then use the baseline appliance's System page to check for updates, inspect the
version/sequence/notes, and explicitly confirm the update and downtime. Observe
the persistent job through authenticated download, offline preparation,
mandatory pre-update checkpoint, activation, service health, activation commit,
recovery-selector advancement, policy advancement, and terminal completion.
Confirm application data survived and the installed version/accepted sequence
are `0.1.1`/`2`. Reboot, block outbound Internet, and prove the updated appliance
boots fully from local state.

Finally, in a disposable VM, rerun at least one existing update interruption
injection using the actual public GitHub Release artifacts rather than the local
synthetic server. Reboot and verify deterministic recovery convergence. Record
the release, injection point, final version/sequence, job result, and health
evidence without credentials.
