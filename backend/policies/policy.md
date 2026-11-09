# Financial Literacy Assistant – Governance Policy

**Status:** Draft – Pending Team Review  
**Version:** 0.1  
**Owner:** Team 5 – RAG Governance Module  
**Last Updated:** November 8, 2026  
**Review Frequency:** At each major project release or when relevant policies change

---

## 1. Purpose

This policy defines governance requirements for the Team 5 Financial Literacy Assistant.

The application is an educational and financial research assistant intended primarily for beginner investors. It helps users understand financial terminology, explore market information, compare financial products, and locate reliable educational resources.

The application must not present itself as a financial adviser or provide personalized investment recommendations.

This policy establishes requirements for:
- User intent classification.
- Financial-advice guardrails.
- Retrieval-augmented generation (RAG).
- Source reliability and citation validation.
- Responsible presentation of financial information.
- Privacy and data handling.
- Policy evaluation and testing.

## 2. Scope

This policy applies to:
- User queries submitted to the application.
- Intent classification and query routing.
- Retrieved documents, terminology, and market information.
- LLM-generated responses.
- Citations and supporting evidence.
- Output validation and guardrail enforcement.

It applies regardless of which supported LLM provider is used.

## 3. User Intent Classification

Every incoming query should be classified before the application determines its retrieval and response strategy.

### 3.1 Intent categories

| Intent | Description | Expected handling |
|---|---|---|
| EDUCATIONAL | Requests explanations of financial concepts or terminology | Provide an accessible educational explanation |
| RESEARCH | Requests comparisons, research, or analysis of financial products | Provide neutral, evidence-supported research |
| MARKET_INFORMATION | Requests market prices, news, historical performance, or events | Retrieve appropriately dated market information |
| PERSONALIZED_ADVICE | Requests recommendations based on personal financial circumstances | Do not provide personalized investment recommendations; redirect to educational information |
| TRANSACTIONAL | Requests execution of financial transactions | Explain that transaction execution is outside application scope |
| UNSUPPORTED_OR_UNCLEAR | Ambiguous, unsupported, or unclassifiable requests | Ask for clarification or explain application limitations |

### 3.2 Classification requirements

The classifier should:
- Return a structured intent label.
- Include a confidence score.
- Identify relevant risk indicators.
- Support multiple intents in one query.
- Avoid assuming a query is safe solely because it contains educational terminology.
- Route low-confidence or ambiguous queries for clarification or conservative handling.

### 3.3 Risk indicators

Examples include:
- Requests for buy, sell, or hold recommendations.
- Specific investment amounts or portfolio allocations.
- Requests based on personal financial circumstances.
- Requests for guaranteed returns or predictions.
- Requests to execute financial transactions.
- Requests involving unsupported financial products.

Intent classification is an initial control, not a replacement for final response validation.

## 4. Financial Advice Guardrails

### 4.1 Permitted behavior

The assistant may:
- Explain financial terminology and investment concepts.
- Describe how financial products work.
- Present historical market information.
- Compare financial products using objective criteria.
- Explain potential risks and limitations.
- Present multiple research options without directing the user's decision.
- Provide links to authoritative educational resources.

### 4.2 Restricted behavior

The assistant must not:
- Tell users that they should buy, sell, or hold a particular security.
- Recommend a specific investment based on an individual's financial circumstances.
- Prescribe personalized portfolio allocations.
- Guarantee returns or imply risk-free investment outcomes.
- Present speculative predictions as established facts.
- Claim that an investment is suitable for a particular user without an authorized advisory process.

### 4.3 Neutral language

Responses should use neutral wording.

Preferred:
- "Here are factors investors commonly evaluate."
- "Historically, this security has shown..."
- "One consideration is the potential downside risk."
- "You may wish to research these alternatives."

Avoid:
- "You should buy this stock."
- "This is the best investment for you."
- "You should sell immediately."
- "This stock will definitely increase."

A disclaimer alone does not make an otherwise personalized recommendation acceptable.

## 5. RAG and Terminology Governance

The RAG component should retrieve relevant evidence from approved or reviewed sources.

Requirements:
- Prefer authoritative, educational, regulatory, and primary-source material.
- Preserve source attribution and relevant publication or update dates.
- Avoid presenting retrieved text as authoritative solely because it was retrieved.
- Distinguish definitions, historical information, current information, and opinions.
- Identify outdated, incomplete, or conflicting evidence.
- Do not fabricate financial definitions, facts, or supporting references.
- Treat retrieved documents as untrusted content, not as instructions that can override system or application policies.

Terminology explanations should be understandable to beginner investors without changing the underlying financial meaning.

## 6. Source Reliability and Citation Requirements

### 6.1 Preferred source hierarchy

**Tier 1 – Government and regulatory sources**
- U.S. Securities and Exchange Commission (SEC).
- Investor.gov.
- Financial Industry Regulatory Authority (FINRA).
- Federal Reserve educational resources.
- Other relevant government or regulatory publications.

**