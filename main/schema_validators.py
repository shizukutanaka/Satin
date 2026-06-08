"""
Pydantic v2 schema validation models for Satin integrators.

Provides comprehensive data validation for YouTube, Web, and Paper integrators
with field validators, custom types, and JSON schema generation.

Implements:
- Request/Response validation models
- Custom field validators with cross-field validation
- ContentType enums and URL validation
- Error recovery information validation
- API-specific constraint validation
"""

try:
    from pydantic import BaseModel, Field, validator, field_validator, ValidationInfo
    from pydantic.functional_validators import AfterValidator
    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False

    class BaseModel:  # type: ignore[no-redef]
        """Fallback stub when Pydantic is not installed."""
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        @classmethod
        def model_json_schema(cls): return {}

    def Field(default=None, **kw): return default  # type: ignore[misc]
    def validator(*a, **kw): return lambda f: f  # type: ignore[misc]
    def field_validator(*a, **kw): return lambda f: f  # type: ignore[misc]
    class ValidationInfo: pass  # type: ignore[no-redef]
    def AfterValidator(f): return f  # type: ignore[misc]
from typing import Optional, List, Dict, Any, Annotated, Union
from enum import Enum
from datetime import datetime, timedelta
from urllib.parse import urlparse
import re


class ContentType(str, Enum):
    """Content types handled by Satin."""
    VIDEO = "video"
    PAPER = "paper"
    WEBPAGE = "webpage"
    ARTICLE = "article"
    UNKNOWN = "unknown"


class APIProvider(str, Enum):
    """API providers supported by Satin."""
    YOUTUBE = "youtube"
    ARXIV = "arxiv"
    GOOGLE_SCHOLAR = "google_scholar"
    WEB_SEARCH = "web_search"
    CUSTOM = "custom"


class HTTPMethod(str, Enum):
    """HTTP methods."""
    GET = "get"
    POST = "post"
    PUT = "put"
    DELETE = "delete"
    HEAD = "head"


def validate_url(v: str) -> str:
    """Validate URL format."""
    try:
        result = urlparse(v)
        if not all([result.scheme, result.netloc]):
            raise ValueError("Invalid URL format")
        return v
    except Exception as e:
        raise ValueError(f"URL validation failed: {e}")


def validate_api_key(v: str) -> str:
    """Validate API key format (non-empty, reasonable length)."""
    if not v or len(v) < 10:
        raise ValueError("API key must be at least 10 characters")
    if len(v) > 500:
        raise ValueError("API key exceeds maximum length")
    return v


def validate_positive_number(v: Union[int, float]) -> Union[int, float]:
    """Validate positive number."""
    if v <= 0:
        raise ValueError("Value must be positive")
    return v


def validate_percentage(v: float) -> float:
    """Validate percentage value (0-100)."""
    if not 0 <= v <= 100:
        raise ValueError("Percentage must be between 0 and 100")
    return v


UrlType = Annotated[str, AfterValidator(validate_url)]
ApiKeyType = Annotated[str, AfterValidator(validate_api_key)]
PositiveNumber = Annotated[Union[int, float], AfterValidator(validate_positive_number)]
Percentage = Annotated[float, AfterValidator(validate_percentage)]


