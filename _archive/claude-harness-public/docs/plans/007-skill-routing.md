# Plan-007: Skill Routing

## Objective

Integrate Claude Code skills into the registry and routing system.

## Dependencies

- Plan-005 (Registry and Routing)

## Scope

1. Finalize `skills` section in `registry.yaml`
2. Add skill routing step to bootstrap Stage 2 (after module routing)
3. Skills with `tech_signals` matching the project profile are SUGGESTED to the user
4. Module-bound skills activate when their parent module activates

## Verification Criteria

- [ ] `registry.yaml` skills section lists all 3 existing skills
- [ ] Bootstrap Stage 2 includes skill routing after module routing
- [ ] React+TypeScript project → frontend-hook + zod-schema SUGGESTED
- [ ] Python-only project → no skills suggested
