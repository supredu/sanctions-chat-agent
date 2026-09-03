from agents import function_tool


PRIORITY_SANCTIONS_SOURCES = [
    {
        "authority": "OFAC",
        "publisher": "U.S. Department of the Treasury",
        "source_type": "government",
        "notes": "Primary source for SDN and cyber-related sanctions designations.",
    },
    {
        "authority": "UK OFSI",
        "publisher": "UK Office of Financial Sanctions Implementation",
        "source_type": "government",
        "notes": "Primary UK consolidated sanctions list and notices.",
    },
    {
        "authority": "EU",
        "publisher": "European Union",
        "source_type": "government",
        "notes": "EU restrictive measures and consolidated financial sanctions list.",
    },
    {
        "authority": "UN",
        "publisher": "United Nations Security Council",
        "source_type": "government",
        "notes": "UN Security Council consolidated sanctions list.",
    },
    {
        "authority": "Blockchain analytics",
        "publisher": "Chainalysis, TRM Labs, Elliptic, Nansen, Arkham",
        "source_type": "blockchain_analytics",
        "notes": "Useful secondary evidence for entity labels and address clustering.",
    },
]


@function_tool
def list_priority_sanctions_sources() -> list[dict[str, str]]:
    """Return the source families that should be checked for sanctions evidence."""
    return PRIORITY_SANCTIONS_SOURCES
