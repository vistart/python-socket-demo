# Python Async Socket Communication Framework

这是一个基于Python asyncio的TCP和Unix套接字通信框架，支持文件命令和交互式两种客户端模式。

## 功能特性

- 支持TCP和Unix套接字通信
- 提供文件命令和交互式两种客户端模式
- 基于asyncio的异步实现
- 内置会话管理和心跳机制
- JSON格式消息支持
- 模块化和可扩展的设计

## 安装

### 依赖要求

- Python 3.7+
- aioconsole

安装依赖：
```bash
pip install aioconsole
```

### 文件结构

```
.
├── README.md
├── base_client.py          # 客户端基类
├── message.py             # 消息处理
├── tcp_interfaces.py      # 接口定义
├── tcp_server.py         # TCP服务器实现
├── tcp_client.py         # TCP客户端实现
├── unix_server.py        # Unix套接字服务器实现
└── unix_client.py        # Unix套接字客户端实现
```

## 使用方法

### TCP服务器

启动TCP服务器：
```bash
python tcp_server.py [host] [port]
```

参数说明：
- host: 服务器地址（默认：localhost）
- port: 端口号（默认：9999）

### TCP客户端

1. 文件命令模式：
```bash
python tcp_client.py file messages.txt [host] [port]
```

2. 交互式模式：
```bash
python tcp_client.py interactive [host] [port]
```

参数说明：
- messages.txt: 包含命令的文件
- host: 服务器地址（默认：localhost）
- port: 端口号（默认：9999）

### Unix套接字服务器

启动Unix套接字服务器：
```bash
python unix_server.py [socket_path]
```

参数说明：
- socket_path: Unix套接字文件路径（默认：/tmp/chat.sock）

### Unix套接字客户端

1. 文件命令模式：
```bash
python unix_client.py file messages.txt [socket_path]
```

2. 交互式模式：
```bash
python unix_client.py interactive [socket_path]
```

参数说明：
- messages.txt: 包含命令的文件
- socket_path: Unix套接字文件路径（默认：/tmp/chat.sock）

## 消息文件格式

消息文件（如messages.txt）的格式为每行一条命令：
```
Hello Server
How are you?
exit
```

注意：
- 每行一条命令
- exit命令将终止客户端
- 空行会被忽略

## 交互式使用

在交互式模式下：
1. 使用 `>` 提示符输入命令
2. 输入 `exit` 退出
3. Ctrl+C 可以强制退出

## 开发指南

### 消息格式

所有消息都使用JSON格式，基本结构为：
```json
{
    "type": "message",
    "content": "消息内容",
    "session_id": "会话ID"
}
```

消息类型包括：
- message: 普通消息
- heartbeat: 心跳包
- session_init: 会话初始化
- session_ack: 会话确认

### 扩展开发

1. 继承基类创建新的客户端：
```python
from base_client import BaseAsyncClient

class MyCustomClient(BaseAsyncClient):
    # 实现自定义功能
    pass
```

2. 实现新的消息处理器：
```python
from tcp_interfaces import IMessageHandler

class MyMessageHandler(IMessageHandler):
    # 实现自定义消息处理
    pass
```

## 注意事项

1. Unix套接字功能仅在Unix/Linux/macOS系统上可用
2. 确保有适当的文件系统权限创建Unix套接字
3. 服务器异常退出可能需要手动清理Unix套接字文件
4. 推荐在虚拟环境中安装依赖

## 错误处理

常见错误及解决方法：

1. 端口被占用：
   - 使用不同的端口号
   - 检查并关闭占用端口的进程

2. Unix套接字文件已存在：
   - 手动删除套接字文件
   - 确认没有其他程序正在使用该套接字

3. 权限问题：
   - 确保有创建和访问套接字文件的权限
   - 检查目录权限设置

## 调试建议

1. 启用详细日志：
   - 所有关键操作都有日志输出
   - 错误信息包含异常详情

2. 使用文件模式测试：
   - 创建测试命令文件
   - 观察服务器端的响应

3. 心跳超时设置：
   - 可以通过修改服务器的timeout参数调整
   - 默认超时时间为10秒，最大重试3次

## 许可证

[Affero GNU License v3](LICENSE)
