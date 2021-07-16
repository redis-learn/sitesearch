import pytest

from sitesearch.config import AppConfiguration
from sitesearch.query_parser import parse

config = AppConfiguration()


@pytest.mark.asyncio
async def test_strips_dash_star_postfixes():
    query = await parse("index", "python-*", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index python* SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"


@pytest.mark.asyncio
async def test_strips_unsafe_chars():
    query = await parse("index", "this is a [test]", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index this is a  test SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"


@pytest.mark.asyncio
async def test_summarizes_body():
    query = await parse("index", "test", None, 0, 10, config.default_search_site)
    assert "SUMMARIZE FIELDS 1 body" in " ".join(query)


@pytest.mark.asyncio
async def test_highlights_fields():
    query = await parse("index", "test", None, 0, 10, config.default_search_site)
    assert "HIGHLIGHT FIELDS 3 title body section_title" in " ".join(query)


@pytest.mark.asyncio
async def test_exact_search_for_synonym_terms():
    query = await parse("index", "insight*", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index insight SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"


@pytest.mark.asyncio
async def test_allow_fuzzy_search_for_non_synonym_terms():
    query = await parse("index", "test*", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index test* SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"


@pytest.mark.asyncio
async def test_boosts_current_section_if_given():
    query = await parse("index", "test", "test", 0, 10, config.default_search_site)
    assert ' '.join(query) == "index ((@s:test) => {$weight: 10} test) | test SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"


@pytest.mark.asyncio
async def test_escapes_configured_literal_terms():
    query = await parse("index", "active-active", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index active\\-active SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"

    query = await parse("index", "leader-follower active-active", None, 0, 10, config.default_search_site)
    assert ' '.join(query) == "index leader\\-follower active\\-active SUMMARIZE FIELDS 1 body FRAGS 1 LEN 10 HIGHLIGHT FIELDS 3 title body section_title LIMIT 0 10"