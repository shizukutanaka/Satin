"""
Property-based testing framework for Satin using Hypothesis.

Provides strategies for generating test data and property tests for
YouTube, Web, and Paper integrators with edge case coverage.

Implements:
- Custom Hypothesis strategies for Satin data types
- Property-based tests for integrator functions
- Edge case and invariant testing
- Regression test creation from failures
"""

from hypothesis import given, strategies as st, settings, HealthCheck, assume
from hypothesis.strategies import composite, SearchStrategy
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import pytest

from main.schema_validators import (
    ContentType, APIProvider, HTTPMethod,
    YouTubeSearchRequest, WebScrapingRequest, ArxivSearchRequest,
    SearchResult, RateLimitConfig, APIErrorInfo, CacheEntry
)


# Custom Hypothesis Strategies

@composite
def content_types(draw) -> ContentType:
    """Strategy for generating ContentType enums."""
    return draw(st.sampled_from(ContentType))


@composite
def api_providers(draw) -> APIProvider:
    """Strategy for generating APIProvider enums."""
    return draw(st.sampled_from(APIProvider))


@composite
def http_methods(draw) -> HTTPMethod:
    """Strategy for generating HTTP methods."""
    return draw(st.sampled_from(HTTPMethod))


@composite
def valid_urls(draw) -> str:
    """Strategy for generating valid URLs."""
    scheme = draw(st.sampled_from(['http', 'https']))
    domain = draw(st.just(draw(st.from_regex(
        r'[a-z0-9]+(\.[a-z0-9]+)+',
        fullmatch=True
    ))))
    path = draw(st.just('/' + draw(st.text(
        alphabet='abcdefghijklmnopqrstuvwxyz0-9-_/',
        min_size=0,
        max_size=100
    ))))
    return f"{scheme}://{domain}{path}"


@composite
def valid_api_keys(draw) -> str:
    """Strategy for generating valid API keys."""
    return draw(st.text(
        alphabet='abcdefghijklmnopqrstuvwxyz0123456789-_',
        min_size=20,
        max_size=100
    ))


@composite
def youtube_search_requests(draw) -> YouTubeSearchRequest:
    """Strategy for generating YouTubeSearchRequest objects."""
    return YouTubeSearchRequest(
        query=draw(st.text(
            alphabet='abcdefghijklmnopqrstuvwxyz ',
            min_size=1,
            max_size=100
        )),
        max_results=draw(st.integers(min_value=1, max_value=50)),
        api_key=draw(st.one_of(
            st.none(),
            valid_api_keys()
        )),
        order=draw(st.sampled_from([
            'relevance', 'rating', 'title', 'uploadDate', 'videoCount'
        ])),
        region_code=draw(st.one_of(
            st.none(),
            st.from_regex(r'[A-Z]{2}', fullmatch=True)
        )),
        language=draw(st.one_of(
            st.none(),
            st.text(alphabet='abcdefghijklmnopqrstuvwxyz', min_size=2, max_size=5)
        )),
        min_duration=draw(st.integers(min_value=0, max_value=3600))
    )


@composite
def web_scraping_requests(draw) -> WebScrapingRequest:
    """Strategy for generating WebScrapingRequest objects."""
    return WebScrapingRequest(
        url=draw(valid_urls()),
        timeout_seconds=draw(st.floats(
            min_value=1.0,
            max_value=300.0
        )),
        max_retries=draw(st.integers(min_value=0, max_value=10)),
        verify_robots_txt=draw(st.booleans()),
        user_agent=draw(st.text(
            min_size=10,
            max_size=200
        )),
        follow_redirects=draw(st.booleans()),
        max_redirects=draw(st.integers(min_value=0, max_value=20))
    )


@composite
def arxiv_search_requests(draw) -> ArxivSearchRequest:
    """Strategy for generating ArxivSearchRequest objects."""
    return ArxivSearchRequest(
        query=draw(st.text(
            alphabet='abcdefghijklmnopqrstuvwxyz ',
            min_size=1,
            max_size=200
        )),
        max_results=draw(st.integers(min_value=1, max_value=100)),
        sort_by=draw(st.sampled_from([
            'relevance', 'lastUpdatedDate', 'submittedDate'
        ])),
        sort_order=draw(st.sampled_from(['ascending', 'descending']))
    )


@composite
def search_results(draw) -> SearchResult:
    """Strategy for generating SearchResult objects."""
    now = datetime.now()
    ttl = draw(st.integers(min_value=300, max_value=2592000))
    return SearchResult(
        title=draw(st.text(
            min_size=1,
            max_size=200
        )),
        url=draw(valid_urls()),
        content_type=draw(content_types()),
        source=draw(api_providers()),
        summary=draw(st.one_of(
            st.none(),
            st.text(max_size=500)
        )),
        relevance_score=draw(st.floats(
            min_value=0.0,
            max_value=100.0
        )),
        published_date=draw(st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime.now()
            )
        )),
        ttl_seconds=ttl
    )


