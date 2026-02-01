# Emby Strm Doctor

Emby Strm Doctor 是一个用于修复 Emby 媒体库中 .strm 文件的 Docker 工具。它通过调用 Emby API 强制刷新媒体项，帮助提取媒体信息。特别优化了针对网盘挂载（如 115、阿里云盘、Google Drive）场景的防风控机制。

## 功能特点

*   **Web UI 管理界面**：基于 HTML + Tailwind CSS (深色模式)，简洁易用。
*   **安全扫描机制**：支持自定义扫描间隔，防止触发网盘 API 风控 (429/403)。
*   **智能暂停**：检测到 HTTP 429/403 错误时自动暂停任务，保护账号安全。
*   **实时反馈**：通过 WebSocket 实时展示扫描进度和日志。
*   **Docker 部署**：提供 Dockerfile 和 docker-compose.yml，一键部署。

## 快速开始

### 1. 安装与启动

#### 方法一：使用 Docker (推荐)

确保已安装 Docker 和 Docker Compose。

```bash
# 构建并启动容器
docker compose up -d --build
```

#### 方法二：本地直接运行 (如果 Docker 不可用)

如果您没有安装 Docker，可以直接在本地运行 Python 代码：

1.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```

2.  **启动服务**
    ```bash
    python main.py
    ```

访问 Web 界面：`http://localhost:5000`

### 2. 配置

在设置页面 (Settings) 输入您的 Emby 服务器信息：

*   **Emby Host**: 例如 `http://192.168.1.100:8096`
*   **API Key**: 在 Emby 控制台 -> 高级 -> API 密钥 中生成。
*   **User ID**: 任意管理员用户的 ID (可以在浏览器 URL 或 Emby 用户页面找到)。
*   **安全请求间隔**: 默认为 5 秒。**警告**：如果您使用网盘挂载，请务必保持在 5 秒以上，以免被封禁。

### 3. 使用

1.  在“任务面板”选择要修复的媒体库。
2.  点击“开始修复”。
3.  观察下方实时日志，任务会自动逐个刷新媒体项。

## 开发说明

### 技术栈

*   **后端**: Python (FastAPI)
*   **前端**: HTML, Tailwind CSS (CDN), JavaScript
*   **数据存储**: JSON (config.json)

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行服务
uvicorn main:app --reload --port 5000
```

## 注意事项

*   本工具仅调用 Emby 的刷新接口，不会修改您的源文件。
*   请务必合理设置扫描间隔，避免对 Emby 服务器或后端存储造成过大压力。

## 许可证

MIT
