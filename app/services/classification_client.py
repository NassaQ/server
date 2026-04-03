"""
Classification service wrapper for the FastAPI server.

Imports the LLMClassifier from the Classification-model directory and
exposes a simple function that accepts plain text and returns classification results.

Note: ``Classification-model/`` is added to ``sys.path`` in ``app/main.py``.
"""

from typing import Optional

from azure_openai_classifier import LLMClassifier, ClassificationResult  # noqa: E402


# ── Module-level singleton ────────────────────────────────────────────────
_classifier: Optional[LLMClassifier] = None


def _get_classifier(
    api_key: str,
    endpoint: str,
    deployment_name: str,
    api_version: str,
) -> LLMClassifier:
    """Lazily initialise the classifier (one per process)."""
    global _classifier
    if _classifier is None:
        _classifier = LLMClassifier(
            provider="azure",
            api_key=api_key,
            endpoint=endpoint,
            deployment_name=deployment_name,
            api_version=api_version,
        )
    return _classifier


def run_classification(
    plain_text: str,
    api_key: str,
    endpoint: str,
    deployment_name: str,
    api_version: str,
) -> dict:
    """
    Classify plain text into one of the predefined categories.

    Returns a dict with category, confidence, reasoning, tokens_used, cost_usd, error.
    """
    if not plain_text or not plain_text.strip():
        return {
            "category": "Error",
            "confidence": 0.0,
            "reasoning": "No text provided for classification",
            "tokens_used": 0,
            "cost_usd": 0.0,
            "error": "Empty input",
        }

    classifier = _get_classifier(api_key, endpoint, deployment_name, api_version)
    result: ClassificationResult = classifier.classify(plain_text)

    return {
        "category": result.category,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "tokens_used": result.tokens_used,
        "cost_usd": result.cost_usd,
        "error": result.error,
    }
