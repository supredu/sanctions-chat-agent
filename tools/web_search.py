from agents import function_tool


def make_search_queries(address: str) -> list[str]:
    clean_address = address.strip()
    return [
        f'"{clean_address}" sanctions OFAC',
        f'"{clean_address}" "Specially Designated Nationals"',
        f'"{clean_address}" "UK OFSI"',
        f'"{clean_address}" "EU sanctions"',
        f'"{clean_address}" "UN sanctions"',
        f'"{clean_address}" Chainalysis TRM Elliptic sanctions',
    ]


@function_tool
def build_sanctions_search_queries(address: str) -> list[str]:
    """Build high-signal web search queries for a blockchain sanctions lookup."""
    return make_search_queries(address)
