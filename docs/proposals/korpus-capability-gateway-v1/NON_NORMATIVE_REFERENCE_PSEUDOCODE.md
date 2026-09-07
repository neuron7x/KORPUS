# Non-Normative Reference Pseudocode

```python
async def invoke_capability(req, runtime):
    inv = runtime.invocations.new(req)

    spec = runtime.registry.resolve_exact(req.capability_id, req.capability_version)
    if spec is None or not spec.enabled:
        return runtime.finalize_no_call(inv, "CAPABILITY_UNKNOWN")

    decision = await runtime.policy.authorize(
        runtime.policy_input.build(runtime.identity.current(), spec, req)
    )
    if decision.outcome != "ALLOW":
        return runtime.finalize_no_call(inv, "POLICY_DENIED")

    normalized = runtime.contracts.validate_input(spec, req.input)
    effect = runtime.effects.prepare(spec, req, normalized, decision)

    try:
        raw = await runtime.adapters.execute(spec, normalized, effect.context)
    except Timeout:
        return await runtime.effects.handle_timeout(inv, spec, effect)
    except Exception as exc:
        return runtime.finalize_failure(inv, map_provider_error(exc))

    output = runtime.contracts.validate_output(spec, raw.output)
    evidence = runtime.evidence.derive(spec, inv, output, raw.metadata)
    runtime.evidence.require_valid_if_needed(spec, evidence, output)

    audit_id = await runtime.audit.append(
        runtime.audit_record(inv, decision, output, evidence, effect)
    )
    return runtime.success(inv, output, evidence, audit_id)
```

Control ownership is the invariant: the orchestrator owns policy, contracts, effect guard,
evidence gate and final audit/result transition; the adapter does not.
