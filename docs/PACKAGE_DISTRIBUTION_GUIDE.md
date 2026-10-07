# Release100 Private Package Distribution & Access Control Guide

This guide describes how to publish, distribute, and install **Release100 Core** and domain **Cartridges** as private Python packages.

---

## Architecture Overview

```
                      GITHUB ACTIONS CI/CD
                 (Triggered on Git Release / Tag)
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
       [Build Wheel .whl]              [Publish to Registry]
   - release100-core             GitHub Packages / Private Index
   - release100-temp-marker
   - release100-mail-organizer
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
        [Authorized QA/Tester]       [Unauthorized User]
        pip install release100-core  pip install release100-core
        ✅ 200 OK (Installed)         ❌ 401 Unauthorized
```

---

## 1. How You (Admin / Lead) Control Access

1. **Invite a Tester to your GitHub Repository / Organization:**
   - In GitHub: Go to **Settings > Collaborators > Add People** (or Organization > Teams).
   - Set permission to **Read**.
2. **Grant Package Access:**
   - The tester creates a GitHub Personal Access Token (Classic) with the `read:packages` permission.
3. **Revoking Access:**
   - Simply remove the user from your GitHub repository or organization.
   - Their token will immediately stop working for `pip install` and `pip update`.

---

## 2. Tester's 1-Time Setup (Zero URLs Thereafter)

The tester runs the setup script **once** on their machine:

### Windows (PowerShell):
```powershell
.\scripts\setup_private_pip.ps1 -GitHubUser "depali" -GitHubToken "ghp_xxxxxxxxxxxx" -Org "your-org"
```

### Linux / macOS:
```bash
./scripts/setup_private_pip.sh "depali" "ghp_xxxxxxxxxxxx" "your-org"
```

---

## 3. The Tester Experience (Clean Pip Commands)

From that point on, the tester never needs to know the repository URL, git branch, or file paths. They simply run:

```powershell
# 1. Install Core Platform
pip install release100-core

# 2. Install ONLY the cartridge(s) they are testing
pip install release100-cartridge-temperature-marker

# 3. Run the Platform
release100 run
```

---

## 4. Building Wheels Locally (For Manual / Offline Distribution)

To build all package wheels locally into `dist/wheels/`:

```powershell
python packaging/build_all_wheels.py
```

Generated artifacts:
- `release100_core-2.0.0-py3-none-any.whl`
- `release100_cartridge_temperature_marker-1.0.0-py3-none-any.whl`
- `release100_cartridge_mail_organizer-1.0.0-py3-none-any.whl`

---

## 5. Future Roadmap: Solution 2 (Public PyPI + License Gate)
*Planned Enhancement for Public Enterprise Edition:*
- Direct public hosting on `pypi.org` (`pip install apex-release100-core`).
- Access restriction managed via cryptographic license keys / tokens in `.env` (`RELEASE100_LICENSE_KEY=...`).