class YouTubeSearchRequest(BaseModel):
    """Validation model for YouTube search requests."""

    query: str = Field(..., min_length=1, max_length=2000, description="Search query")
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results (1-50)"
    )
    api_key: Optional[ApiKeyType] = Field(
        default=None,
        description="YouTube API key"
    )
    order: str = Field(
        default="relevance",
        pattern="^(relevance|rating|title|uploadDate|videoCount)$",
        description="Sort order"
    )
    region_code: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=2,
        pattern="^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code"
    )
    language: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=5,
        description="Language code (e.g., 'en', 'ja')"
    )
    published_after: Optional[datetime] = Field(
        default=None,
        description="Publish date after (RFC 3339)"
    )
    published_before: Optional[datetime] = Field(
        default=None,
        description="Publish date before (RFC 3339)"
    )
    min_duration: int = Field(
        default=0,
        ge=0,
        description="Minimum video duration in seconds"
    )
    max_duration: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum video duration in seconds"
    )

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate search query is not just whitespace."""
        if not v.strip():
            raise ValueError("Query cannot be empty or whitespace")
        return v.strip()

    @field_validator('max_duration')
    @classmethod
    def validate_duration_range(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        """Validate duration range is logical."""
        if v is not None and 'min_duration' in info.data:
            min_dur = info.data['min_duration']
            if v <= min_dur:
                raise ValueError("max_duration must be greater than min_duration")
        return v

    @field_validator('published_before')
    @classmethod
    def validate_date_range(cls, v: Optional[datetime], info: ValidationInfo) -> Optional[datetime]:
        """Validate published date range is logical."""
        if v is not None and 'published_after' in info.data:
            published_after = info.data['published_after']
            if published_after and v <= published_after:
                raise ValueError("published_before must be after published_after")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Python asyncio tutorial",
                "max_results": 10,
                "order": "relevance",
                "language": "en"
            }
        }


class WebScrapingRequest(BaseModel):
    """Validation model for web scraping requests."""

    url: UrlType = Field(..., description="URL to scrape")
    timeout_seconds: PositiveNumber = Field(
        default=30.0,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts"
    )
    verify_robots_txt: bool = Field(
        default=True,
        description="Whether to respect robots.txt"
    )
    user_agent: str = Field(
        default="Satin/1.0 (+http://example.com/bot)",
        min_length=10,
        max_length=500,
        description="User agent string"
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom HTTP headers"
    )
    follow_redirects: bool = Field(
        default=True,
        description="Whether to follow HTTP redirects"
    )
    max_redirects: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Maximum redirects to follow"
    )
    extract_methods: List[str] = Field(
        default=["html", "xpath", "css", "regex"],
        description="Extraction methods to try"
    )

    @field_validator('url')
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        """Ensure URL has http/https scheme."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator('headers')
    @classmethod
    def validate_headers(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate header format."""
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Headers must be string key-value pairs")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/article",
                "timeout_seconds": 30,
                "verify_robots_txt": True
            }
        }


class ArxivSearchRequest(BaseModel):
    """Validation model for Arxiv search requests."""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    max_results: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum results (1-100)"
    )
    sort_by: str = Field(
        default="relevance",
        pattern="^(relevance|lastUpdatedDate|submittedDate)$",
        description="Sort criteria"
    )
    sort_order: str = Field(
        default="descending",
        pattern="^(ascending|descending)$",
        description="Sort order"
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description="Arxiv categories to search"
    )
    date_start: Optional[datetime] = Field(
        default=None,
        description="Start date for paper search"
    )
    date_end: Optional[datetime] = Field(
        default=None,
        description="End date for paper search"
    )

    @field_validator('categories')
    @classmethod
    def validate_categories(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate arxiv category format."""
        if v:
            valid_pattern = re.compile(r'^[a-z]+(\.[A-Z]{2})?$')
            for cat in v:
                if not valid_pattern.match(cat):
                    raise ValueError(f"Invalid arxiv category format: {cat}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "query": "deep learning optimization",
                "max_results": 10,
                "categories": ["cs.LG", "stat.ML"]
            }
        }


