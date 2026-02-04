import asyncio
import logging
import time
from typing import List, Optional, Set
from fastapi import WebSocket
import httpx
from collections import deque
import traceback
import datetime
from emby_client import EmbyClient
from config import load_config
from database import Database

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Send buffered logs to new connections
        try:
            from task_manager import task_manager  # local import to avoid circular
            for msg in task_manager.log_buffer:
                try:
                    await websocket.send_text(msg)
                except Exception:
                    pass
        except Exception:
            pass

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Append to buffer
        try:
            from task_manager import task_manager  # local import to avoid circular
            task_manager.log_buffer.append(message)
        except Exception:
            pass
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

class TaskManager:
    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.current_task: Optional[asyncio.Task] = None
        self.current_library_id: Optional[str] = None
        self.stats = {"total": 0, "processed": 0, "success": 0}
        self.log_buffer = deque(maxlen=2000)
        self.db = Database()

    async def start_task(self, library_id: str, force: bool = False):
        if self.is_running:
            return False, "Task already running"
        
        self.should_stop = False
        self.is_running = True
        self.current_library_id = library_id
        self.stats = {"total": 0, "processed": 0, "success": 0}
        self.current_task = asyncio.create_task(self._process_library(library_id, force))
        return True, "Task started"

    async def stop_task(self):
        if not self.is_running:
            return False, "No task running"
        
        self.should_stop = True
        if self.current_task:
            await self.current_task
        return True, "Task stopped"

    async def _process_library(self, library_id: str, force: bool):
        config = load_config()
        client = EmbyClient(config.emby_host, config.api_key, config.user_id)
        exclude_lines = [l.strip() for l in (config.exclude_paths or "").splitlines() if l.strip()]
        
        try:
            # 1. Identity Pre-check
            await manager.broadcast("[系统] 正在验证身份...")
            try:
                user_info = await client.get_user_info()
                user_name = user_info.get("Name", "Unknown")
                user_id_check = user_info.get("Id", "Unknown")
                await manager.broadcast(f"[系统] 身份确认: 当前操作用户为 <strong>{user_name}</strong> (ID: {user_id_check})")
            except httpx.HTTPStatusError as e:
                error_body = e.response.text
                await manager.broadcast(f"[系统] 身份验证失败: HTTP {e.response.status_code}")
                await manager.broadcast(f"<pre class='text-xs bg-gray-800 p-2 rounded mt-1'>{error_body}</pre>")
                return
            except Exception as e:
                await manager.broadcast(f"[系统] 身份验证异常: {str(e)}")
                return
            last_sync = self.db.get_config("last_sync_time")
            full_mode = force or (not last_sync)
            if full_mode:
                await manager.broadcast("[系统] 全量扫描模式")
            else:
                await manager.broadcast(f"[系统] 增量同步模式: 起始时间 {last_sync}")
            scanned_ids: Set[str] = set()
            pending_items = []
            skipped_count = 0
            total_found = 0
            async for batch in client.get_items(library_id, None if full_mode else last_sync):
                total_found += len(batch)
                for item in batch:
                    path = item.get("Path", "") or ""
                    name = item.get("Name", "Unknown")
                    item_id = item.get("Id")
                    media_streams = item.get("MediaStreams", [])
                    if full_mode and item_id:
                        scanned_ids.add(item_id)
                    p_lower = path.lower()
                    if not p_lower.endswith(".strm"):
                        continue
                    if any(excl in p_lower for excl in exclude_lines):
                        await manager.broadcast(f"[跳过] 黑名单: {name} -> {path}")
                        if item_id:
                            self.db.set_media_status(item_id, name, path, "ignored")
                        continue
                    if media_streams and len(media_streams) > 0:
                        skipped_count += 1
                        logger.info(f"[跳过] {name} 已包含元数据")
                        if item_id:
                            self.db.set_media_status(item_id, name, path, "ignored")
                        continue
                    # DB checks
                    status_row = self.db.get_media_status(item_id) if item_id else None
                    if status_row and status_row.get("status") == "success":
                        continue
                    if status_row and status_row.get("status") == "failed" and int(status_row.get("retry_count") or 0) >= 3 and (not force):
                        continue
                    pending_items.append(item)
            total_strm_todo = len(pending_items)
            self.stats["total"] = total_strm_todo
            await manager.broadcast(f"扫描完成: 共发现 {total_found} 个项目。")
            await manager.broadcast(f"智能过滤: {skipped_count} 个 .strm 文件已有媒体信息或被黑名单忽略。")
            await manager.broadcast(f"待修复队列: {total_strm_todo} 个文件。")
            if total_strm_todo == 0:
                await manager.broadcast("所有 .strm 文件均正常或已忽略，任务结束。")
                if full_mode:
                    db_ids = set(self.db.get_all_ids())
                    missing = list(db_ids - scanned_ids)
                    removed = self.db.delete_ids(missing)
                    await manager.broadcast(f"[清理] 发现 {removed} 个已删除项目，已从数据库移除")
                self.db.set_config("last_sync_time", datetime.datetime.utcnow().isoformat() + "Z")
                return

            # Apply batch size limit
            batch_size = config.batch_size
            items = pending_items
            if batch_size > 0 and total_strm_todo > batch_size:
                items = pending_items[:batch_size]
                await manager.broadcast(f"配置限制: 仅处理前 {batch_size} 个文件 (剩余 {total_strm_todo - batch_size} 个将在下次处理)。")
                total_strm_todo = batch_size
                self.stats["total"] = batch_size

            await manager.broadcast("准备开始修复任务...")

            for index, item in enumerate(items):
                if self.should_stop:
                    await manager.broadcast("[系统] 用户已手动终止任务")
                    break

                name = item.get('Name', 'Unknown')
                item_id = item.get('Id')
                logger.info(f"[探测] 正在处理: {name} (ID: {item_id})...")
                
                await manager.broadcast(f"[{index + 1}/{total_strm_todo}] 正在探测: {name}...")
                
                try:
                    # 1. Low Bitrate Trick (Force Probe)
                    await client.refresh_item(item_id)
                    
                    # 2. Post-Check Verification (Wait & Verify)
                    # Wait for Emby to process the probe result (DB write)
                    await asyncio.sleep(2) 
                    
                    updated_item = await client.get_item_details(item_id)
                    media_streams = updated_item.get('MediaStreams', [])
                    
                    if media_streams and len(media_streams) > 0:
                        # Extract rich info for logging
                        video_stream = next((s for s in media_streams if s.get('Type') == 'Video'), {})
                        width = video_stream.get('Width')
                        height = video_stream.get('Height')
                        codec = video_stream.get('Codec', 'Unknown').upper()
                        
                        # Format resolution (e.g., 3840x2160 -> 4K)
                        res_str = f"{width}x{height}"
                        if width and width >= 3800: res_str = "4K"
                        elif width and width >= 1900: res_str = "1080p"
                        elif width and width >= 1200: res_str = "720p"
                        
                        # Format duration
                        run_ticks = updated_item.get('RunTimeTicks', 0)
                        duration_str = ""
                        if run_ticks:
                            total_seconds = run_ticks / 10000000
                            hours = int(total_seconds // 3600)
                            minutes = int((total_seconds % 3600) // 60)
                            if hours > 0: duration_str = f" | {hours}h {minutes}m"
                            else: duration_str = f" | {minutes}m"
                        
                        logger.info(f"[成功] {name} 获取到信息: {res_str} {codec}{duration_str}")
                        self.stats["success"] += 1
                        self.db.set_media_status(item_id, name, item.get("Path", ""), "success", f"{res_str} {codec}{duration_str}")
                            
                        await manager.broadcast(f"[{index + 1}/{total_strm_todo}] 成功: {name} ({res_str} {codec}{duration_str})")
                    else:
                        await manager.broadcast(f"[{index + 1}/{total_strm_todo}] 失败: {name} - Emby 无法读取文件头 (可能是坏链或网盘超时)")
                        self.db.set_media_status(item_id, name, item.get("Path", ""), "failed", None, True)
                        
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in [403, 429]:
                        await manager.broadcast(f"错误: {e.response.status_code} - 可能触发风控，任务自动停止！")
                        if e.response.status_code == 403:
                             await manager.broadcast(f"<pre class='text-xs bg-gray-800 p-2 rounded mt-1'>{e.response.text}</pre>")
                        logger.error(f"Rate limit or Forbidden hit: {e}")
                        break
                    else:
                        await manager.broadcast(f"[{index + 1}/{total_strm_todo}] 失败: {name} (HTTP {e.response.status_code})")
                        self.db.set_media_status(item_id, name, item.get("Path", ""), "failed", None, True)
                except Exception as e:
                    await manager.broadcast(f"[{index + 1}/{total_strm_todo}] 异常: {name} ({str(e)})")
                    self.db.set_media_status(item_id, name, item.get("Path", ""), "failed", None, True)
                finally:
                    self.stats["processed"] += 1

                # Sleep logic with interruption check
                sleep_time = config.scan_interval
                for _ in range(sleep_time):
                    if self.should_stop:
                        break
                    await asyncio.sleep(1)
                
                if self.should_stop:
                    await manager.broadcast("[系统] 用户已手动终止任务")
                    break
            
            if not self.should_stop:
                await manager.broadcast("任务完成！")
                if full_mode:
                    db_ids = set(self.db.get_all_ids())
                    missing = list(db_ids - scanned_ids)
                    removed = self.db.delete_ids(missing)
                    await manager.broadcast(f"[清理] 发现 {removed} 个已删除项目，已从数据库移除")
                self.db.set_config("last_sync_time", datetime.datetime.utcnow().isoformat() + "Z")

        except Exception as e:
            await manager.broadcast(f"系统错误: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.is_running = False
            self.current_task = None

task_manager = TaskManager()
