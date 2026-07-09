from scraper.parsers.registry import detect_url, LFL_RE


def test_www_lfl_classic_recognized():
    url = "https://www.lfl.ru/person63121"
    assert LFL_RE.match(url)
    assert detect_url(url) == (url, "lfl")


def test_www_afl_recognized():
    url = "https://www.afl.ru/players/zverev-ivan-711043"
    assert detect_url(url) == (url, "afl")


def test_www_fleague_recognized():
    url = "https://www.f-league.ru/player/6691548"
    assert detect_url(url) == (url, "fleague")


def test_www_page_lfl_recognized():
    url = "https://www.page.lfl.ru/persons/191918"
    assert detect_url(url) == (url, "lfl")


def test_non_www_still_works():
    assert detect_url("https://lfl.ru/person63121") == ("https://lfl.ru/person63121", "lfl")


def test_regional_subdomain_still_ignored():
    assert detect_url("https://ug.lfl.ru/player12345") is None