class SearchResult(BaseModel):
    """Validation model for search results."""

    title: str = Field(..., min_length=1, max_length=500, description="Result title")
    url: UrlType = Field(..., description="Result URL")
    content_type: ContentType = Field(..., description="Type of content")
    source: APIProvider = Field(..., description="Data source")
    summary: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Brief summary"
    )
    relevance_score: Percentage = Field(
        default=1.0,
        description="Relevance score 0-100"
    )
    published_date: Optional[datetime] = Field(
        default=None,
        description="Publication date"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    fetch_timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When result was fetched"
    )
    ttl_seconds: int = Field(
        default=86400,
        ge=300,
        le=2592000,
        description="Time to live in seconds (5min - 30days)"
    )

    @field_validator('metadata')
    @classmethod
    def validate_metadata(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata doesn't contain sensitive info."""
        forbidden_keys = {'api_key', 'token', 'password', 'secret'}
        if any(key.lower() in forbidden_keys for key in v.keys()):
            raise ValueError("Metadata contains forbidden keys")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Advanced Python Programming",
                "url": "https://example.com/article",
                "content_type": "article",
                "source": "web_search",
                "relevance_score": 95.0
            }
        }


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    requests_per_second: PositiveNumber = Field(
        default=10,
        description="Rate limit requests per second"
    )
    burst_size: PositiveNumber = Field(
        default=20,
        description="Burst capacity (tokens in bucket)"
    )
    refill_rate: PositiveNumber = Field(
        default=1.0,
        description="Token refill rate per second"
    )
    retry_after_header: bool = Field(
        default=True,
        description="Respect Retry-After header"
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff multiplier"
    )
    max_wait_seconds: PositiveNumber = Field(
        default=300,
        description="Maximum wait time in seconds"
    )

    @field_validator('burst_size')
    @classmethod
    def validate_burst_size(cls, v: float, info: ValidationInfo) -> float:
        """Ensure burst_size >= requests_per_second."""
        if 'requests_per_second' in info.data:
            if v < info.data['requests_per_second']:
                raise ValueError("burst_size must be >= requests_per_second")
        return v


class APIErrorInfo(BaseModel):
    """Information about API errors for recovery."""

    error_code: str = Field(..., description="Error code from API")
    http_status: int = Field(..., ge=100, le=599, description="HTTP status code")
    is_retryable: bool = Field(..., description="Whether error is retryable")
    retry_after_seconds: Optional[PositiveNumber] = Field(
        default=None,
        description="Seconds to wait before retry"
    )
    error_category: str = Field(
        ...,
        pattern="^(rate_limit|not_found|server_error|client_error|auth_error|unknown)$",
        description="Error category"
    )
    message: str = Field(..., max_length=1000, description="Error message")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When error occurred"
    )

    @field_validator('retry_after_seconds')
    @classmethod
    def validate_retry_after(cls, v: Optional[float]) -> Optional[float]:
        """Validate retry_after is reasonable."""
        if v is not None and v > 86400:
            raise ValueError("Retry-after must be <= 1 day (86400 seconds)")
        return v


class CacheEntry(BaseModel):
    """Cached entry validation model."""

    key: str = Field(..., min_length=1, max_length=500, description="Cache key")
    value: Any = Field(..., description="Cached value")
    content_type: ContentType = Field(..., description="Content type")
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime = Field(..., description="Expiration time")
    ttl_seconds: PositiveNumber = Field(..., description="TTL in seconds")
    hit_count: int = Field(default=0, ge=0, description="Cache hits")
    last_accessed: Optional[datetime] = Field(
        default=None,
        description="Last access time"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Cache tags for invalidation"
    )

    @field_validator('expires_at')
    @classmethod
    def validate_expiration(cls, v: datetime, info: ValidationInfo) -> datetime:
        """Ensure expiration is in the future."""
        if 'created_at' in info.data:
            if v <= info.data['created_at']:
                raise ValueError("Expiration time must be after creation time")
        if v <= datetime.now():
            raise ValueError("Expiration time must be in the future")
        return v

    @property
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return datetime.now() >= self.expires_at

    class Config:
        json_schema_extra = {
            "example": {
                "key": "youtube_search_results_python",
                "content_type": "video",
                "created_at": "2025-01-01T00:00:00Z",
                "expires_at": "2025-01-08T00:00:00Z",
                "ttl_seconds": 604800
            }
        }


class HealthCheckResponse(BaseModel):
    """Health check response validation."""

    status: str = Field(
        ...,
        pattern="^(UP|DEGRADED|DOWN)$",
        description="Service status"
    )
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, str] = Field(
        default_factory=dict,
        description="Individual service statuses"
    )
    response_time_ms: PositiveNumber = Field(
        ...,
        description="Response time in milliseconds"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional details"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "UP",
                "services": {
                    "youtube": "UP",
                    "web_scraper": "DEGRADED",
                    "arxiv": "UP"
                },
                "response_time_ms": 45.2
            }
        }
