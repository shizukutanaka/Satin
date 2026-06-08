"""
論文インテグレーター (arXiv / Google Scholar)

pip install arxiv scholarly で実際の検索が有効になります。
このスタブは content_aggregator.py がインポート可能な最低限の型定義を提供します。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

try:
    import arxiv as _arxiv_lib
except ImportError:
    _arxiv_lib = None  # type: ignore

try:
    from scholarly import scholarly as _scholarly_lib
except ImportError:
    _scholarly_lib = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class AcademicPaper:
    paper_id: str
    title: str
    abstract: str
    authors: List[str]
    published_date: Optional[datetime]
    url: str
    source: str  # 'arxiv' | 'scholar'
    keywords: List[str] = field(default_factory=list)
    citations: int = 0
    doi: Optional[str] = None
    full_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.published_date:
            data["published_date"] = self.published_date.isoformat()
        return data


class PaperIntegrator:
    """論文検索クライアント"""

    def __init__(self, cache_dir: str = "cache/papers"):
        self.cache_dir = cache_dir

    def search_arxiv(self, query: str, max_results: int = 10) -> List[AcademicPaper]:
        if _arxiv_lib is None:
            logger.warning("arxiv package not installed; pip install arxiv")
            return []
        papers = []
        try:
            client = _arxiv_lib.Client()
            search = _arxiv_lib.Search(query=query, max_results=max_results)
            for result in client.results(search):
                papers.append(AcademicPaper(
                    paper_id=result.entry_id,
                    title=result.title,
                    abstract=result.summary,
                    authors=[a.name for a in result.authors],
                    published_date=result.published,
                    url=result.entry_id,
                    source="arxiv",
                    keywords=result.categories,
                ))
        except Exception as e:
            logger.error(f"arXiv search error: {e}")
        return papers

    def search_google_scholar(
        self,
        query: str,
        max_results: int = 10,
        year_low: Optional[int] = None,
        year_high: Optional[int] = None,
    ) -> List[AcademicPaper]:
        if _scholarly_lib is None:
            logger.warning("scholarly package not installed; pip install scholarly")
            return []
        papers = []
        try:
            for i, result in enumerate(_scholarly_lib.search_pubs(query)):
                if i >= max_results:
                    break
                bib = result.get("bib", {})
                year = bib.get("pub_year")
                if year_low and year and int(year) < year_low:
                    continue
                if year_high and year and int(year) > year_high:
                    continue
                papers.append(AcademicPaper(
                    paper_id=result.get("url_scholarbib", str(i)),
                    title=bib.get("title", ""),
                    abstract=bib.get("abstract", ""),
                    authors=bib.get("author", []),
                    published_date=datetime(int(year), 1, 1) if year else None,
                    url=result.get("pub_url", ""),
                    source="scholar",
                    citations=result.get("num_citations", 0),
                ))
        except Exception as e:
            logger.error(f"Google Scholar search error: {e}")
        return papers

    def get_paper_by_doi(self, doi: str) -> Optional[AcademicPaper]:
        return None

    def get_paper_with_full_text(self, paper: AcademicPaper) -> AcademicPaper:
        return paper
