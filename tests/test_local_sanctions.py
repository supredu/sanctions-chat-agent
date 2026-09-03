from tools.local_sanctions import lookup_local_sanctions, normalize_address, search_local_entities


def test_normalizes_evm_address() -> None:
    assert (
        normalize_address("0xE950DC316b836e4EeFb8308bf32Bf7C72a1358FF")
        == "0xe950dc316b836e4eefb8308bf32bf7c72a1358ff"
    )


def test_lookup_known_ofac_address() -> None:
    hits = lookup_local_sanctions("0xE950DC316b836e4EeFb8308bf32Bf7C72a1358FF")

    assert hits
    assert any(hit["authority"] == "Office of Foreign Assets Control" for hit in hits)


def test_ftm_dates_are_metadata_only() -> None:
    hits = lookup_local_sanctions("TY6P1xitySxBa9MgW4nnoB4yMLjvZ7UcsH")

    assert hits
    assert all(hit["sanction_dates"] == [] for hit in hits)
    assert all(hit["publication_date"] is None for hit in hits)
    assert any(hit["metadata"].get("third_party_sanction_start_date") for hit in hits)


def test_fuzzy_search_finds_ofac_entity_by_partial_name() -> None:
    hits = search_local_entities("Gaza", limit=10)

    assert any("Gaza Now" in hit["name"] for hit in hits)
    assert any(hit["addresses"] for hit in hits if "Gaza Now" in hit["name"])
