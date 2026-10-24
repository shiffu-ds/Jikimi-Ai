"""Apply the server's signed rule bundle on the edge (F11: "signed config on the edge").

Verification, key pinning and persistence are shared with the event calendar
(``jikimi_edge.config_sync``); a rule bundle is additionally refused if it carries a rule that
is unapproved or belongs to another site.
"""

from __future__ import annotations

from jikimi_contracts.rules_dsl import Rule, RuleBundle

from ...config_sync import SignedBundleSync


class RuleSync(SignedBundleSync[RuleBundle]):
    kind = "rules"
    path = "/v1/edge/rules"
    model = RuleBundle

    def payload(self, b: RuleBundle) -> list[Rule]:
        return b.rules

    def extra_refusal(self, b: RuleBundle) -> str | None:
        if any(not r.approved_by or r.site_id != self.site_id for r in b.rules):
            return "bundle contains an unapproved or foreign rule"
        return None
