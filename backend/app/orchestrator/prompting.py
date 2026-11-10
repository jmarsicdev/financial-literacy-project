# turns governance guidance + glossary + ontology + evidence into chat messages
from __future__ import annotations

from ..rag_governance.evidence import RetrievalContext
from ..rag_governance.governance_pipeline import GenerationMode, RequestGovernanceResult

ROLE = (
    "You are an educational financial-literacy assistant for beginner investors. "
    "You explain concepts, describe how products work, and summarize what sources say. "
    "You are not a financial adviser and never tell the user what to do with their money."
)

# policy.md section 4.3, neutral language
LANGUAGE_RULES = [
    "Use neutral wording: 'factors investors commonly evaluate', 'historically', 'one consideration is'.",
    "Never write 'you should buy/sell/hold', 'I recommend', 'the best investment for you', or promise returns.",
    "Do not call any investment suitable, right, or ideal for the user.",
    "Distinguish definitions, historical facts, current data, and opinions from sources.",
]

CITATION_RULES = [
    "Every factual statement about a security, price, return, revenue, earnings, or market event must end with a citation marker like [1] that refers to the numbered Sources list.",
    "Only cite sources from the list, and only for claims they actually support. Never invent numbers, dates, or sources.",
    "If the sources do not cover part of the question, say so plainly instead of guessing.",
    "Keep the answer under 250 words, in short paragraphs, written for a beginner.",
]

MODE_BLOCKS = {
    GenerationMode.STANDARD: (
        "Mode: educational explanation. Start from the SEC glossary definitions in Sources, then add context from the other sources."
    ),
    GenerationMode.CITED_INFORMATION: (
        "Mode: cited information. Lead with what the Sources say, with a citation on every factual sentence. "
        "State the date of any price or figure you mention."
    ),
    GenerationMode.SAFE_REDIRECT: (
        "Mode: safe redirect. The user asked for a personal recommendation. Do not give one and do not hint at one. "
        "Explain the factors and risks a person in that situation commonly considers, point to the SEC glossary definitions in Sources, "
        "and suggest they consult a licensed professional for personal decisions. "
        "Cite the SEC glossary definitions from Sources where relevant."
    ),
}

STRICT_BLOCK = (
    "A previous draft was rejected for advice-like language. Rewrite without any second-person directive: "
    "no 'you should', 'you ought to', 'I recommend', no allocation percentages for the user, no guarantees."
)


def build_messages(
    query: str,
    governance: RequestGovernanceResult,
    context: RetrievalContext | None,
    *,
    strict: bool = False,
) -> list[dict[str, str]]:
    system_parts = [ROLE, "", "Language rules:"]
    system_parts += [f"- {rule}" for rule in LANGUAGE_RULES]
    system_parts += ["", "Citation rules:"]
    system_parts += [f"- {rule}" for rule in CITATION_RULES]
    if governance.guidance:
        system_parts += ["", "Governance guidance for this request:"]
        system_parts += [f"- {line}" for line in governance.guidance]
    mode_block = MODE_BLOCKS.get(governance.generation_mode)
    if mode_block:
        system_parts += ["", mode_block]
    if strict:
        system_parts += ["", STRICT_BLOCK]

    user_parts = [f"Question: {query.strip()}", ""]

    if context is not None and context.ontology.relationships:
        user_parts.append("Related financial concepts (for context, not citations):")
        for rel in context.ontology.relationships:
            desc = f" — {rel.description}" if rel.description else ""
            user_parts.append(f"- {rel.source_name} {rel.relationship_type.replace('_', ' ')} {rel.target_name}{desc}")
        user_parts.append("")

    if context is not None and context.evidence_chunks:
        user_parts.append("Sources:")
        for chunk in context.evidence_chunks:
            meta = ", ".join(
                part for part in (
                    chunk.publisher or chunk.source_domain,
                    f"published {chunk.publication_date[:10]}" if chunk.publication_date else "",
                ) if part
            )
            user_parts.append(f"[{chunk.citation_id}] {chunk.title} ({meta})")
            user_parts.append(f"    {chunk.supporting_text.strip()[:1200]}")
        user_parts.append("")
    else:
        user_parts.append("Sources: none. Say plainly that no sources were found and keep the answer general.")
        user_parts.append("")

    user_parts.append("Write the answer now.")

    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