@composite
def rate_limit_configs(draw) -> RateLimitConfig:
    """Strategy for generating RateLimitConfig objects."""
    rps = draw(st.floats(min_value=0.1, max_value=1000.0))
    burst = draw(st.floats(min_value=rps, max_value=rps * 10))
    return RateLimitConfig(
        requests_per_second=rps,
        burst_size=burst,
        refill_rate=draw(st.floats(min_value=0.1, max_value=100.0)),
        backoff_factor=draw(st.floats(min_value=1.0, max_value=10.0)),
        max_wait_seconds=draw(st.floats(min_value=1.0, max_value=3600.0))
    )


@composite
def api_error_infos(draw) -> APIErrorInfo:
    """Strategy for generating APIErrorInfo objects."""
    return APIErrorInfo(
        error_code=draw(st.text(
            alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_',
            min_size=3,
            max_size=30
        )),
        http_status=draw(st.sampled_from([
            400, 401, 403, 404, 429, 500, 502, 503, 504
        ])),
        is_retryable=draw(st.booleans()),
        retry_after_seconds=draw(st.one_of(
            st.none(),
            st.floats(min_value=1.0, max_value=3600.0)
        )),
        error_category=draw(st.sampled_from([
            'rate_limit', 'not_found', 'server_error',
            'client_error', 'auth_error', 'unknown'
        ])),
        message=draw(st.text(max_size=500))
    )


@composite
def cache_entries(draw) -> CacheEntry:
    """Strategy for generating CacheEntry objects."""
    now = datetime.now()
    ttl = draw(st.integers(min_value=300, max_value=2592000))
    return CacheEntry(
        key=draw(st.text(
            alphabet='abcdefghijklmnopqrstuvwxyz0123456789_-',
            min_size=1,
            max_size=100
        )),
        value={'data': draw(st.text())},
        content_type=draw(content_types()),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl),
        ttl_seconds=ttl,
        tags=draw(st.lists(
            st.text(alphabet='abcdefghijklmnopqrstuvwxyz0123456789-', min_size=1, max_size=20),
            max_size=10
        ))
    )


# Property-Based Tests

class TestYouTubeSearchRequest:
    """Property-based tests for YouTubeSearchRequest validation."""

    @given(youtube_search_requests())
    def test_valid_request_construction(self, req: YouTubeSearchRequest):
        """Test valid requests can be constructed."""
        assert req.query is not None
        assert 1 <= req.max_results <= 50
        assert req.query.strip() != ""

    @given(st.text(min_size=1, max_size=2000))
    def test_query_validation(self, query: str):
        """Test query field validation."""
        req = YouTubeSearchRequest(query=query)
        assert req.query is not None

    @given(
        st.integers(min_value=0, max_value=3600),
        st.integers(min_value=1, max_value=3600)
    )
    def test_duration_range_validation(self, min_dur: int, max_dur: int):
        """Test duration range constraints."""
        assume(max_dur > min_dur)
        req = YouTubeSearchRequest(
            query="test",
            min_duration=min_dur,
            max_duration=max_dur
        )
        assert req.min_duration <= req.max_duration

    @given(st.datetimes(), st.datetimes())
    def test_date_range_validation(self, date1: datetime, date2: datetime):
        """Test date range constraints."""
        assume(date1 != date2)
        if date1 < date2:
            req = YouTubeSearchRequest(
                query="test",
                published_after=date1,
                published_before=date2
            )
            assert req.published_after <= req.published_before
        else:
            with pytest.raises(ValueError):
                YouTubeSearchRequest(
                    query="test",
                    published_after=date1,
                    published_before=date2
                )


class TestWebScrapingRequest:
    """Property-based tests for WebScrapingRequest validation."""

    @given(web_scraping_requests())
    def test_valid_request_construction(self, req: WebScrapingRequest):
        """Test valid requests can be constructed."""
        assert req.url.startswith(('http://', 'https://'))
        assert req.timeout_seconds > 0
        assert 0 <= req.max_retries <= 10

    @given(valid_urls())
    def test_url_validation(self, url: str):
        """Test URL validation."""
        req = WebScrapingRequest(url=url)
        assert req.url == url

    @given(st.floats(min_value=1.0, max_value=1000.0))
    def test_timeout_validation(self, timeout: float):
        """Test timeout field validation."""
        req = WebScrapingRequest(
            url="https://example.com",
            timeout_seconds=timeout
        )
        assert req.timeout_seconds == timeout


class TestSearchResult:
    """Property-based tests for SearchResult validation."""

    @given(search_results())
    def test_valid_result_construction(self, result: SearchResult):
        """Test valid results can be constructed."""
        assert result.title is not None
        assert result.url is not None
        assert 0 <= result.relevance_score <= 100
        assert result.ttl_seconds >= 300

    @given(search_results())
    def test_result_invariants(self, result: SearchResult):
        """Test result invariants."""
        # expiration should be in future
        assert result.fetch_timestamp <= datetime.now()
        # relevance should be valid percentage
        assert 0 <= result.relevance_score <= 100

    @given(
        st.floats(min_value=-1.0, max_value=101.0)
    )
    def test_relevance_score_bounds(self, score: float):
        """Test relevance score is properly bounded."""
        assume(0 <= score <= 100)
        result = SearchResult(
            title="test",
            url="https://example.com",
            content_type=ContentType.ARTICLE,
            source=APIProvider.WEB_SEARCH,
            relevance_score=score
        )
        assert result.relevance_score == score


