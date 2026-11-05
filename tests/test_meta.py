"""Pruebas de los adaptadores de Meta con transporte falso. Ninguna llama a la API real.

Las respuestas imitan los ejemplos de dev.meta.ai/docs consultados el 30 de octubre de 2026.
"""
import base64
import json

import httpx
import pytest

from premonition.meta import (Budget, BudgetExceeded, MetaClient, MetaError, MetaPlanner, MetaReference,
                              client_from_env)
from premonition.models import Contract, Predicate
from premonition.validator import PlanRejected

KEY = "clave-de-prueba-no-real"
DOC_SAM_LINE = ("<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,"
                "~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>,1<|box;x1=155;y1=228;x2=202;y2=254;"
                "w=320;h=334|><|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>")


def client(handler, budget=None, log=None):
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai/v1")
    return MetaClient(KEY, budget or Budget(max_calls=10, max_usd=1.0), http=http, on_usage=log)


def chat_reply(content):
    return httpx.Response(200, json={
        "id": "chatcmpl-1", "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}})


def contract():
    return Contract(contract_id="c", run_id="r", step_id="s4", attempt=1, plan_sha256="p", action="place",
                    role="post", piece_id="A", predicates=[Predicate(kind="piece_present", region="left", piece="A")],
                    initial_frame_sha256=None, reference_sha256=None, reference_source=None, thresholds_sha256="t")


def test_key_is_read_from_the_environment_only(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert client_from_env() is None
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    assert client_from_env().api_key == KEY


def test_default_meta_client_has_a_25_second_timeout():
    instance = MetaClient(KEY, Budget(8, 0.15))
    try:
        assert instance.http.timeout.read == 25.0
        assert instance.http.timeout.connect == 25.0
    finally:
        instance.http.close()


def test_planner_sends_the_documented_structured_output_request(sim_cell, demo_plan):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
        return chat_reply(demo_plan.model_dump_json())

    plan = MetaPlanner(client(handler)).plan("Coloca A a la izquierda", sim_cell)
    assert plan == demo_plan
    assert seen["url"] == "https://api.meta.ai/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    body = seen["body"]
    assert body["model"] == "muse-spark-1.3"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "KitPlan"
    assert body["response_format"]["json_schema"]["strict"] is True


def test_planner_output_goes_through_the_deterministic_validator(sim_cell):
    bad = json.dumps({"steps": [{"step_id": "s1", "action": "pick", "piece_id": "Z", "source_id": "src_a"}]})
    with pytest.raises(PlanRejected):
        MetaPlanner(client(lambda r: chat_reply(bad))).plan("x", sim_cell)


def test_planner_output_cannot_add_tools_or_enable_motion(sim_cell, demo_plan):
    raw = json.loads(demo_plan.model_dump_json()) | {"motion_enabled": True}
    with pytest.raises(PlanRejected):
        MetaPlanner(client(lambda r: chat_reply(json.dumps(raw)))).plan("x", sim_cell)


def test_reference_uses_the_documented_edit_endpoint_and_the_initial_photo(sim_cell):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content))
        return httpx.Response(200, json={
            "created": 1, "data": [{"b64_json": base64.b64encode(b"imagen").decode()}], "output_format": "jpeg",
            "background": "opaque", "usage": {"input_tokens": 9, "output_tokens": 7, "total_tokens": 16}})

    image = MetaReference(client(handler))(b"foto-inicial", contract(), sim_cell)
    assert image == b"imagen"
    assert seen["url"] == "https://api.meta.ai/v1/images/edits"
    body = seen["body"]
    assert body["model"] == "muse-image-1.0" and body["n"] == 1 and body["output_format"] == "jpeg"
    assert body["images"] == [{"image_url": "data:image/jpeg;base64," + base64.b64encode(b"foto-inicial").decode()}]
    assert all(value is False for value in body["tool_enablement"].values())


def test_reference_prompt_comes_from_the_contract(sim_cell):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2Vu"}], "usage": {}})

    MetaReference(client(handler))(b"x", contract(), sim_cell)
    assert "pieza A" in seen["prompt"] and "izquierda" in seen["prompt"]


def test_segmentation_uses_responses_and_the_official_parser():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_1", "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": DOC_SAM_LINE, "annotations": []}]}],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}})

    records = client(handler).segment(b"foto", "pieza roja")
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    content = seen["body"]["input"][0]["content"]
    assert seen["body"]["model"] == "sam-3.1"
    assert content[0] == {"type": "input_text", "text": "pieza roja"}
    assert content[1]["type"] == "input_image" and content[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert seen["body"]["metadata"] == {"include_confidence": "true"}
    # El parser oficial entrega cajas semiabiertas: x2=270 de la API se convierte en right=271.
    assert [(r.object_id, r.box) for r in records] == [("0", (211, 228, 271, 255)), ("1", (155, 228, 203, 255))]
    assert records[0].mask_shape == (27, 60)


def test_zero_matches_is_a_valid_empty_result():
    empty = httpx.Response(200, json={"output": [{"type": "message", "content": [
        {"type": "output_text", "text": ""}]}], "usage": {}})
    assert client(lambda r: empty).segment(b"x", "tetera") == []


@pytest.mark.parametrize("status, code", [(401, "authentication_error"), (404, "model_not_found"),
                                          (429, "rate_limit_error"), (503, "server_error")])
def test_api_failures_are_raised_never_replaced_by_fixtures(status, code):
    failure = httpx.Response(status, json={"error": {"type": code, "code": code, "message": "falló"}},
                             headers={"Retry-After": "15"})
    with pytest.raises(MetaError) as caught:
        client(lambda r: failure).segment(b"x", "pieza")
    assert caught.value.status == status and code in str(caught.value)


def test_budget_blocks_the_call_before_it_is_sent():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"output": [], "usage": {}})

    meta = client(handler, Budget(max_calls=1, max_usd=1.0))
    meta.segment(b"x", "pieza")
    with pytest.raises(BudgetExceeded):
        meta.segment(b"x", "pieza")
    assert len(calls) == 1


