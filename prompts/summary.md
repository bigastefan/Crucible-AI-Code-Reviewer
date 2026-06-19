<!-- version: 1.0 | updated: 2026-06-19 -->

<!-- RENDER TEMPLATE (not a second LLM call), per plan A5. The single LLM call returns
     summary + overall_risk + findings; this template formats the posted summary COMMENT.
     {placeholders} are filled by the summary renderer in Phase 3. -->

### 🔥 Crucible review

{summary}

**Overall risk:** {overall_risk}

{findings_table}

<sub>Crucible is advisory during the pilot — it does not block merges. Reply to a comment to discuss.</sub>
