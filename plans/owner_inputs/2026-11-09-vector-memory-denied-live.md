# Owner report (2026-11-09): Vector Memory section still denies access

Verbatim root-chat message:

> При заходе в Векторную память все так же нет доступа к разделу. Мой id 5885953495

## Binding interpretation

- This is a live acceptance failure of MOD-ACL-UX-01 M1 (deployed 2.58.173 @ 17c3a05e). Unit tests with synthetic roles proved the code path, but the real owner is still denied, so M1 rows must not stay VERIFIED.
- The owner supplied the real Telegram ID: 5885953495. Production facts about that account (role rows, role_type, permissions) and the exact denied request must be read rather than assumed.
- Owner is the account holder asking for this fix; that does not authorise fabricating an initData session. Diagnose by reading role rows, server logs for real 4xx responses, the served bundle, and by reproducing the same role state locally.
- Scope stays inside the existing ACL: no new ACL, no wildcard bypass, no widening for non-owners.
