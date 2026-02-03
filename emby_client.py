import httpx
import logging

logger = logging.getLogger(__name__)

class EmbyClient:
    def __init__(self, host: str, api_key: str, user_id: str):
        self.host = host.rstrip('/')
        self.api_key = api_key
        self.user_id = user_id
        self.headers = {
            "X-Emby-Token": self.api_key,
            "Content-Type": "application/json"
        }

    async def validate_connection(self):
        url = f"{self.host}/System/Info"
        async with httpx.AsyncClient() as client:
            logger.info(f"验证连接 [GET]: {url}")
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            return True

    async def get_user_info(self):
        """Fetch user info to validate identity."""
        url = f"{self.host}/Users/{self.user_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            return resp.json()

    async def get_libraries(self):
        """Get all media libraries."""
        url = f"{self.host}/Users/{self.user_id}/Views"
        async with httpx.AsyncClient() as client:
            logger.info(f"获取媒体库 [GET]: {url}")
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            return resp.json().get("Items", [])

    async def get_items(self, parent_id: str):
        """Recursively get all items (Video/Audio) from a library."""
        # Note: Depending on library size, we might want to paginate or use specific filters.
        # For simplicity, we'll fetch all items that are likely to be strm files (Movies, Episodes).
        # We filter by 'Video' and 'Audio' types.
        url = f"{self.host}/Users/{self.user_id}/Items"
        params = {
            "ParentId": parent_id,
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode,Audio",
            "Fields": "Path,MediaStreams,ProviderIds", 
        }
        logger.debug(f"Fetching items from {url} with params: {params}")
        async with httpx.AsyncClient() as client:
            logger.info(f"正在获取列表 [GET]: {url} | 参数: {params}")
            resp = await client.get(url, headers=self.headers, params=params, timeout=60.0)
            resp.raise_for_status()
            return resp.json().get("Items", [])

    async def refresh_item(self, item_id: str):
        """
        Force Emby to probe the file by requesting PlaybackInfo with extremely low bitrate.
        This forces ffmpeg probe because Emby thinks bandwidth is insufficient for direct play.
        """
        url = f"{self.host}/Items/{item_id}/PlaybackInfo"
        
        # We use POST with a body to simulate a real playback request
        # MaxStreamingBitrate=1 forces transcoding check which triggers probe
        data = {
            "UserId": self.user_id,
            "MaxStreamingBitrate": 1, 
            "StartTimeTicks": 0,
            "AudioStreamIndex": 0,
            "SubtitleStreamIndex": -1,
            "MediaSourceId": item_id,
            "AutoOpenLiveStream": False,
            "EnableDirectPlay": False,
            "EnableDirectStream": False
        }
        
        logger.debug(f"Refreshing item {item_id} via {url} with data: {data}")
        async with httpx.AsyncClient() as client:
            logger.info(f"触发探测 [POST]: {url} | 码率限制: {data.get('MaxStreamingBitrate')}")
            resp = await client.post(url, headers=self.headers, json=data, timeout=60.0)
            resp.raise_for_status()
            return True

    async def get_item_details(self, item_id: str):
        """Fetch full item details to verify MediaStreams."""
        url = f"{self.host}/Users/{self.user_id}/Items/{item_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
