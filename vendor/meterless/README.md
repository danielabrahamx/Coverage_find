# Vendored Meterless reference engines

Pre-existing components, not written for Coverage Detective. Copied unchanged from
https://github.com/Meterless/Meterless at commit `1742dec56a66e58eef9dda2d2b865823758ca8cd` (cloned 26 Oct 2026):

| Folder | Upstream path | What it is |
|---|---|---|
| `hmem/` | `engines/hmem/reference` | H-MEM: memory records with confidence and provenance, append-only trust ledger |
| `world-model/` | `engines/world-model/reference` | World Model: event-sourced entities, relationships, facts, audit |

Licence: Apache License 2.0 (`LICENSE`, from the upstream repository root). Both are
deterministic, zero-runtime-dependency TypeScript reference implementations; they run with
`tsx`. Their own tests: `cd vendor/meterless/hmem && npm install && npm test` (same for
`world-model`). Coverage Detective uses them through `meterless_service/` (an HTTP service on
port 8100) and does not modify them.
