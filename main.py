import re
import json
import uuid
import httpx
import os
import asyncio
import shutil
from urllib.parse import urlencode, unquote, quote

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Record, File, Video
from typing import Optional


@register(
    "qishui_music",
    "西南",
    "汽水音乐解析下载插件，支持搜索歌曲、解析分享链接、下载音频和视频",
    "v1.0.0",
    "https://github.com/ainiaho/astrbot_plugin_qishui_music",
)
class QiShuiMusicPlugin(Star):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, context: Context):
        super().__init__(context)
        self.client = httpx.AsyncClient(
            headers=self.HEADERS,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        self.cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.help_text = """🎵 **汽水音乐插件帮助**

**功能：** 搜索歌曲、解析链接、下载音频/视频、自动发送语音条。

**指令列表：**
1. 搜索歌曲：
   • `/qishui search 歌名`
   • `汽水搜索 歌名`

2. 直接下载（根据歌名）：
   • `/qishui download 歌名`
   • `汽水听歌 歌名`
   *自动搜索并下载第一首匹配的歌曲*

3. 链接解析/下载：
   • `/qishui download 链接`
   • `汽水听歌 链接`
   • `汽水解析 链接`
   *支持汽水音乐分享链接*

4. 帮助：
   • `/qishui help`
   • `汽水帮助`

**注意：** 首次下载可能需要几秒钟下载和转码，之后会缓存。
🔗 官网：https://blog.diepthink.top/"""
        logger.info(f"汽水音乐插件初始化完成，缓存目录: {self.cache_dir}")

    async def terminate(self):
        await self.client.aclose()
        logger.info("汽水音乐插件已关闭")

    def _extract_url(self, text: str) -> Optional[str]:
        match = re.search(r'https?://[^\s<>"\']+', text)
        return match.group(0) if match else (text if text.startswith("http") else None)

    def _format_duration(self, ms: int) -> str:
        if not ms:
            return "00:00"
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    async def search_songs(self, keyword: str, count: int = 5) -> list:
        params = {
            "aid": "386088",
            "device_platform": "windows",
            "device_type": "Windows",
            "os_version": "Windows 11 Home China",
            "fp": "1088932190113307",
            "q": keyword,
            "cursor": 0,
            "search_id": str(uuid.uuid4()),
            "search_method": "input",
        }
        url = f"https://api.qishui.com/luna/pc/search/track?{urlencode(params)}"

        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"搜索请求失败: {e}")
            return []

        results = []
        try:
            result_groups = data.get("result_groups", [])
            if not result_groups:
                return []

            search_data = result_groups[0].get("data", [])
            for item in search_data:
                if len(results) >= count:
                    break

                entity = item.get("entity", {})
                track = entity.get("track", {})
                track_id = track.get("id")
                if not track_id:
                    continue

                title = track.get("name", "未知歌曲")
                duration = track.get("duration", 0)

                artist = "未知歌手"
                artists = track.get("artists", [])
                if artists:
                    names = [a.get("name", "") for a in artists if a.get("name")]
                    if names:
                        artist = " / ".join(names)

                cover = ""
                album = track.get("album", {})
                if album:
                    url_cover = album.get("url_cover", {})
                    if url_cover:
                        urls = url_cover.get("urls", [])
                        uri = url_cover.get("uri", "")
                        template_prefix = url_cover.get("template_prefix", "")
                        if urls and uri:
                            base_url = urls[0]
                            if base_url and template_prefix:
                                cover = f"{base_url}{template_prefix}_{uri}~c5_375x375.jpg"

                share_url = f"https://music.douyin.com/qishui/share/track?track_id={track_id}"

                results.append({
                    "track_id": track_id,
                    "title": title,
                    "artist": artist,
                    "cover": cover,
                    "duration": duration,
                    "share_url": share_url,
                })
        except Exception as e:
            logger.error(f"解析搜索结果失败: {e}")

        return results

    async def parse_link(self, url: str) -> Optional[dict]:
        if not url or not url.startswith("http"):
            logger.error(f"无效的链接格式: {url}")
            return None
        logger.info(f"正在解析链接: {url}")
        try:
            resp = await self.client.head(url)
            final_url = str(resp.url)
        except Exception:
            try:
                resp = await self.client.get(url)
                final_url = str(resp.url)
            except Exception:
                return None

        if "ugc_video" in final_url:
            return await self._parse_ugc_video(final_url)

        track_id = self._extract_track_id(url, final_url)
        if not track_id:
            return None
        return await self._parse_track_page(track_id)

    def _extract_track_id(self, original_url: str, final_url: str) -> Optional[str]:
        match = re.search(r"track_id=(\d+)", final_url)
        if match:
            return match.group(1)

        match = re.search(r"track_id=(\d+)", original_url)
        if match:
            return match.group(1)

        return None

    async def _parse_ugc_video(self, final_url: str) -> Optional[dict]:
        match = re.search(r"ugc_video_id=(\d+)", final_url)
        if not match:
            return None

        video_id = match.group(1)
        page_url = f"https://music.douyin.com/qishui/share/ugc_video?ugc_video_id={video_id}"

        try:
            resp = await self.client.get(page_url)
            html = resp.text
        except Exception:
            return None

        match = re.search(r'_ROUTER_DATA\s*=\s*({[\s\S]*?});', html)
        if not match:
            return None

        try:
            json_str = match.group(1).strip().rstrip(',')
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        try:
            loader = data.get("loaderData", {})
            ugc = loader.get("ugc_video_page", {})
            video_opts = ugc.get("videoOptions", {})

            if not video_opts or "url" not in video_opts:
                return None

            title = video_opts.get("videoName", "")
            if title:
                title = re.sub(r"#.*", "", title).strip()
                title = re.sub(r'["""]', "", title).strip()

            return {
                "type": "ugc_video",
                "video_id": video_opts.get("video_id"),
                "title": title,
                "artist": video_opts.get("artistName", ""),
                "video_url": video_opts.get("url", ""),
                "cover": video_opts.get("coverURL", ""),
                "duration": video_opts.get("duration", 0),
            }
        except Exception:
            return None

    async def _parse_track_page(self, track_id: str) -> Optional[dict]:
        url = f"https://music.douyin.com/qishui/share/track?track_id={track_id}"
        try:
            resp = await self.client.get(url)
            html = resp.text
        except Exception:
            return None

        info = {"track_id": track_id}

        match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(unquote(match.group(1)))
                info["title"] = data.get("name", data.get("title", ""))
                images = data.get("image", data.get("images", []))
                if isinstance(images, list) and images:
                    info["cover"] = images[0]
                elif isinstance(images, str):
                    info["cover"] = images
            except Exception:
                pass

        match = re.search(r'_ROUTER_DATA\s*=\s*({[\s\S]*?});', html)
        if not match:
            match = re.search(r'_ROUTER_DATA\s*=\s*({[\s\S]*?})\s*</script>', html)
        if not match:
            match = re.search(r'_ROUTER_DATA\s*=\s*({[\s\S]*?}})\s*;', html)

        if match:
            try:
                json_str = match.group(1).strip().rstrip(',')
                data = json.loads(json_str)

                loader = data.get("loaderData", {})
                track_page = loader.get("track_page", {})
                audio_option = track_page.get("audioWithLyricsOption", {})

                info["audio_url"] = audio_option.get("url", "")

                lyrics_data = audio_option.get("lyrics", {})
                sentences = lyrics_data.get("sentences", [])
                if sentences:
                    lrc_lines = []
                    for sentence in sentences:
                        start_ms = sentence.get("startMs", 0)
                        words = sentence.get("words", [])
                        text = "".join(w.get("text", "") for w in words if isinstance(w, dict))
                        if text:
                            minutes = start_ms // 60000
                            seconds = (start_ms % 60000) // 1000
                            millis = start_ms % 1000
                            lrc_lines.append(f"[{minutes:02d}:{seconds:02d}.{millis:03d}]{text}")
                    info["lyrics"] = "\n".join(lrc_lines)

                for key in ["title", "trackName", "name"]:
                    if key in audio_option:
                        info.setdefault("title", audio_option[key])

                artist = audio_option.get("artistName", audio_option.get("artist", ""))
                if artist:
                    info["artist"] = artist

            except Exception:
                pass

        if not info.get("audio_url"):
            url_match = re.search(r'"url"\s*:\s*"(https://v\d+-luna\.douyinvod\.com/[^"]+)"', html)
            if url_match:
                info["audio_url"] = url_match.group(1).replace("\\u002F", "/")

        if info.get("audio_url"):
            title = info.get("title", "")
            if title:
                title = re.sub(r"\s*@.*?汽水音乐.*$", "", title).strip()
                title = re.sub(r"[《》（）()]", "", title).strip()
                info["title"] = title
            return info

        return None

    async def _download_file(self, url: str, path: str) -> bool:
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
        except Exception as e:
            logger.error(f"下载文件失败: {e}")
            return False

    def _get_cache_paths(self, identifier: str, ext: str = "") -> dict:
        """获取缓存路径字典"""
        base = os.path.join(self.cache_dir, identifier)
        return {
            "wav": f"{base}.wav",
            "source": f"{base}.{ext}" if ext else None
        }

    async def _get_or_download_media(self, info: dict, identifier: str, url: str, ext: str) -> Optional[str]:
        """统一获取媒体文件，优先使用缓存，无缓存则下载并转换"""
        paths = self._get_cache_paths(identifier, ext)
        wav_path = paths["wav"]
        source_path = paths["source"]

        # 1. 检查是否已经有转换好的语音
        if os.path.exists(wav_path):
            logger.info(f"命中语音缓存: {wav_path}")
            return wav_path

        # 2. 检查是否有源文件
        if source_path and os.path.exists(source_path):
            logger.info(f"命中源文件缓存: {source_path}")
            return await self._convert_to_wav(source_path)

        # 3. 下载源文件
        if source_path and await self._download_file(url, source_path):
            logger.info(f"下载成功并缓存: {source_path}")
            return await self._convert_to_wav(source_path)
            
        return None

    async def _process_download(self, event: AstrMessageEvent, info: dict, source_url: str):
        """
        处理具体的下载、转码和发送逻辑。
        """
        if info.get("type") == "ugc_video":
            media_url = info.get("video_url", "")
            title = info.get("title", "video")
            artist = info.get("artist", "unknown")
            identifier = info.get("video_id", f"vid_{hash(source_url)}")
            ext = "mp4"

            if not media_url:
                yield event.plain_result("获取视频链接失败")
                return

        else:
            media_url = info.get("audio_url", "")
            title = info.get("title", "audio")
            artist = info.get("artist", "unknown")
            identifier = info.get("track_id", f"tid_{hash(source_url)}")
            
            if not media_url:
                yield event.plain_result("获取音频链接失败")
                return

            # 推断音频后缀
            content_type = ""
            try:
                head_resp = await self.client.head(media_url)
                content_type = head_resp.headers.get("content-type", "")
            except Exception:
                pass
                
            if "flac" in content_type:
                ext = "flac"
            elif "mp3" in content_type:
                ext = "mp3"
            else:
                ext = "m4a"

        # 只输出歌名和音频
        # 1. 输出歌名
        song_name = f"{artist} - {title}" if artist != "unknown" else title
        yield event.plain_result(song_name)

        # 2. 下载并发送
        wav_path = await self._get_or_download_media(info, identifier, media_url, ext)
        
        if wav_path and os.path.exists(wav_path):
            yield event.chain_result([Record(file=f"file:///{wav_path}", url=wav_path)])
        else:
            yield event.plain_result("转换失败，请检查 ffmpeg 配置")

    async def _download_by_keyword(self, event: AstrMessageEvent, keyword: str):
        """
        根据关键词搜索并下载第一首歌曲。
        """
        results = await self.search_songs(keyword, count=1)
        if not results:
            yield event.plain_result(f"未找到关于 '{keyword}' 的歌曲")
            return
            
        first_song = results[0]
        share_url = first_song['share_url']
        
        info = await self.parse_link(share_url)
        if not info:
            yield event.plain_result("解析歌曲链接失败")
            return
            
        async for res in self._process_download(event, info, share_url):
            yield res

    async def _convert_to_wav(self, input_path: str) -> Optional[str]:
        """使用 ffmpeg 将文件转换为 wav 格式，用于发送语音"""
        if not os.path.exists(input_path):
            return None
        
        # 检查 ffmpeg 是否存在
        if not shutil.which("ffmpeg"):
            logger.warning("未找到 ffmpeg，无法转换为语音，将发送原文件")
            return None
            
        wav_path = input_path.rsplit('.', 1)[0] + '.wav'
        
        # 优化后的 ffmpeg 命令，专为聊天语音优化：
        # -y: 覆盖输出文件
        # -i: 输入文件
        # -vn: 不处理视频流
        # -acodec pcm_s16le: 音频编码 (PCM)
        # -ar 24000: 采样率降至 24kHz (QQ 语音标准，大幅减小体积)
        # -ac 1: 转为单声道 (体积减半)
        cmd = [
            "ffmpeg", "-y", "-i", input_path, 
            "-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", wav_path
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0 and os.path.exists(wav_path):
                logger.info(f"成功将 {input_path} 转换为 {wav_path}")
                return wav_path
            else:
                logger.error(f"ffmpeg 转换失败: {stderr.decode()}")
                return None
        except Exception as e:
            logger.error(f"ffmpeg 执行异常: {e}")
            return None

    @filter.command_group("qishui")
    def qishui(self):
        pass

    @qishui.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        """显示帮助信息"""
        yield event.plain_result(self.help_text)

    @qishui.command("search")
    async def search(self, event: AstrMessageEvent, keyword: str = ""):
        """搜索歌曲。用法：/qishui search 关键词"""
        if not keyword:
            yield event.plain_result("请输入搜索关键词\n用法：/qishui search 歌曲名或歌手名")
            return

        yield event.plain_result(f"正在搜索: {keyword}...")

        results = await self.search_songs(keyword, count=5)
        if not results:
            yield event.plain_result("未找到相关歌曲")
            return

        msg = f"找到 {len(results)} 首歌曲:\n\n"
        for i, r in enumerate(results, 1):
            duration = self._format_duration(r.get("duration", 0))
            msg += f"{i}. {r['title']} - {r['artist']} [{duration}]\n"
        msg += "\n回复 /qishui download <链接> 下载歌曲"

        yield event.plain_result(msg)

    @qishui.command("parse")
    async def parse(self, event: AstrMessageEvent, url: str = ""):
        """解析汽水音乐分享链接。用法：/qishui parse 链接"""
        target_url = self._extract_url(url) or self._extract_url(event.message_str)
        if not target_url:
            yield event.plain_result("请输入汽水音乐分享链接\n用法：/qishui parse 链接")
            return

        yield event.plain_result("正在解析链接...")

        info = await self.parse_link(target_url)
        if not info:
            yield event.plain_result("解析失败，请检查链接是否正确")
            return

        if info.get("type") == "ugc_video":
            msg = f"🎬 UGC 视频\n"
            msg += f"标题: {info.get('title', '未知')}\n"
            msg += f"作者: {info.get('artist', '未知')}\n"
            msg += f"时长: {info.get('duration', 0):.0f}秒"
        else:
            msg = f"🎵 歌曲信息\n"
            msg += f"歌名: {info.get('title', '未知')}\n"
            msg += f"歌手: {info.get('artist', '未知')}\n"
            if info.get("lyrics"):
                lyrics_preview = info["lyrics"][:200]
                msg += f"\n歌词:\n{lyrics_preview}..."

        yield event.plain_result(msg)

    @qishui.command("download")
    async def download(self, event: AstrMessageEvent, input_str: str = ""):
        """下载汽水音乐音频/视频。支持链接或歌名"""
        full_msg = input_str or event.message_str
        target_url = self._extract_url(full_msg)
        
        # 1. 尝试提取链接
        if target_url:
            # 直接解析，不显示状态信息
            info = await self.parse_link(target_url)
            if not info:
                yield event.plain_result("解析失败，请检查链接是否正确")
                event.stop_event()
                return
            async for res in self._process_download(event, info, target_url):
                yield res
            event.stop_event()
            return

        # 2. 当作歌名直接下载
        keyword = full_msg.replace("/qishui download", "").strip()
        if not keyword:
            yield event.plain_result("请输入链接或歌名\n用法：/qishui download 链接 或 /qishui download 歌名")
            return
            
        async for res in self._download_by_keyword(event, keyword):
            yield res
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        message_str = (event.message_str or "").strip().lstrip("/")

        if message_str.startswith("汽水搜索") or message_str.startswith("汽水搜"):
            keyword = message_str.replace("汽水搜索", "").replace("汽水搜", "").strip()
            if not keyword:
                yield event.plain_result("请输入搜索关键词\n用法：汽水搜索 歌曲名")
                event.stop_event()
                return

            results = await self.search_songs(keyword, count=5)
            if not results:
                yield event.plain_result("未找到相关歌曲")
                event.stop_event()
                return

            msg = f"找到 {len(results)} 首歌曲:\n\n"
            for i, r in enumerate(results, 1):
                duration = self._format_duration(r.get("duration", 0))
                msg += f"{i}. {r['title']} - {r['artist']} [{duration}]\n"
            msg += "\n回复 汽水听歌 歌名 或 /qishui download 链接 下载歌曲"
            yield event.plain_result(msg)
            event.stop_event()

        elif message_str.startswith("汽水解析"):
            url = self._extract_url(message_str)
            if not url:
                yield event.plain_result("请输入汽水音乐分享链接\n用法：汽水解析 链接")
                event.stop_event()
                return

            info = await self.parse_link(url)
            if not info:
                yield event.plain_result("解析失败，请检查链接是否正确")
                event.stop_event()
                return

            if info.get("type") == "ugc_video":
                msg = f"🎬 UGC 视频\n"
                msg += f"标题: {info.get('title', '未知')}\n"
                msg += f"作者: {info.get('artist', '未知')}\n"
                msg += f"时长: {info.get('duration', 0):.0f}秒"
            else:
                msg = f"🎵 歌曲信息\n"
                msg += f"歌名: {info.get('title', '未知')}\n"
                msg += f"歌手: {info.get('artist', '未知')}\n"
                if info.get("lyrics"):
                    lyrics_preview = info["lyrics"][:200]
                    msg += f"\n歌词:\n{lyrics_preview}..."

            yield event.plain_result(msg)
            event.stop_event()

        elif message_str.startswith("汽水听歌"):
            query = message_str.replace("汽水听歌", "").strip()
            target_url = self._extract_url(query)
            
            # 1. 尝试提取链接
            if target_url:
                # 直接解析，不显示状态信息
                info = await self.parse_link(target_url)
                if not info:
                    yield event.plain_result("解析失败，请检查链接是否正确")
                    event.stop_event()
                    return
                async for res in self._process_download(event, info, target_url):
                    yield res
                event.stop_event()
                return

            # 2. 如果既不是链接，当作歌名直接下载
            if query:
                async for res in self._download_by_keyword(event, query):
                    yield res
                event.stop_event()
                return

            yield event.plain_result("请输入链接或歌名\n用法：汽水听歌 链接 或 汽水听歌 歌名")
            event.stop_event()

        elif message_str.startswith("汽水帮助"):
            yield event.plain_result(self.help_text)
            event.stop_event()

