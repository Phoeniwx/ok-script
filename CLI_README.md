# ok-cli - ok-script 命令行工具

ok-script 的命令行封装，方便 AI agent 通过 bash 调用屏幕自动化功能。

## 特性

- **持久化守护进程**：连接后启动后台 daemon 进程，保持捕获状态
- **多捕获方法支持**：自动尝试 WGC、BitBlt、DXGI 等捕获方式
- **JSON 输出**：所有命令输出结构化 JSON，便于程序解析
- **静默输出**：交互命令只返回最终结果，无冗余日志
- **连接自清理**：发现 daemon 不可访问时会移除过期连接记录

## 安装

```bash
pip install ok-script
```

## 全局选项

所有操作命令都支持以下选项：

- `--cid <连接ID>` / `--connection-id <连接ID>` - 指定要使用的连接（默认使用最新连接）

## 支持的命令

### 连接相关
- `ok-cli connect --desktop` - 连接桌面模式（自动选择可见窗口）
- `ok-cli connect --exe <程序名.exe>` - 通过 exe 连接窗口
- `ok-cli connect --title "窗口标题"` - 通过标题连接窗口
- `ok-cli disconnect` - 断开最新连接
- `ok-cli disconnect --cid <连接ID>` - 断开指定连接
- `ok-cli list-connections` - 列出所有保存的连接

### 屏幕信息
- `ok-cli screen-info` - 获取屏幕分辨率和当前捕获方法

### 截图
- `ok-cli screenshot --output <文件路径.png>` - 保存截图
- `ok-cli crop --x <x> --y <y> --size <边长> --output <文件路径.png>` - 以截图坐标为中心裁剪方形小图
- `ok-cli crop-rel --x <0-1> --y <0-1> --size <边长> --output <文件路径.png>` - 以相对坐标为中心裁剪方形小图

### 鼠标操作
- `ok-cli click --x <x> --y <y>` - 点击绝对坐标
- `ok-cli click --x <x> --y <y> --button <left/right/middle>` - 指定鼠标按钮点击
- `ok-cli click-rel --x <0-1> --y <0-1>` - 相对坐标点击
- `ok-cli swipe --fx <x> --fy <y> --tx <x> --ty <y> --duration <秒>` - 滑动手势
- `ok-cli scroll --x <x> --y <y> --amount <数量>` - 滚动

鼠标命令默认接收截图坐标：如果 `screenshot` 输出是 `1576x1051`，就在这张截图上读取目标中心点并直接传给 `click`。daemon 会在内部按窗口实际可点击区域自动换算，调用方不需要处理 DPI 或 client 尺寸差异。

如果不确定目标中心点是否正确，可以先用 `crop` 裁出小图验证。例如：

```bash
ok-cli crop --x 243 --y 55 --size 80 --output gear-check.png
```

### 键盘操作
- `ok-cli key --key <键名>` - 按键 (enter/esc/f1/a/...)
- `ok-cli text --content <文本>` - 输入文本

### OCR（可选）
- `ok-cli ocr` - 全屏 OCR
- `ok-cli ocr --region <x> <y> <w> <h>` - 指定区域 OCR

OCR 依赖调用方项目提供可用的 `ocr` / `template_matching` 配置。默认 CLI 连接只初始化 Windows 捕获和交互能力，如果未提供 OCR 能力会返回明确错误。

### 图像和颜色查找
- `ok-cli find-image --template <模板图片.png> --threshold <0-1>` - 模板匹配
- `ok-cli find-color --hex <RRGGBB> --threshold <0-1>` - 颜色查找

## 输出格式

所有命令输出 JSON：

成功：
```json
{"success": true, "data": {...}}
```

失败：
```json
{"success": false, "error": "错误信息"}
```

## 架构说明

### 守护进程模式

`connect` 命令启动一个后台守护进程（daemon），后续所有命令通过本机 HTTP IPC 与该进程通信：

```
ok-cli connect --desktop
  → 启动 daemon 进程
  → daemon 初始化 OK 实例，复用 DeviceManager 启动捕获和交互
  → 保存连接信息到 ~/.ok-cli/connections.json
  → 返回连接成功

ok-cli click --x 100 --y 200
  → CLI 读取 connections.json 获取 daemon 端口
  → 发送 HTTP 请求到 daemon
  → daemon 执行点击（使用已初始化的捕获状态）
  → 返回结果

ok-cli disconnect
  → 发送 shutdown 命令到 daemon
  → daemon 清理资源并退出
  → 从 connections.json 删除连接
```

### 日志

Daemon 日志写入 `~/.ok-cli/daemon-<连接ID>.log`，stderr 写入 `~/.ok-cli/daemon-<连接ID>.stderr`，可用于排查连接和捕获初始化问题。

## 使用示例

### 基础使用流程

```bash
# 连接桌面
ok-cli connect --desktop
# {"success": true, "data": {"success": true, "mode": "desktop", "connection_id": "a1b2c3d4", "screen_info": {...}}}

# 获取屏幕信息（使用已建立的连接，无重新初始化延迟）
ok-cli screen-info
# {"success": true, "data": {"width": 1920, "height": 1080, "mode": "desktop", "capture_method": "WindowsGraphicsCaptureMethod"}}

# 截图
ok-cli screenshot --output screen.png

# 点击
ok-cli click --x 100 --y 200
# 坐标来源于 screenshot 图片，不需要手动换算 DPI/client 坐标

# 断开
ok-cli disconnect
```

### 多连接管理

```bash
# 创建多个连接
ok-cli connect --desktop
ok-cli connect --exe "Game.exe"

# 列出所有连接
ok-cli list-connections
# {"success": true, "data": {"latest": "...", "connections": {...}}}

# 对指定连接操作
ok-cli screenshot --cid a1b2c3d4 --output desktop.png
ok-cli screenshot --cid d4c3b2a1 --output game.png

# 断开指定连接
ok-cli disconnect --cid a1b2c3d4
```

### 连接指定窗口

```bash
# 通过 exe 名称连接
ok-cli connect --exe "notepad.exe"

# 通过窗口标题连接
ok-cli connect --title "记事本"
```

## 持久化连接状态

连接信息保存在 `~/.ok-cli/connections.json`：

```json
{
  "latest": "a1b2c3d4",
  "connections": {
    "a1b2c3d4": {
      "mode": "desktop",
      "target": {"type": "desktop"},
      "config": {...},
      "created": "2026-04-24T10:00:00",
      "daemon": {
        "pid": 12345,
        "port": 54321,
        "started": "2026-04-24T10:00:01"
      }
    }
  }
}
```

- 每个连接有唯一的 8 位 ID
- `latest` 指向最新创建的连接
- 未指定 `--cid` 时自动使用 `latest` 连接
- `daemon` 字段记录守护进程 pid、port 和启动时间

## 错误处理

- **连接断开**：如果 daemon 不响应，输出错误提示 `Connection lost. Run 'ok-cli disconnect --cid <id>' then 'ok-cli connect' to reconnect.`
- **命令执行失败**：返回 `{"success": false, "error": "具体错误信息"}`
- **捕获未就绪**：返回 `capture is not ready yet` 或 daemon 初始化失败原因，通常可查看 daemon 日志定位窗口查找或捕获方法问题。
- **OCR 不可用**：返回默认 CLI 配置不支持 OCR 的错误，需要由调用方提供完整 OK OCR 配置后再启用。

## 验证

```bash
# 只跑无副作用检查
python test_ok_cli.py

# 跑真实桌面连接、截图和断开流程
python test_ok_cli.py --live
```
