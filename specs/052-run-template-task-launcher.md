# 052 — Run Template / Task Launcher (P32)

Status: Complete
Date: 2026-06-07
Depends on: `specs/048-provider-model-launch-wiring.md`

## Backend

- `run_templates` SQLite table + `/run-templates` CRUD
- `GET /run-templates/{id}/preview` — truthful argv/provider/model
- `POST /sessions` accepts `template_id`; sessions record `source_template_id`

## Acceptance

Templates create/preview/launch; writes localhost-only (§2A)