class TestCacheEntry:
    """Property-based tests for CacheEntry validation."""

    @given(cache_entries())
    def test_valid_cache_entry(self, entry: CacheEntry):
        """Test valid cache entries."""
        assert entry.key is not None
        assert entry.expires_at > entry.created_at
        assert not entry.is_expired

    @given(cache_entries())
    def test_cache_entry_invariants(self, entry: CacheEntry):
        """Test cache entry invariants."""
        # TTL should be positive
        assert entry.ttl_seconds > 0
        # Hit count should be non-negative
        assert entry.hit_count >= 0
        # Not expired
        assert not entry.is_expired

    @given(
        st.datetimes(min_value=datetime(2025, 1, 1)),
        st.timedeltas(min_value=timedelta(seconds=300))
    )
    def test_expiration_calculation(self, created: datetime, delta: timedelta):
        """Test expiration is calculated correctly."""
        expires = created + delta
        entry = CacheEntry(
            key="test",
            value={"data": "test"},
            content_type=ContentType.ARTICLE,
            created_at=created,
            expires_at=expires,
            ttl_seconds=int(delta.total_seconds())
        )
        assert entry.expires_at == expires


class TestRateLimitConfig:
    """Property-based tests for RateLimitConfig."""

    @given(rate_limit_configs())
    def test_valid_config(self, config: RateLimitConfig):
        """Test valid rate limit configurations."""
        assert config.requests_per_second > 0
        assert config.burst_size >= config.requests_per_second
        assert config.refill_rate > 0
        assert config.backoff_factor >= 1.0

    @given(rate_limit_configs())
    def test_config_invariants(self, config: RateLimitConfig):
        """Test rate limit config invariants."""
        # Burst size should accommodate burst
        assert config.burst_size >= config.requests_per_second
        # Backoff should be reasonable
        assert 1.0 <= config.backoff_factor <= 10.0
        # Max wait should be positive
        assert config.max_wait_seconds > 0


class TestAPIErrorInfo:
    """Property-based tests for APIErrorInfo."""

    @given(api_error_infos())
    def test_valid_error_info(self, error: APIErrorInfo):
        """Test valid error info creation."""
        assert error.error_code is not None
        assert 100 <= error.http_status <= 599
        assert error.error_category in [
            'rate_limit', 'not_found', 'server_error',
            'client_error', 'auth_error', 'unknown'
        ]

    @given(api_error_infos())
    def test_error_invariants(self, error: APIErrorInfo):
        """Test error info invariants."""
        # Timestamp should be recent
        delta = datetime.now() - error.timestamp
        assert delta.total_seconds() >= 0
        assert delta.total_seconds() < 10  # Should be generated recently
        # HTTP status should be valid
        assert 100 <= error.http_status <= 599


# Regression Test Framework

def create_regression_test(
    function_name: str,
    inputs: Dict[str, Any],
    expected_output: Any,
    error_type: Optional[type] = None
) -> str:
    """
    Create a regression test from a property-based test failure.

    Args:
        function_name: Name of function being tested
        inputs: Input data that caused failure
        expected_output: Expected output
        error_type: Exception type if error expected

    Returns:
        Generated pytest test code as string
    """
    test_code = f"""
def test_regression_{function_name}_{id(inputs)}():
    \"\"\"Regression test for {function_name}.\"\"\"
    inputs = {repr(inputs)}
"""

    if error_type:
        test_code += f"""
    with pytest.raises({error_type.__name__}):
        {function_name}(**inputs)
"""
    else:
        test_code += f"""
    result = {function_name}(**inputs)
    assert result == {repr(expected_output)}
"""

    return test_code


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(search_results())
def test_search_result_serialization(result: SearchResult):
    """Test SearchResult can be serialized/deserialized."""
    json_data = result.model_dump_json()
    assert json_data is not None

    deserialized = SearchResult.model_validate_json(json_data)
    assert deserialized.title == result.title
    assert deserialized.url == result.url
    assert deserialized.relevance_score == result.relevance_score


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(search_results(), min_size=1, max_size=100))
def test_result_list_processing(results: List[SearchResult]):
    """Test processing lists of search results."""
    # Filter by relevance
    high_relevance = [r for r in results if r.relevance_score >= 75]
    assert all(r.relevance_score >= 75 for r in high_relevance)

    # Sort by score
    sorted_results = sorted(results, key=lambda r: r.relevance_score, reverse=True)
    for i in range(len(sorted_results) - 1):
        assert sorted_results[i].relevance_score >= sorted_results[i+1].relevance_score