def test_usd_budget_blocks_an_image_that_would_exceed_it(sim_cell):
    meta = client(lambda r: httpx.Response(500), Budget(max_calls=9, max_usd=0.005))
    with pytest.raises(BudgetExceeded):
        MetaReference(meta)(b"x", contract(), sim_cell)


def test_usage_and_latency_are_recorded_without_the_key(sim_cell, demo_plan):
    log = []
    MetaPlanner(client(lambda r: chat_reply(demo_plan.model_dump_json()), log=log.append)).plan("x", sim_cell)
    entry = log[0]
    assert entry["model"] == "muse-spark-1.3" and entry["input_tokens"] == 1000 and entry["output_tokens"] == 200
    assert entry["latency_ms"] >= 0
    assert entry["usd"] == pytest.approx(1000 * 1.25e-6 + 200 * 4.25e-6)
    assert KEY not in json.dumps(log)


def test_failed_calls_are_recorded_too():
    log = []
    with pytest.raises(MetaError):
        client(lambda r: httpx.Response(503, json={"error": {"message": "x"}}), log=log.append).segment(b"x", "p")
    assert log[0]["status"] == 503 and log[0]["usd"] == 0


def test_error_text_never_contains_the_key():
    with pytest.raises(MetaError) as caught:
        client(lambda r: httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})).segment(b"x", "p")
    assert KEY not in str(caught.value)


def test_chat_response_without_choices_is_a_meta_error():
    with pytest.raises(MetaError):
        client(lambda r: httpx.Response(200, json={"id": "chatcmpl-1"})).chat_json("s", "u", {}, "S")


def test_task_judge_still_fits_budget_after_a_plan_timeout():
    import cv2
    import numpy as np
    from types import SimpleNamespace
    from premonition.autonomy import plan_task, judge
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            raise httpx.ReadTimeout("plan timed out", request=request)
        return chat_reply(json.dumps({"success": False, "reason": "no grasp", "next": "ask_human"}))
    instance = client(handler, budget=Budget(8, 0.15))
    image = np.zeros((1080, 1920, 3), np.uint8)
    views = {v: SimpleNamespace(image=image) for v in ("c922", "usb")}
    with pytest.raises(MetaError):
        plan_task(instance, "Pick the orange sponge and place it in clear area A left of its start, away from edges.", views)
    verdict = judge(instance, "grasp", views, views)
    assert verdict["source"] == "muse"
    assert instance.budget.calls == 2 and instance.budget.usd < 0.15
    assert all(r["reasoning_effort"] == "low" and r["max_completion_tokens"] <= 1024 for r in requests)
