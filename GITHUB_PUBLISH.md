# Publish Daycraft to GitHub

This folder contains **source code and configuration**, not your personal schedules. The `.gitignore` is designed to exclude local SQLite databases, journals, logs, private `.env` files, dependencies and generated build artifacts.

## 1. Review before publishing

- Decide whether your new repository should be **private or public**. A public repository exposes source code and documentation, including any comments or test fixtures you commit.
- Review files for passwords, API keys, sensitive URLs, real user data or anything you do not want published. The packaging cleanup is not a comprehensive credential scanner.
- Your personal data and local installation must remain outside Git; **do not manually force-add the `data/` or `logs/` directories**.
- Select a license if you intend to grant others permission to use or modify the code. This distribution does not assume a license.

## 2. Create a new empty repository on GitHub

At https://github.com/new choose a repository name (for example `daycraft`). Choose visibility. **Do not** initialize the GitHub repository with a README, `.gitignore` or license; those can be managed in this source folder.

## 3. Push from PowerShell

Open PowerShell in the extracted project root (the directory with `README.md` and `Launch Schedule Builder.cmd`). Replace `YOUR_USERNAME` and `YOUR_REPOSITORY` with the actual GitHub values:

```powershell
git init
git branch -M main
git add .
git status
```

Review `git status` carefully before continuing. It should **not** show local databases, `.env` files, backup ZIP files or downloaded dependencies. If anything sensitive appears, remove it from the staging area before committing.

```powershell
git commit -m "Initial Daycraft source"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Authenticate using GitHub's browser/credential manager flow or an appropriate credential method. GitHub account passwords are not accepted directly for Git pushes. If Git says a remote or repository already exists, inspect `git remote -v` and the existing repository rather than blindly overwriting its contents.

## 4. Verify after publishing

Open your GitHub repository in the browser. Confirm the expected top-level files are present: `README.md`, `backend/`, `frontend/`, `scripts/`, `e2e/`, `docs/`, the launch `.cmd` files and `.env.example`. Confirm that private user data and environment directories are **absent**. You can then clone into a new test folder and launch the application to verify that a clean install works.

## Optional: update the repository later

From the same repository directory:

```powershell
git status
git add .
git commit -m "Describe the change"
git push
```

Run `git status` before each commit, particularly after using the backup tool or creating logs.
