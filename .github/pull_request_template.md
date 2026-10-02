## Scope and result

- Scope:
- Result:

## Verification

- [ ] `make test`
- [ ] `make lint`
- [ ] `make app` (changes to `macos/`, `scripts/`, or `install.sh`)
- [ ] `scripts/test-install.sh` (changes to `install.sh`)
- [ ] GitHub Actions CI is green.

## Source and runtime safety

- [ ] No credentials, OAuth clients or tokens, sync state, exported task or reminder data, or logs are included.
- [ ] Deletion and completion limits, account binding, and credential isolation are unchanged, or the change is explained below.
- [ ] Impact on installed apps, the login item, or user data is described below, or this change has none.

Runtime/install impact:

Rollback:
