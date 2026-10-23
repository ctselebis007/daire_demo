import pytest

from app.filters import FilterError, translate
from app.indexes import build_search_definition, build_vector_definition
from app.search import _app_rrf, build_pipeline, build_stages, display_pipeline, pipeline_to_text
from app.seed_data import generate_records, tenant_configs
from app.settings import Settings, mask_secret, redact_uri
from app.templating import TemplateError, render, validate

TENANTS = {t["_id"]: {**t, "activeDatasetVersion": 3} for t in tenant_configs()}
TM = TENANTS["talent-match"]


def test_filter_translation_parity():
    mql, s_filter, s_not = translate(TM, [
        {"field": "metadata.level", "op": "in", "value": ["manager", "director"]},
        {"field": "metadata.yearsExperience", "op": "gte", "value": "8"},
        {"field": "metadata.location.country", "op": "ne", "value": "US"},
        {"field": "metadata.availableFrom", "op": "lte", "value": "2026-12-01"},
    ])
    assert mql[0] == {"metadata.level": {"$in": ["manager", "director"]}}
    assert mql[1] == {"metadata.yearsExperience": {"$gte": 8.0}}
    assert s_filter[0] == {"in": {"path": "metadata.level", "value": ["manager", "director"]}}
    assert s_filter[1] == {"range": {"path": "metadata.yearsExperience", "gte": 8.0}}
    assert s_not == [{"equals": {"path": "metadata.location.country", "value": "US"}}]
    assert mql[3]["metadata.availableFrom"]["$lte"].year == 2026


@pytest.mark.parametrize("bad", [
    {"field": "$where", "op": "eq", "value": "1"},
    {"field": "metadata.level", "op": "regex", "value": ".*"},
    {"field": "metadata.secret", "op": "eq", "value": "x"},
    {"field": "metadata.yearsExperience", "op": "eq", "value": 5},
    {"field": "metadata.level", "op": "eq", "value": {"$gt": ""}},
    {"field": "metadata.yearsExperience", "op": "gte", "value": "abc"},
])
def test_filter_rejections(bad):
    with pytest.raises(FilterError):
        translate(TM, [bad])


def test_template_sandbox_blocks_ssti():
    with pytest.raises(TemplateError):
        render("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})


def test_template_renders_record():
    rec = generate_records("talent-match", 1)[0]
    text = render(TM["embeddingInputTemplate"], rec)
    assert rec["name"] in text and "Skills:" in text
    assert "@" not in text  # email is not embedded


def test_seed_records_valid_for_all_tenants():
    for tid, t in TENANTS.items():
        recs = generate_records(tid, 50)
        assert len({r["recordId"] for r in recs}) == 50
        for r in recs:
            assert validate(t["inputSchema"], r) == [], (tid, r)
            render(t["embeddingInputTemplate"], r)
        for sq in t["sampleQueries"]:
            assert validate(t["queryConfig"]["schema"], sq["query"]) == []
            translate(t, sq["filters"])


def test_seed_is_deterministic():
    assert generate_records("vendor-sourcing", 5, 42) == generate_records("vendor-sourcing", 5, 42)


def test_index_generator_union():
    tenants = list(TENANTS.values())
    sdef, warnings = build_search_definition(tenants)
    assert not warnings
    meta = sdef["mappings"]["fields"]["metadata"]["fields"]
    assert meta["location"]["fields"]["country"] == {"type": "token"}
    assert meta["rating"] == {"type": "number"}
    assert meta["diversityOwned"] == {"type": "boolean"}
    vdef, _ = build_vector_definition(tenants, 1024)
    paths = [f["path"] for f in vdef["fields"]]
    assert paths[:4] == ["embedding", "tenantId", "datasetVersion", "status"]
    assert "metadata.availableFrom" in paths
    assert vdef["fields"][0]["similarity"] == "dotProduct"


def test_hybrid_pipeline_shape():
    stages = build_stages(TM, [0.1] * 4, "aws migration", [{"field": "metadata.level", "op": "eq", "value": "manager"}], 30, exact=False)
    p = build_pipeline("hybrid", stages, {"vector": 0.7, "text": 0.3}, 30)
    rf = p[0]["$rankFusion"]
    vs = rf["input"]["pipelines"]["vector"][0]["$vectorSearch"]
    assert vs["filter"]["$and"][:3] == [{"tenantId": "talent-match"}, {"datasetVersion": 3}, {"status": 1}]
    assert vs["numCandidates"] == 450
    assert rf["combination"]["weights"] == {"vector": 0.7, "text": 0.3}
    assert display_pipeline(p)[0]["$rankFusion"]["input"]["pipelines"]["vector"][0]["$vectorSearch"]["queryVector"] == "<4 floats>"
    exact = build_stages(TM, [0.1], "x", None, 10, exact=True)["vector"][0]["$vectorSearch"]
    assert exact["exact"] is True and "numCandidates" not in exact


def test_app_rrf_matches_formula():
    v = [{"recordId": "a"}, {"recordId": "b"}]
    t = [{"recordId": "b"}, {"recordId": "c"}]
    out = _app_rrf(v, t, {"vector": 0.7, "text": 0.3}, 10)
    assert [r["recordId"] for r in out] == ["b", "a", "c"]
    assert out[0]["score"] == pytest.approx(0.7 / 62 + 0.3 / 61)


def test_settings_masking():
    assert redact_uri("mongodb+srv://user:p%40ss@cluster0.x.mongodb.net/") == "mongodb+srv://user:••••@cluster0.x.mongodb.net/"
    assert mask_secret("pa-abcdefghijkl1234") == "••••1234"
    with pytest.raises(ValueError):
        Settings(mongodb_uri="http://evil")
    with pytest.raises(ValueError):
        Settings(voyage_base_url="http://ai.mongodb.com/v1")


def test_pipeline_text_is_executable_shape():
    filters = [{"field": "metadata.availableFrom", "op": "lte", "value": "2026-12-01"}]
    stages = build_stages(TM, [0.25, -0.5], "genai", filters, 30, exact=False)
    text = pipeline_to_text(build_pipeline("hybrid", stages, {"vector": 0.7, "text": 0.3}, 30))
    assert '"queryVector": [0.25,-0.5]' in text
    assert 'ISODate("2026-12-01T00:00:00")' in text
    assert "__dare_" not in text
    assert '"$rankFusion"' in text
