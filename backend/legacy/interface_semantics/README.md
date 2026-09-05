# Legacy interface semantics

This directory preserves the retired workspace-specific interface semantic
implementation for migration history only. It is outside the
`context_router` package and is not imported by the application.

The active implementation lives in
`backend/src/context_router/interface_search/` and stores workspace vocabulary
as data rather than Python path/controller mappings.

Do not run the archived seed scripts against a database whose migration is at
or beyond `20260902_0074` because the legacy intent table and columns are no
longer part of the active schema.
