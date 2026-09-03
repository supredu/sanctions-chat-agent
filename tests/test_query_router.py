from services.query_router import infer_query_type, lookup_local_query


def test_infers_address_query() -> None:
    assert infer_query_type("0xE950DC316b836e4EeFb8308bf32Bf7C72a1358FF") == "address"


def test_infers_entity_query() -> None:
    assert infer_query_type("Gaza") == "entity"


def test_routes_entity_query_to_fuzzy_search() -> None:
    result = lookup_local_query("Gaza", entity_limit=5)

    assert result["query_type"] == "entity"
    assert result["hit_count"] > 0
    assert any("Gaza Now" in hit["name"] for hit in result["hits"])
