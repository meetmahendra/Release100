# ISSUE-009: Fail-Open Required Roles Lookup

**Status:** LOGGED / BACKLOG
**Severity:** MEDIUM
**Component:** `core_platform.app.rbac.permissions._get_required_roles`
**Date Logged:** 2026-10-07

## Problem

`_get_required_roles` catches every exception and returns an empty list when the plugin loader is not ready or the cartridge is not loaded. An empty list means "no roles required", so the role check fails open. Only the tenant-enabled check still applies.

## Impact

During start-up races or a cartridge load failure, role-protected routes may be reachable by authenticated users without the required role.

## Proposed Fix (not implemented)

Return a sentinel that denies (fail closed) and log the error with causal chaining. Add tests for loader-not-ready and unknown-app cases. The entitlement gate (Plan 10) is unaffected: it has its own fail-closed path under `enforce`.
