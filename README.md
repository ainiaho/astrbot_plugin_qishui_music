# 汽水音乐 AstrBot 插件

汽水音乐解析下载插件，支持搜索歌曲、解析分享链接、下载音频和视频。

## 功能

- **自动转语音**：下载音频或提取视频音频后，自动发送为聊天语音条。
- **本地缓存**：自动缓存源文件和语音文件，重复发送秒响应。
- **智能搜索**：搜索后可直接回复编号下载歌曲。

## 安装

将插件目录复制到 AstrBot 的 `data/plugins/` 目录下：

```bash
cp -r astrbot_plugin_qishui_music /path/to/AstrBot/data/plugins/
```

重启 AstrBot 或在管理面板中重载插件。

## 功能

### 命令方式

| 命令 | 功能 |
|------|------|
| `/qishui search 歌名` | 搜索歌曲 |
| `/qishui parse 链接` | 解析分享链接 |
| `/qishui download 歌名/链接` | 下载音频/视频 |

### 自然语言方式

| 触发词 | 功能 |
|--------|------|
| `汽水搜索 歌名` | 搜索歌曲 |
| `汽水解析 链接` | 解析分享链接 |
| `汽水听歌 歌名/链接` | 下载音频/视频 |
| `汽水帮助` | 查看帮助信息 |

## 示例

**1. 直接根据歌名听歌**
```
用户：汽水听歌 晴天
Bot：周杰伦 - 晴天
[发送语音条]
```

**2. 解析链接听歌**
```
用户：汽水听歌 https://qishui.douyin.com/s/xxxxxx/
Bot：周杰伦 - 晴天
[发送语音条]
```

## 前置依赖

- **Python 库**: httpx>=0.27.0 (插件会自动安装)
- **系统工具**: ffmpeg (必需，用于将媒体文件转换为聊天平台支持的语音格式)

### 安装 ffmpeg
如果是 Docker 部署的 AstrBot，请进入容器内安装：
```bash
# Debian/Ubuntu
docker exec -it <容器名> apt-get update && apt-get install -y ffmpeg

# Alpine 
docker exec -it <容器名> apk add ffmpeg
```

## 缓存机制
插件会在 `plugins/astrbot_plugin_qishui_music/cache/` 目录下自动缓存媒体文件。
- 首次请求：下载源文件 -> 转为 WAV -> 发送。
- 再次请求：直接使用缓存的 WAV 文件发送，速度极快。

### 小白一个，哪里写的不好见谅

## 更多信息

- **作者**: 西南
- **仓库**: https://github.com/ainiaho/astrbot_plugin_qishui_music
- **官网**: https://blog.diepthink.top/
