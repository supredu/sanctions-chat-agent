SOURCE_TYPE_RANK = {
    "government": 100,
    "official_list": 90,
    "blockchain_analytics": 70,
    "news": 40,
    "unknown": 0,
}


def rank_source_type(source_type: str | None) -> int:
    if not source_type:
        return 0

    return SOURCE_TYPE_RANK.get(source_type, 0)
