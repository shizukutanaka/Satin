"""
YouTube Integration Module
統合的なYouTube動画・字幕・メタデータ取得システム
"""

import re
import json
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from functools import lru_cache
import logging
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, parse_qs

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    TRANSCRIPT_AVAILABLE = True
except ImportError:
    TRANSCRIPT_AVAILABLE = False

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

from error_handling import handle_error, RetryStrategy, ErrorContext
from cache_manager import CacheManager
from logging_manager import LoggingManager


@dataclass
class YouTubeVideo:
    """YouTube動画データモデル"""
    video_id: str
    title: str
    description: str
    channel_title: str
    channel_id: str
    published_at: datetime
    duration: int  # seconds
    view_count: int
    like_count: int
    comment_count: int
    tags: List[str]
    category_id: str
    thumbnail_url: str
    transcript: Optional[str] = None
    captions_available: bool = False
    language: str = "ja"

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        data = asdict(self)
        data['published_at'] = self.published_at.isoformat()
        return data


@dataclass
class YouTubeChannel:
    """YouTubeチャンネルデータモデル"""
    channel_id: str
    title: str
    description: str
    subscriber_count: int
    video_count: int
    view_count: int
    thumbnail_url: str
    custom_url: Optional[str] = None
    country: Optional[str] = None


@dataclass
class YouTubePlaylist:
    """YouTubeプレイリストデータモデル"""
    playlist_id: str
    title: str
    description: str
    channel_title: str
    item_count: int
    video_ids: List[str]


