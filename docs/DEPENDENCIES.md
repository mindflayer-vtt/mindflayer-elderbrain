# Dependency updates

Dependabot checks GitHub Actions, setup npm dependencies, the setup Docker base
image and the pinned Borgmatic/esptool Python requirements every Monday at 07:00 Europe/Berlin.
Python and npm minor/patch updates are grouped; majors remain separate. Security
updates have their own groups. No automatic merging or deployment is configured.
The configuration becomes active when merged to the repository's default branch.
GitHub-side execution and security-update settings have not been changed here.

`config/defaults/requirements.txt` includes the installer-consumed
`borgmatic-requirements.txt` so dependency discovery and production pins agree.
Run the full tests, including the opt-in Borg integrations, when changing these pins.

The image pins in `config/defaults/appliance.env`, coordinated Foundry/application
versions, Ubuntu ISO version, system packages and firmware release trust anchors
are intentionally reviewed as appliance releases. Do not assume Dependabot updates
arbitrary shell/environment-variable pins. Compose uses environment-provided image
values, so it is not configured as a second, misleading source of image updates.

The sibling keypad configuration covers npm release tooling, GitHub Actions and
PlatformIO Core via its shared `requirements.txt`. PlatformIO libraries/platforms,
pinned rBoot/esptool2 commits and firmware signing trust anchors remain manual.
The sibling server configuration covers npm, GitHub Actions and its Docker base.

Configuration options follow the [GitHub Dependabot reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
