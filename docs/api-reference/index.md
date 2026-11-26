# Python API reference

These typed entry points and rule types back the `punt` CLI. See the [punt-kit
README](https://github.com/punt-labs/punt-kit#commands) for command-line usage.
Other Python modules house CLI implementation details.

::: punt_kit
    options:
      members: false

## Project setup and inspection

::: punt_kit.init.run_init

::: punt_kit.seed.run_seed

::: punt_kit.audit.run_audit

::: punt_kit.status.run_status

::: punt_kit.status.StatusInfo

::: punt_kit.doctor.run_doctor

::: punt_kit.doctor.CheckResult

## Enablement

::: punt_kit.enablement.PuntEnablement
    options:
      members:
        - __new__
        - enable
        - disable

::: punt_kit.enablement.EnablementReport

## Rule and configuration helpers

::: punt_kit.claude_md.ClaudeMdImport
    options:
      members:
        - __new__
        - append_would_be_fenced
        - is_registered
        - register
        - prune

::: punt_kit.claude_md.UNCLOSED_FENCE

::: punt_kit.claude_md.write_atomically

::: punt_kit.claude_permissions.PUNT_RULES

::: punt_kit.claude_permissions.PermissionChange

::: punt_kit.claude_permissions.ProjectPermissions
    options:
      members:
        - __new__
        - grant
        - revoke

::: punt_kit.permission_rules.PermissionRule

::: punt_kit.permission_rules.RuleSet

::: punt_kit.permission_rules.Tier

## Release and PII checks

::: punt_kit.release.run_release

::: punt_kit.pii_checkout.run_pii