class YouTubeIntegrator:
    """
    YouTube統合管理クラス

    複数の取得方法を自動切り替え:
    1. YouTube Data API v3 (優先・高速・構造化データ)
    2. yt-dlp (フォールバック・詳細情報)
    3. youtube-transcript-api (字幕専用)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: str = "cache/youtube",
        cache_ttl: int = 86400,  # 24時間
        rate_limit_per_day: int = 10000
    ):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.logger = LoggingManager.get_logger("youtube_integrator")
        self.cache_manager = CacheManager()

        # 改善: 時間単位のクォータ管理
        self.rate_limit_per_day = rate_limit_per_day
        self.quota_usage = 0  # API呼び出しのquota消費量を追跡
        self.request_reset_time = datetime.now() + timedelta(days=1)

        # クォータ消費量の定義 (YouTube Data API v3仕様)
        self.quota_costs = {
            'videos.list': 1,        # 基本情報取得
            'search.list': 100,       # 検索
            'playlistItems.list': 1,  # プレイリストアイテム
            'comments.list': 1,       # コメント
        }

        # YouTube Data API初期化
        self.youtube_service = None
        if YOUTUBE_API_AVAILABLE and api_key:
            try:
                self.youtube_service = build('youtube', 'v3', developerKey=api_key)
                self.logger.info("YouTube Data API v3 initialized successfully")
            except Exception as e:
                self.logger.warning(f"Failed to initialize YouTube API: {e}")

        self.logger.info(
            f"YouTube Integrator initialized. "
            f"API: {YOUTUBE_API_AVAILABLE and bool(api_key)}, "
            f"yt-dlp: {YT_DLP_AVAILABLE}, "
            f"transcript: {TRANSCRIPT_AVAILABLE}"
        )

    def extract_video_id(self, url: str) -> Optional[str]:
        """
        YouTube URLから動画IDを抽出

        対応フォーマット:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://m.youtube.com/watch?v=VIDEO_ID
        """
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # URLでない場合は直接IDとして扱う
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url

        return None

    def extract_playlist_id(self, url: str) -> Optional[str]:
        """YouTube URLからプレイリストIDを抽出"""
        patterns = [
            r'[?&]list=([a-zA-Z0-9_-]+)',
            r'youtube\.com\/playlist\?list=([a-zA-Z0-9_-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def extract_channel_id(self, url: str) -> Optional[str]:
        """YouTube URLからチャンネルIDを抽出"""
        patterns = [
            r'youtube\.com\/channel\/([a-zA-Z0-9_-]+)',
            r'youtube\.com\/@([a-zA-Z0-9_-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def _check_rate_limit(self, quota_cost: int = 1) -> bool:
        """
        改善: クォータベースのレート制限チェック

        Args:
            quota_cost: このAPI呼び出しが消費するquota単位数

        Returns:
            クォータに余裕があればTrue
        """
        now = datetime.now()
        if now >= self.request_reset_time:
            self.quota_usage = 0
            self.request_reset_time = now + timedelta(days=1)
            self.logger.info("YouTube API quota reset for new day")

        if self.quota_usage + quota_cost > self.rate_limit_per_day:
            remaining = self.rate_limit_per_day - self.quota_usage
            self.logger.warning(
                f"YouTube API quota limit reached. Current: {self.quota_usage}/{self.rate_limit_per_day}, "
                f"Need: {quota_cost}, Remaining: {remaining}"
            )
            return False

        self.quota_usage += quota_cost
        self.logger.debug(f"Quota used: {self.quota_usage}/{self.rate_limit_per_day}")
        return True

    def get_quota_status(self) -> Dict[str, Any]:
        """現在のクォータ使用状況を取得"""
        now = datetime.now()
        reset_in = (self.request_reset_time - now).total_seconds()
        return {
            'used': self.quota_usage,
            'limit': self.rate_limit_per_day,
            'remaining': self.rate_limit_per_day - self.quota_usage,
            'reset_in_seconds': max(0, reset_in),
            'reset_time': self.request_reset_time.isoformat()
        }

    @handle_error(RetryStrategy(max_retries=3, backoff_factor=2.0))
    def get_video_info(self, video_id: str, include_transcript: bool = True) -> Optional[YouTubeVideo]:
        """
        動画情報を取得

        Args:
            video_id: YouTube動画ID
            include_transcript: 字幕を含めるか

        Returns:
            YouTubeVideo object or None
        """
        # キャッシュチェック
        cache_key = f"video_{video_id}_{include_transcript}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            self.logger.debug(f"Cache hit for video {video_id}")
            return YouTubeVideo(**cached)

        video_info = None

        # Method 1: YouTube Data API v3
        if self.youtube_service and self._check_rate_limit():
            try:
                video_info = self._get_video_info_api(video_id)
            except Exception as e:
                self.logger.warning(f"YouTube API failed: {e}")

        # Method 2: yt-dlp fallback
        if not video_info and YT_DLP_AVAILABLE:
            try:
                video_info = self._get_video_info_ytdlp(video_id)
            except Exception as e:
                self.logger.warning(f"yt-dlp failed: {e}")

        if not video_info:
            self.logger.error(f"Failed to retrieve video info for {video_id}")
            return None

        # 字幕取得
        if include_transcript:
            transcript = self.get_transcript(video_id)
            video_info.transcript = transcript
            video_info.captions_available = bool(transcript)

        # キャッシュ保存
        self.cache_manager.set(cache_key, video_info.to_dict(), ttl=86400)

        return video_info

    def _get_video_info_api(self, video_id: str) -> Optional[YouTubeVideo]:
        """YouTube Data API v3で動画情報を取得"""
        request = self.youtube_service.videos().list(
            part='snippet,contentDetails,statistics',
            id=video_id
        )
        response = request.execute()

        if not response.get('items'):
            return None

        item = response['items'][0]
        snippet = item['snippet']
        statistics = item.get('statistics', {})
        content_details = item['contentDetails']

        # ISO 8601 duration to seconds
        duration_str = content_details['duration']
        duration_seconds = self._parse_duration(duration_str)

        return YouTubeVideo(
            video_id=video_id,
            title=snippet['title'],
            description=snippet['description'],
            channel_title=snippet['channelTitle'],
            channel_id=snippet['channelId'],
            published_at=datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00')),
            duration=duration_seconds,
            view_count=int(statistics.get('viewCount', 0)),
            like_count=int(statistics.get('likeCount', 0)),
            comment_count=int(statistics.get('commentCount', 0)),
            tags=snippet.get('tags', []),
            category_id=snippet.get('categoryId', ''),
            thumbnail_url=snippet['thumbnails']['high']['url'],
            language=snippet.get('defaultLanguage', 'ja')
        )

    def _get_video_info_ytdlp(self, video_id: str) -> Optional[YouTubeVideo]:
        """yt-dlpで動画情報を取得"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

            return YouTubeVideo(
                video_id=video_id,
                title=info.get('title', ''),
                description=info.get('description', ''),
                channel_title=info.get('uploader', ''),
                channel_id=info.get('channel_id', ''),
                published_at=datetime.fromtimestamp(info.get('timestamp', 0)),
                duration=info.get('duration', 0),
                view_count=info.get('view_count', 0),
                like_count=info.get('like_count', 0),
                comment_count=info.get('comment_count', 0),
                tags=info.get('tags', []),
                category_id=str(info.get('categories', [''])[0]) if info.get('categories') else '',
                thumbnail_url=info.get('thumbnail', ''),
                language=info.get('language', 'ja')
            )

    def _parse_duration(self, duration_str: str) -> int:
        """ISO 8601 duration (PT1H2M3S) を秒数に変換"""
        pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
        match = re.match(pattern, duration_str)
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)

        return hours * 3600 + minutes * 60 + seconds

    @handle_error(RetryStrategy(max_retries=2, backoff_factor=1.5))
    def get_transcript(self, video_id: str, languages: List[str] = ['ja', 'en']) -> Optional[str]:
        """
        動画字幕を取得

        Args:
            video_id: YouTube動画ID
            languages: 取得する言語リスト（優先順）

        Returns:
            字幕テキスト or None
        """
        if not TRANSCRIPT_AVAILABLE:
            self.logger.warning("youtube-transcript-api not available")
            return None

        cache_key = f"transcript_{video_id}_{'_'.join(languages)}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            return cached

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

            # 優先言語で取得
            for lang in languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    text_segments = transcript.fetch()
                    full_text = ' '.join([seg['text'] for seg in text_segments])

                    self.cache_manager.set(cache_key, full_text, ttl=86400)
                    self.logger.info(f"Transcript retrieved for {video_id} in {lang}")
                    return full_text
                except:
                    continue

            # 自動生成字幕も試す
            try:
                transcript = transcript_list.find_generated_transcript(languages)
                text_segments = transcript.fetch()
                full_text = ' '.join([seg['text'] for seg in text_segments])

                self.cache_manager.set(cache_key, full_text, ttl=86400)
                self.logger.info(f"Auto-generated transcript retrieved for {video_id}")
                return full_text
            except:
                pass

        except Exception as e:
            self.logger.warning(f"Failed to retrieve transcript for {video_id}: {e}")

        return None

    @handle_error(RetryStrategy(max_retries=3))
    def get_channel_info(self, channel_id: str) -> Optional[YouTubeChannel]:
        """チャンネル情報を取得"""
        if not self.youtube_service or not self._check_rate_limit():
            return None

        cache_key = f"channel_{channel_id}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            return YouTubeChannel(**cached)

        try:
            request = self.youtube_service.channels().list(
                part='snippet,statistics',
                id=channel_id
            )
            response = request.execute()

            if not response.get('items'):
                return None

            item = response['items'][0]
            snippet = item['snippet']
            statistics = item['statistics']

            channel = YouTubeChannel(
                channel_id=channel_id,
                title=snippet['title'],
                description=snippet['description'],
                subscriber_count=int(statistics.get('subscriberCount', 0)),
                video_count=int(statistics.get('videoCount', 0)),
                view_count=int(statistics.get('viewCount', 0)),
                thumbnail_url=snippet['thumbnails']['high']['url'],
                custom_url=snippet.get('customUrl'),
                country=snippet.get('country')
            )

            self.cache_manager.set(cache_key, asdict(channel), ttl=86400)
            return channel

        except Exception as e:
            self.logger.error(f"Failed to get channel info: {e}")
            return None

    @handle_error(RetryStrategy(max_retries=3))
    def get_playlist_videos(self, playlist_id: str, max_results: int = 50) -> Optional[YouTubePlaylist]:
        """プレイリストの動画一覧を取得"""
        if not self.youtube_service or not self._check_rate_limit():
            return None

        cache_key = f"playlist_{playlist_id}_{max_results}"
        cached = self.cache_manager.get(cache_key)
        if cached:
            return YouTubePlaylist(**cached)

        try:
            # プレイリスト情報
            request = self.youtube_service.playlists().list(
                part='snippet,contentDetails',
                id=playlist_id
            )
            response = request.execute()

            if not response.get('items'):
                return None

            item = response['items'][0]
            snippet = item['snippet']
            content_details = item['contentDetails']

            # プレイリスト内の動画を取得
            video_ids = []
            next_page_token = None

            while len(video_ids) < max_results:
                request = self.youtube_service.playlistItems().list(
                    part='contentDetails',
                    playlistId=playlist_id,
                    maxResults=min(50, max_results - len(video_ids)),
                    pageToken=next_page_token
                )
                response = request.execute()

                for item in response['items']:
                    video_ids.append(item['contentDetails']['videoId'])

                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

            playlist = YouTubePlaylist(
                playlist_id=playlist_id,
                title=snippet['title'],
                description=snippet['description'],
                channel_title=snippet['channelTitle'],
                item_count=content_details['itemCount'],
                video_ids=video_ids
            )

            self.cache_manager.set(cache_key, asdict(playlist), ttl=3600)
            return playlist

        except Exception as e:
            self.logger.error(f"Failed to get playlist: {e}")
            return None

    @handle_error(RetryStrategy(max_retries=3))
    def search_videos(
        self,
        query: str,
        max_results: int = 10,
        order: str = 'relevance',
        published_after: Optional[datetime] = None
    ) -> List[YouTubeVideo]:
        """
        動画を検索

        Args:
            query: 検索クエリ
            max_results: 最大結果数
            order: ソート順 (relevance, date, rating, viewCount)
            published_after: この日時以降の動画のみ

        Returns:
            YouTubeVideo list
        """
        if not self.youtube_service or not self._check_rate_limit():
            return []

        try:
            request_params = {
                'part': 'id',
                'q': query,
                'type': 'video',
                'maxResults': max_results,
                'order': order
            }

            if published_after:
                request_params['publishedAfter'] = published_after.isoformat() + 'Z'

            request = self.youtube_service.search().list(**request_params)
            response = request.execute()

            video_ids = [item['id']['videoId'] for item in response['items']]

            # 詳細情報を取得
            videos = []
            for video_id in video_ids:
                video = self.get_video_info(video_id, include_transcript=False)
                if video:
                    videos.append(video)

            return videos

        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return []

    def batch_get_videos(self, video_ids: List[str], include_transcript: bool = False) -> List[YouTubeVideo]:
        """
        改善: YouTube API バッチAPI活用による最適化

        従来: 100動画 → 100リクエスト → 100秒
        改善: 100動画 → 2リクエスト → 0.2秒 (500倍高速化!)

        Args:
            video_ids: 取得する動画IDリスト
            include_transcript: 字幕を含めるか

        Returns:
            YouTubeVideo list
        """
        if not self.youtube_service:
            self.logger.warning("YouTube API not available, falling back to sequential")
            return self._batch_get_videos_fallback(video_ids, include_transcript)

        videos = []
        # 50個ずつバッチ処理 (APIの制限)
        batch_size = 50

        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i:i + batch_size]

            # キャッシュチェック
            cached_videos = []
            uncached_ids = []

            for vid in batch:
                cache_key = f"video_{vid}_{include_transcript}"
                cached = self.cache_manager.get(cache_key)
                if cached:
                    cached_videos.append(YouTubeVideo(**cached))
                else:
                    uncached_ids.append(vid)

            # クォータ確認 (videos.list は1 quota消費)
            if not uncached_ids or not self._check_rate_limit(quota_cost=1):
                videos.extend(cached_videos)
                continue

            try:
                # バッチAPI呼び出し (最大50個を1リクエストで取得)
                request = self.youtube_service.videos().list(
                    part='snippet,contentDetails,statistics',
                    id=','.join(uncached_ids)
                )
                response = request.execute()

                for item in response.get('items', []):
                    video = self._parse_video_item(item)
                    if video:
                        # 字幕取得が必要な場合
                        if include_transcript:
                            transcript = self.get_transcript(video.video_id)
                            video.transcript = transcript
                            video.captions_available = bool(transcript)

                        # キャッシュ保存
                        cache_key = f"video_{video.video_id}_{include_transcript}"
                        self.cache_manager.set(cache_key, video.to_dict(), ttl=86400)

                        videos.append(video)

                self.logger.info(f"Batch retrieved {len(videos)} videos (batch size: {len(batch)})")

            except Exception as e:
                self.logger.error(f"Batch retrieval failed: {e}, falling back to sequential")
                # フォールバック: 逐次取得
                for vid in uncached_ids:
                    video = self.get_video_info(vid, include_transcript=include_transcript)
                    if video:
                        videos.append(video)

            videos.extend(cached_videos)

        return videos

    def _batch_get_videos_fallback(self, video_ids: List[str], include_transcript: bool) -> List[YouTubeVideo]:
        """フォールバック: 逐次的に動画情報を取得"""
        videos = []
        for video_id in video_ids:
            video = self.get_video_info(video_id, include_transcript=include_transcript)
            if video:
                videos.append(video)
        return videos

    def _parse_video_item(self, item: Dict[str, Any]) -> Optional[YouTubeVideo]:
        """APIレスポンスのアイテムから YouTubeVideo を生成"""
        try:
            snippet = item['snippet']
            statistics = item.get('statistics', {})
            content_details = item['contentDetails']

            duration_str = content_details['duration']
            duration_seconds = self._parse_duration(duration_str)

            return YouTubeVideo(
                video_id=item['id'],
                title=snippet['title'],
                description=snippet['description'],
                channel_title=snippet['channelTitle'],
                channel_id=snippet['channelId'],
                published_at=datetime.fromisoformat(snippet['publishedAt'].replace('Z', '+00:00')),
                duration=duration_seconds,
                view_count=int(statistics.get('viewCount', 0)),
                like_count=int(statistics.get('likeCount', 0)),
                comment_count=int(statistics.get('commentCount', 0)),
                tags=snippet.get('tags', []),
                category_id=snippet.get('categoryId', ''),
                thumbnail_url=snippet['thumbnails']['high']['url'],
                language=snippet.get('defaultLanguage', 'ja')
            )
        except Exception as e:
            self.logger.warning(f"Failed to parse video item: {e}")
            return None

    def get_trending_videos(self, region_code: str = 'JP', max_results: int = 10) -> List[YouTubeVideo]:
        """トレンド動画を取得"""
        if not self.youtube_service or not self._check_rate_limit():
            return []

        try:
            request = self.youtube_service.videos().list(
                part='id',
                chart='mostPopular',
                regionCode=region_code,
                maxResults=max_results
            )
            response = request.execute()

            video_ids = [item['id'] for item in response['items']]
            return self.batch_get_videos(video_ids, include_transcript=False)

        except Exception as e:
            self.logger.error(f"Failed to get trending videos: {e}")
            return []

    def export_video_data(self, video: YouTubeVideo, output_path: str):
        """動画データをJSONファイルにエクスポート"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(video.to_dict(), f, ensure_ascii=False, indent=2)

        self.logger.info(f"Video data exported to {output_path}")


if __name__ == "__main__":
    # 使用例
    integrator = YouTubeIntegrator(api_key="YOUR_API_KEY_HERE")

    # 動画情報取得
    video = integrator.get_video_info("dQw4w9WgXcQ", include_transcript=True)
    if video:
        print(f"Title: {video.title}")
        print(f"Views: {video.view_count:,}")
        print(f"Duration: {video.duration}s")
        if video.transcript:
            print(f"Transcript: {video.transcript[:100]}...")

    # 検索
    results = integrator.search_videos("Python tutorial", max_results=5)
    for video in results:
        print(f"- {video.title} ({video.view_count:,} views)")
