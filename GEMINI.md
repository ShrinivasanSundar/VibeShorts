# Coding Rules (Karpathy Guidelines)

Apply these four rules on every coding task. No exceptions unless the task is trivial.

## 1. Think Before Coding
- State assumptions explicitly before writing any code. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- Push back when a simpler approach exists.

## 2. Simplicity First
- Write the minimum code that solves the problem. Nothing speculative.
- No unrequested features, abstractions, flexibility, or error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes
- Touch only what the user's request requires. Do not improve adjacent code.
- Match existing style, even if you'd do it differently.
- Remove imports/variables/functions that **your** changes made unused. Leave pre-existing dead code alone unless asked.
- Every changed line must trace directly to the user's request.

## 4. Goal-Driven Execution
- Define verifiable success criteria before starting.
- For multi-step tasks, state a brief plan with a verify step for each.
- Loop until the criteria are met. Don't stop at "it should work".
