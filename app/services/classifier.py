"""
Classification service using Azure OpenAI GPT-4.1-mini.
"""

import json
import time
from typing import Optional
from dataclasses import dataclass

from openai import AzureOpenAI


@dataclass
class ClassificationResult:
    domain: str = "Uncertain"
    category: str = "Uncertain"
    confidence: float = 0.0
    reasoning: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


CATEGORIES = {
    "Law": {
        "Contracts": "Agreements, terms, parties, obligations, clauses, signatures (commercial, employment, lease, NDA)",
        "Litigation": "Lawsuits, claims, plaintiffs, defendants, petitions, appeals, motions, complaints",
        "Court Rulings": "Judgments, verdicts, court decisions, judicial opinions, sentences, orders",
        "Legislation": "Statutes, regulations, codes, legislative acts, amendments, articles of law",
        "Legal Opinions": "Advisory opinions, legal memos, counsel guidance, fatwas, attorney guidance",
    }
}

FEW_SHOT_EXAMPLES = """
Examples:

[Law > Contracts] "وقّع الطرفان عقد شراكة تجارية وفقاً لأحكام القانون المدني" -> Contracts
[Law > Contracts] "The parties executed a non-disclosure agreement with standard indemnification clauses" -> Contracts
[Law > Litigation] "رفع المحامي دعوى تعويض أمام المحكمة الابتدائية ضد الشركة" -> Litigation
[Law > Litigation] "The plaintiff filed a class-action lawsuit alleging securities fraud" -> Litigation
[Law > Court Rulings] "أصدرت المحكمة الدستورية العليا حكماً بعدم دستورية المادة الثانية" -> Court Rulings
[Law > Court Rulings] "The Supreme Court delivered a landmark ruling on patent eligibility" -> Court Rulings
[Law > Legislation] "نشرت الجريدة الرسمية قانون العمل الجديد رقم 12 لسنة 2024" -> Legislation
[Law > Legislation] "The Data Protection Act 2024 introduces new compliance requirements" -> Legislation
[Law > Legal Opinions] "أصدر مجلس الدولة فتوى قانونية بشأن نزاع عقود التعيينات الحكومية" -> Legal Opinions
[Law > Legal Opinions] "The Attorney General issued a formal legal opinion on the treaty" -> Legal Opinions
[Uncertain] "The weather is nice today" -> Uncertain
[Uncertain] "I had breakfast this morning" -> Uncertain
"""


class Classifier:
    def __init__(
        self,
        api_key: str = "",
        endpoint: str = "",
        deployment_name: str = "gpt-4.1-mini",
        api_version: str = "2024-12-01-preview",
    ):
        self.api_key = api_key
        self.endpoint = endpoint
        self.deployment_name = deployment_name
        self.api_version = api_version

        if not self.api_key or not self.endpoint:
            raise ValueError(
                "Missing Azure OpenAI credentials. "
                "Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."
            )

        self.client = AzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
        )
        self.input_cost = 0.00015
        self.output_cost = 0.0006

    def classify(self, text: str) -> ClassificationResult:
        if not text or not text.strip():
            return ClassificationResult(error="Empty input")

        categories_text = ""
        for domain_name, sub_cats in CATEGORIES.items():
            for cat, desc in sub_cats.items():
                categories_text += f"- {domain_name} > {cat} ({desc})\n"

        prompt = f"""You are an expert legal document classifier for Arabic and English documents.

Classify the following document into ONE domain and ONE sub-category:
{categories_text}

{FEW_SHOT_EXAMPLES}

Document to classify:
\"\"\"{text[:3000]}\"\"\"

Respond ONLY with a JSON object:
{{"domain": "Law", "category": "CategoryName", "confidence": 0.XX, "reasoning": "Brief explanation"}}

domain must be: Law
category must be one of: Contracts, Litigation, Court Rulings, Legislation, Legal Opinions, Uncertain"""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": "You are a legal document classifier. Respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=200,
            )

            content = response.choices[0].message.content.strip()

            try:
                result_dict = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{[^{}]*"category"[^{}]*\}', content, re.DOTALL)
                if json_match:
                    result_dict = json.loads(json_match.group(0))
                else:
                    result_dict = {"domain": "Law", "category": "Uncertain", "confidence": 0.5, "reasoning": content[:200]}

            tokens_used = response.usage.total_tokens
            cost_usd = (
                (response.usage.prompt_tokens / 1000) * self.input_cost +
                (response.usage.completion_tokens / 1000) * self.output_cost
            )

            domain = result_dict.get("domain", "Law")
            if domain not in CATEGORIES:
                domain = "Law"

            category = result_dict.get("category", "Uncertain")
            if domain in CATEGORIES and category not in CATEGORIES[domain]:
                category = "Uncertain"

            return ClassificationResult(
                domain=domain,
                category=category,
                confidence=float(result_dict.get("confidence", 0.5)),
                reasoning=result_dict.get("reasoning", ""),
                tokens_used=tokens_used,
                cost_usd=round(cost_usd, 6),
            )

        except Exception as e:
            return ClassificationResult(error=f"Classification failed: {str(e)}")


# Singleton
_classifier: Optional[Classifier] = None


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        from app.core.config import settings

        _classifier = Classifier(
            api_key=settings.AZURE_OPENAI_API_KEY,
            endpoint=settings.AZURE_OPENAI_ENDPOINT,
            deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    return _classifier
