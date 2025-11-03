"""
Web Content Integration Module
Webコンテンツ取得・解析・抽出統合システム
"""

import re
import json
import time
import hashlib
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, urljoin, quote
from collections import deque
import logging

try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from error_handling import handle_error, RetryStrategy
from cache_manager import CacheManager
from logging_manager import LoggingManager


@dataclass
class WebPage:
    """Webページデータモデル"""
    url: str
    title: str
    content: str
    html: str
    extracted_text: str
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    language: str = "ja"
    keywords: List[str] = None
    images: List[str] = None
    links: List[str] = None
    metadata: Dict[str, Any] = None
    fetch_time: datetime = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []
        if self.images is None:
            self.images = []
        if self.links is None:
            self.links = []
        if self.metadata is None:
            self.metadata = {}
        if self.fetch_time is None:
            self.fetch_time = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        data = asdict(self)
        data['fetch_time'] = self.fetch_time.isoformat()
        if self.published_date:
            data['published_date'] = self.published_date.isoformat()
        return data


@dataclass
class SitemapEntry:
    """サイトマップエントリ"""
    url: str
    lastmod: Optional[datetime] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None


class WebIntegrator:
    """
    Web コンテンツ統合管理クラス

    複数の取得・解析手法を自動切り替え:
    1. Trafilatura (高精度記事抽出)
    2. Readability (コンテンツ抽出)
    3. BeautifulSoup (汎用HTML解析)
    4. Selenium (JavaScript動的レンダリング)
    """

    def __init__(
        self,
        cache_dir: str = "cache/web",
        user_agent: str = None,
        timeout: int = 30,
        max_retries: int = 3,
        use_selenium: bool = False
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.logger = LoggingManager.get_logger("web_integrator")
        self.cache_manager = CacheManager()

        self.timeout = timeout
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE

        # User-Agent
        if not user_agent:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        self.user_agent = user_agent

        # Requests session with retry
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            retry_strategy = Retry(
                total=max_retries,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.session.headers.update({'User-Agent': self.user_agent})

        # Selenium driver
        self.driver = None
        if self.use_selenium:
            self._init_selenium()

        capabilities = []
        if REQUESTS_AVAILABLE:
            capabilities.append("HTTP")
        if BS4_AVAILABLE:
            capabilities.append("BS4")
        if TRAFILATURA_AVAILABLE:
            capabilities.append("Trafilatura")
        if READABILITY_AVAILABLE:
            capabilities.append("Readability")
        if self.use_selenium:
            capabilities.append("Selenium")

        self.logger.info(f"Web Integrator initialized. Capabilities: {', '.join(capabilities)}")

    def _init_selenium(self):
        """Seleniumドライバ初期化"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(f'user-agent={self.user_agent}')

            self.driver = webdriver.Chrome(options=chrome_options)
            self.logger.info("Selenium WebDriver initialized")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Selenium: {e}")
            self.use_selenium = False

    def __del__(self):
        """デストラクタ - Seleniumドライバ終了 (改善: リソース確実解放)"""
        self.close()

    def close(self):
        """リソースを確実に解放"""
        if self.driver:
            try:
                self.driver.quit()
                self.logger.info("Selenium driver closed successfully")
            except Exception as e:
                self.logger.warning(f"Error closing Selenium driver: {e}")
            finally:
                self.driver = None

    def __enter__(self):
        """Context manager サポート"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager サポート"""
        self.close()

    def generate_url_hash(self, url: str) -> str:
        """URLのハッシュ値を生成"""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    @handle_error(RetryStrategy(max_retries=3, backoff_factor=2.0))
    def fetch_page(self, url: str, use_cache: bool = True) -> Optional[WebPage]:
        """
        Webページを取得・解析

        Args:
            url: 取得するURL
            use_cache: キャッシュを使用するか

        Returns:
            WebPage object or None
        """
        # キャッシュチェック
        cache_key = f"webpage_{self.generate_url_hash(url)}"
        if use_cache:
            cached = self.cache_manager.get(cache_key)
            if cached:
                self.logger.debug(f"Cache hit for {url}")
                return WebPage(**cached)

        # HTML取得
        html = self._fetch_html(url)
        if not html:
            self.logger.error(f"Failed to fetch HTML from {url}")
            return None

        # コンテンツ解析
        page = self._parse_html(url, html)
        if not page:
            return None

        # キャッシュ保存
        if use_cache:
            self.cache_manager.set(cache_key, page.to_dict(), ttl=86400)

        self.logger.info(f"Successfully fetched page: {url}")
        return page

    def _fetch_html(self, url: str) -> Optional[str]:
        """HTMLを取得"""
        # Method 1: Requests
        if REQUESTS_AVAILABLE:
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                response.encoding = response.apparent_encoding
                return response.text
            except Exception as e:
                self.logger.warning(f"Requests failed for {url}: {e}")

        # Method 2: Selenium fallback
        if self.use_selenium and self.driver:
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(2)  # JavaScript実行待機
                return self.driver.page_source
            except Exception as e:
                self.logger.warning(f"Selenium failed for {url}: {e}")

        return None

    def _parse_html(self, url: str, html: str) -> Optional[WebPage]:
        """HTMLを解析してWebPageオブジェクトを生成"""
        title = ""
        content = ""
        extracted_text = ""
        author = None
        published_date = None
        language = "ja"
        keywords = []
        images = []
        links = []
        metadata = {}

        # Method 1: Trafilatura (高精度記事抽出) - 最速・最高精度
        if TRAFILATURA_AVAILABLE:
            try:
                extracted_text = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False
                )
                if extracted_text:
                    content = extracted_text

                    # メタデータ取得
                    meta = trafilatura.extract_metadata(html)
                    if meta:
                        title = meta.title or title
                        author = meta.author
                        if meta.date:
                            try:
                                published_date = datetime.fromisoformat(meta.date)
                            except ValueError:
                                pass
                        language = meta.language or language

                    # 成功したので以降の抽出をスキップ
                    return WebPage(
                        url=url, title=title or url, content=content,
                        html=html, extracted_text=content, author=author,
                        published_date=published_date, language=language,
                        keywords=keywords, images=images, links=links,
                        metadata=metadata
                    )

            except Exception as e:
                self.logger.debug(f"Trafilatura extraction failed: {e}")

        # Method 2: Readability (コンテンツ抽出)
        if READABILITY_AVAILABLE:
            try:
                doc = Document(html)
                title = doc.title() or title
                content_html = doc.summary()

                if BS4_AVAILABLE:
                    soup = BeautifulSoup(content_html, 'html.parser')
                    content = soup.get_text(strip=True, separator=' ')

                # 成功したので以降の抽出をスキップ
                if content:
                    return WebPage(
                        url=url, title=title or url, content=content,
                        html=html, extracted_text=content, author=author,
                        published_date=published_date, language=language,
                        keywords=keywords, images=images, links=links,
                        metadata=metadata
                    )

            except Exception as e:
                self.logger.debug(f"Readability extraction failed: {e}")

        # Method 3: BeautifulSoup (汎用解析)
        if BS4_AVAILABLE:
            try:
                soup = BeautifulSoup(html, 'html.parser')

                # タイトル
                if not title:
                    title_tag = soup.find('title')
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                # メタタグ
                meta_tags = soup.find_all('meta')
                for tag in meta_tags:
                    name = tag.get('name', '').lower()
                    property_attr = tag.get('property', '').lower()
                    content_attr = tag.get('content', '')

                    if name == 'description':
                        metadata['description'] = content_attr
                    elif name == 'keywords':
                        keywords = [k.strip() for k in content_attr.split(',')]
                    elif name == 'author':
                        author = content_attr
                    elif property_attr == 'og:title':
                        title = content_attr or title
                    elif property_attr == 'og:description':
                        metadata['og_description'] = content_attr
                    elif property_attr == 'article:published_time':
                        try:
                            published_date = datetime.fromisoformat(content_attr.replace('Z', '+00:00'))
                        except:
                            pass

                # 本文抽出（フォールバック）
                if not content:
                    # 記事要素を探す
                    article = soup.find('article') or soup.find('main') or soup.find('body')
                    if article:
                        # スクリプト・スタイル除去
                        for script in article(['script', 'style', 'nav', 'footer', 'header']):
                            script.decompose()
                        content = article.get_text(strip=True, separator=' ')

                # 画像リンク
                img_tags = soup.find_all('img')
                for img in img_tags[:50]:  # 最大50枚
                    src = img.get('src', '')
                    if src:
                        full_url = urljoin(url, src)
                        if full_url.startswith('http'):
                            images.append(full_url)

                # リンク
                a_tags = soup.find_all('a', href=True)
                for a in a_tags[:100]:  # 最大100リンク
                    href = a.get('href', '')
                    if href:
                        full_url = urljoin(url, href)
                        if full_url.startswith('http'):
                            links.append(full_url)

            except Exception as e:
                self.logger.warning(f"BeautifulSoup parsing failed: {e}")

        # コンテンツが取得できなかった場合
        if not content:
            content = extracted_text or "Content extraction failed"

        return WebPage(
            url=url,
            title=title or url,
            content=content[:50000],  # 最大50KB
            html=html[:100000],  # 最大100KB
            extracted_text=extracted_text or content,
            author=author,
            published_date=published_date,
            language=language,
            keywords=keywords,
            images=images[:50],
            links=links[:100],
            metadata=metadata
        )

    def normalize_url(self, url: str) -> str:
        """
        改善: URL正規化 - 重複排除と標準化

        実装内容:
        - クエリパラメータの標準化 (ソート)
        - フラグメント削除
        - スキーム正規化 (http → https)
        - 末尾スラッシュ統一

        例:
        - https://example.com/page?b=2&a=1#section
        - https://example.com/page?a=1&b=2
        """
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        parsed = urlparse(url)

        # スキーム正規化 (http → https)
        scheme = 'https' if not parsed.scheme else parsed.scheme

        # ホストの小文字化
        netloc = parsed.netloc.lower()

        # パスの正規化
        path = parsed.path.rstrip('/')

        # クエリパラメータの正規化 (ソート)
        query = ''
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            # パラメータをソートして再構築
            sorted_params = []
            for key in sorted(params.keys()):
                for value in params[key]:
                    sorted_params.append((key, value))
            query = urlencode(sorted_params)

        # フラグメント削除
        fragment = ''

        # 正規化されたURLを再構築
        normalized = urlunparse((scheme, netloc, path, '', query, fragment))
        return normalized

    def check_robots_txt(self, url: str) -> bool:
        """
        改善: robots.txt チェック - スクレイピング倫理対応

        Args:
            url: チェック対象URL

        Returns:
            スクレイピング許可ならTrue
        """
        try:
            from urllib.robotparser import RobotFileParser
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            robots = RobotFileParser(robots_url)
            robots.read()

            can_fetch = robots.can_fetch(self.user_agent, url)
            if not can_fetch:
                self.logger.warning(f"robots.txt denies access to {url}")
            return can_fetch

        except Exception as e:
            # robots.txt が存在しない or 読み込み失敗 → スクレイピング許可と判定
            self.logger.debug(f"robots.txt check failed for {url}: {e}, allowing access")
            return True

    def batch_fetch_pages(
        self,
        urls: List[str],
        delay: float = 1.0,
        check_robots: bool = True,
        deduplicate: bool = True
    ) -> List[WebPage]:
        """
        改善: 複数URLを一括取得

        Args:
            urls: URL list
            delay: リクエスト間隔（秒）
            check_robots: robots.txt チェック実施
            deduplicate: URL重複排除実施

        Returns:
            WebPage list
        """
        pages = []

        # URL正規化と重複排除
        normalized_urls = []
        seen = set()

        for url in urls:
            norm_url = self.normalize_url(url)
            if deduplicate and norm_url in seen:
                self.logger.debug(f"Skipping duplicate URL: {url} → {norm_url}")
                continue
            seen.add(norm_url)
            normalized_urls.append(norm_url)

        self.logger.info(f"Processing {len(normalized_urls)} unique URLs (original: {len(urls)})")

        # バッチ取得
        for i, url in enumerate(normalized_urls):
            # robots.txt チェック
            if check_robots and not self.check_robots_txt(url):
                self.logger.info(f"Skipped {url} due to robots.txt")
                continue

            page = self.fetch_page(url, use_cache=True)
            if page:
                pages.append(page)
            else:
                self.logger.warning(f"Failed to fetch {url}")

            # レート制限対策
            if i < len(normalized_urls) - 1:
                time.sleep(delay)

        self.logger.info(f"Fetched {len(pages)}/{len(normalized_urls)} pages successfully")
        return pages

    @handle_error(RetryStrategy(max_retries=2))
    def crawl_site(
        self,
        start_url: str,
        max_pages: int = 100,
        same_domain_only: bool = True,
        depth_limit: int = 3
    ) -> List[WebPage]:
        """
        Webサイトをクロール

        Args:
            start_url: 開始URL
            max_pages: 最大ページ数
            same_domain_only: 同一ドメインのみ
            depth_limit: 最大階層深度

        Returns:
            WebPage list
        """
        visited: Set[str] = set()
        queue: deque = deque([(start_url, 0)])
        pages: List[WebPage] = []

        start_domain = urlparse(start_url).netloc

        # robots.txt 準拠チェック (倫理的スクレイピング)
        if not self.check_robots_txt(start_url):
            self.logger.error(f"robots.txt denies crawling {start_url}")
            return pages

        while queue and len(pages) < max_pages:
            url, depth = queue.popleft()

            if url in visited or depth > depth_limit:
                continue

            visited.add(url)

            # ページ取得
            page = self.fetch_page(url)
            if not page:
                continue

            pages.append(page)
            self.logger.info(f"Crawled: {url} (depth: {depth}, total: {len(pages)})")

            # リンク追加
            for link in page.links:
                if link not in visited:
                    link_domain = urlparse(link).netloc

                    # 同一ドメインチェック
                    if same_domain_only and link_domain != start_domain:
                        continue

                    queue.append((link, depth + 1))

            # レート制限対策
            time.sleep(1.0)

        self.logger.info(f"Crawl completed: {len(pages)} pages from {start_url}")
        return pages

    @handle_error(RetryStrategy(max_retries=2))
    def fetch_sitemap(self, domain: str) -> List[SitemapEntry]:
        """
        サイトマップを取得

        Args:
            domain: ドメイン (例: https://example.com)

        Returns:
            SitemapEntry list
        """
        sitemap_urls = [
            f"{domain}/sitemap.xml",
            f"{domain}/sitemap_index.xml",
            f"{domain}/sitemap-index.xml",
        ]

        for sitemap_url in sitemap_urls:
            try:
                html = self._fetch_html(sitemap_url)
                if not html or not BS4_AVAILABLE:
                    continue

                soup = BeautifulSoup(html, 'xml') or BeautifulSoup(html, 'html.parser')

                # URL要素を検索
                entries = []
                for url_tag in soup.find_all('url'):
                    loc = url_tag.find('loc')
                    if not loc:
                        continue

                    entry = SitemapEntry(url=loc.get_text(strip=True))

                    lastmod = url_tag.find('lastmod')
                    if lastmod:
                        try:
                            entry.lastmod = datetime.fromisoformat(lastmod.get_text(strip=True).replace('Z', '+00:00'))
                        except:
                            pass

                    changefreq = url_tag.find('changefreq')
                    if changefreq:
                        entry.changefreq = changefreq.get_text(strip=True)

                    priority = url_tag.find('priority')
                    if priority:
                        try:
                            entry.priority = float(priority.get_text(strip=True))
                        except:
                            pass

                    entries.append(entry)

                if entries:
                    self.logger.info(f"Found {len(entries)} URLs in sitemap: {sitemap_url}")
                    return entries

            except Exception as e:
                self.logger.debug(f"Sitemap fetch failed for {sitemap_url}: {e}")

        self.logger.warning(f"No sitemap found for {domain}")
        return []

    def search_text_in_page(self, page: WebPage, pattern: str, case_sensitive: bool = False) -> List[str]:
        """ページ内テキスト検索"""
        flags = 0 if case_sensitive else re.IGNORECASE
        matches = re.findall(pattern, page.content, flags=flags)
        return matches

    def export_page_data(self, page: WebPage, output_path: str):
        """ページデータをJSONファイルにエクスポート"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(page.to_dict(), f, ensure_ascii=False, indent=2)

        self.logger.info(f"Page data exported to {output_path}")


if __name__ == "__main__":
    # 使用例
    integrator = WebIntegrator()

    # 単一ページ取得
    page = integrator.fetch_page("https://example.com")
    if page:
        print(f"Title: {page.title}")
        print(f"Content length: {len(page.content)} chars")
        print(f"Images: {len(page.images)}")
        print(f"Links: {len(page.links)}")

    # サイトマップ取得
    sitemap = integrator.fetch_sitemap("https://example.com")
    print(f"\nSitemap URLs: {len(sitemap)}")
    for entry in sitemap[:5]:
        print(f"- {entry.url}")
