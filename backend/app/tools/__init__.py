"""The function-calling surface exposed to the model. The composition layer.

MAY IMPORT:  domain, policy, repo, ledger, market, notify.
IMPORTED BY: voice.

Deliberately the widest node in the graph: this is where a model-proposed action meets
policy.evaluate(). One directory answers "what can the model do?" via `ls`.

Every tool here is `propose_*` or a read. No tool mutates state without a policy gate,
and adding one is an architectural decision — flag it in the PR, don't just ship it.
"""
