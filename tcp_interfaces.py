from abc import ABC, abstractmethod
import asyncio
from typing import Optional, Dict, Any, Tuple


class ISession(ABC):
    """会话接口,定义单个客户端连接的会话管理功能"""

    @property
    @abstractmethod
    def session_id(self) -> str:
        """获取会话唯一标识符

        Returns:
            str: 唯一的会话ID
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """获取会话连接状态

        Returns:
            bool: 会话是否处于连接状态
        """
        pass

    @property
    @abstractmethod
    def last_heartbeat(self) -> float:
        pass

    @property
    @abstractmethod
    def writer(self) -> asyncio.StreamWriter:
        pass

    @abstractmethod
    def update_heartbeat(self) -> None:
        """更新最后一次心跳时间"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭并清理会话"""
        pass


class IServer(ABC):
    """TCP服务器接口,定义服务器核心功能"""

    @abstractmethod
    async def start(self) -> None:
        """启动服务器并开始监听连接

        服务器将开始监听指定端口,接受新的客户端连接并为每个连接创建会话
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止服务器并清理所有资源

        关闭所有活动的客户端连接,清理会话,停止服务器
        """
        pass

    @abstractmethod
    async def handle_client(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter
    ) -> None:
        """处理新的客户端连接

        Args:
            reader: 用于从客户端读取数据的StreamReader
            writer: 用于向客户端写入数据的StreamWriter
        """
        pass

    @abstractmethod
    async def process_message(
            self,
            session: ISession,
            message: dict
    ) -> None:
        """处理从客户端接收到的消息

        Args:
            session: 消息来源的会话对象
            message: 解析后的消息内容
        """
        pass

    @abstractmethod
    async def send_message(
            self,
            session: ISession,
            message: dict
    ) -> None:
        """向指定会话发送消息

        Args:
            session: 目标会话对象
            message: 要发送的消息内容
        """
        pass


class IClient(ABC):
    """TCP客户端接口,定义客户端核心功能"""

    @abstractmethod
    async def connect(self) -> bool:
        """连接到服务器

        Returns:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开与服务器的连接并清理资源"""
        pass

    @abstractmethod
    async def start(self, message_source: str) -> None:
        """启动客户端并开始消息处理

        Args:
            message_source: 消息来源(如文件路径)
        """
        pass

    @abstractmethod
    async def send_message(self, content: str) -> None:
        """发送消息到服务器

        Args:
            content: 要发送的消息内容
        """
        pass

    @abstractmethod
    async def receive_messages(self) -> None:
        """接收并处理来自服务器的消息"""
        pass

    @abstractmethod
    async def send_heartbeat(self, interval: int = 5) -> None:
        """发送心跳包到服务器

        Args:
            interval: 心跳包发送间隔(秒)
        """
        pass


class IMessageHandler(ABC):
    """消息处理器接口,定义消息的编码解码和验证"""

    @abstractmethod
    def encode_message(self, message: Dict[str, Any]) -> bytes:
        """将消息对象编码为字节串

        Args:
            message: 要编码的消息对象

        Returns:
            bytes: 编码后的字节串
        """
        pass

    @abstractmethod
    def decode_message(self, data: bytes) -> Dict[str, Any]:
        """将字节串解码为消息对象

        Args:
            data: 要解码的字节串

        Returns:
            Dict[str, Any]: 解码后的消息对象

        Raises:
            ValueError: 解码失败时抛出
        """
        pass

    @abstractmethod
    def validate_message(self, message: Dict[str, Any]) -> bool:
        """验证消息格式是否有效

        Args:
            message: 要验证的消息对象

        Returns:
            bool: 消息格式是否有效
        """
        pass