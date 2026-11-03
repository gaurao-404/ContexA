from types import SimpleNamespace
from app.embeddings import embed, cosine, hybrid_score
from app.inspection import contrast_ratio, inspect_content, _validated_context_findings, local_ai_status
from app import inspection as inspection_module


def rule(code, category, severity, pattern=None, clause="approved guideline clause", fix="review and update"):
    return SimpleNamespace(id=f"id-{code}", code=code, title=f"Rule {code}", category=category,
        severity=severity, pattern=pattern, rule_clause=clause, suggested_fix=fix,
        embedding=embed(f"Rule {code} {category} {clause}"), is_active=True)


def test_embed_is_normalized_and_repeatable():
    a, b = embed("quantified revenue claim"), embed("quantified revenue claim")
    assert a == b
    assert abs(cosine(a, a) - 1.0) < 1e-6
    assert hybrid_score("quantified revenue claim", "quantified revenue", embed("quantified revenue")) > 0


def test_deterministic_claim_and_disclaimer_findings():
    rules = [
        rule("CLM-204", "claim", "critical", r"#\s?1\b|\bfastest\b|\bboost[^.!?\n]{0,55}\b\d+%", "Claims require evidence."),
        rule("LGL-002", "legal", "critical", None, "Promotional claims need disclaimers."),
    ]
    text = "We are the #1 fastest platform to boost revenue by 400%."
    findings = inspect_content(text, [{"page": 1, "text": text, "spans": []}], rules)
    assert any(f["rule_id"] == "id-CLM-204" and f["severity"] == "critical" for f in findings)
    assert any(f["rule_id"] == "id-LGL-002" for f in findings)
    assert all(f["rule_id"] in {"id-CLM-204", "id-LGL-002"} for f in findings)


def test_disclaimer_prevents_second_legal_finding():
    rules = [rule("CLM-204", "claim", "critical", r"\bfastest\b"), rule("LGL-002", "legal", "critical", None)]
    text = "Our product is the fastest in its category. Results may vary."
    findings = inspect_content(text, [{"page": 1, "text": text, "spans": []}], rules)
    assert any(f["rule_id"] == "id-CLM-204" for f in findings)
    assert not any(f["rule_id"] == "id-LGL-002" for f in findings)


def test_wcag_contrast():
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == 21.0
    assert contrast_ratio((255, 255, 255), (255, 255, 255)) == 1.0


def test_local_ai_context_result_requires_valid_rule_and_grounded_quote():
    approved = rule("TONE-009", "tone", "warning", None, "Use clear, evidence-led language.")
    content = "This new plan is the obvious choice for every customer."
    response = __import__("json").dumps({"findings": [{
        "rule_id": approved.id, "quote": "obvious choice", "reasoning": "It is pressuring language without evidence.",
        "suggested_fix": "Explain the measurable benefit instead.", "severity": "critical"
    }]})
    result = _validated_context_findings(response, [approved], content, [{"page": 1, "text": content, "spans": []}])
    assert len(result) == 1
    assert result[0]["rule_id"] == approved.id
    assert result[0]["severity"] == "warning"  # model cannot change approved rule severity


def test_local_ai_marks_ungrounded_quotes_unverifiable():
    approved = rule("CLAIM-010", "claim", "critical", None, "Quantified claims require evidence.")
    content = "We improve onboarding for teams."
    response = __import__("json").dumps({"findings": [{
        "rule_id": approved.id, "quote": "We guarantee 900% revenue growth",
        "reasoning": "Made-up claim", "suggested_fix": "Remove the claim."
    }]})
    result = _validated_context_findings(response, [approved], content, [{"page": 1, "text": content, "spans": []}])
    assert result[0]["finding_type"] == "unverifiable"
    assert result[0]["rule_id"] is None

def test_local_ai_status_handles_missing_ollama_without_api_key(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("connection refused")
    # Explicitly opt in for this test; submission-safe app defaults keep Ollama disabled.
    monkeypatch.setattr(inspection_module, "OLLAMA_ENABLED", True)
    monkeypatch.setattr(inspection_module, "urlopen", unavailable)
    status = local_ai_status()
    assert status["enabled"] is True
    assert status["service_available"] is False
    assert status["model_available"] is False
    assert status["install_command"].startswith("ollama pull ")


def test_local_ollama_inference_parses_grounded_json(monkeypatch):
    import json
    approved = rule("TONE-011", "tone", "warning", None, "Use specific, evidence-led phrasing.")
    content = "This offer is the obvious choice for every customer."
    result_payload = {"message": {"content": json.dumps({"findings": [{
        "rule_id": approved.id, "quote": "obvious choice",
        "reasoning": "This is an absolute endorsement without context.",
        "suggested_fix": "Explain the concrete benefit instead.", "severity": "critical"
    }]})}}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(result_payload).encode("utf-8")
    monkeypatch.setattr(inspection_module, "_ollama_model_available", lambda: True)
    monkeypatch.setattr(inspection_module, "urlopen", lambda *args, **kwargs: FakeResponse())
    result = inspection_module._run_ollama_grounded_checks(content, [{"page": 1, "text": content, "spans": []}], [approved])
    assert result is not None and len(result) == 1
    assert result[0]["rule_id"] == approved.id
    assert result[0]["severity"] == "warning"
