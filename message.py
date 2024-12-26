import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Union


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


class MessageType(Enum):
    """消息类型枚举"""
    SESSION_INIT = "session_init"
    SESSION_ACK = "session_ack"
    HEARTBEAT = "heartbeat"
    MESSAGE = "message"
    ERROR = "error"
    DISCONNECT = "disconnect"


@dataclass
class Message:
    """预定义消息结构"""
    type: MessageType
    content: str
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "type": self.type.value,
            "content": self.content,
            "session_id": self.session_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Message':
        """从字典创建消息对象"""
        try:
            msg_type = MessageType(data.get("type"))
            content = data.get("content", "")
            session_id = data.get("session_id")
            return cls(msg_type, content, session_id)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid message format: {e}")


class PresetMessages:
    """预设消息工厂"""

    @staticmethod
    def session_init(session_id: str) -> Message:
        return Message(
            MessageType.SESSION_INIT,
            "Session established",
            session_id
        )

    @staticmethod
    def session_ack(session_id: str) -> Message:
        return Message(
            MessageType.SESSION_ACK,
            "Session acknowledged",
            session_id
        )

    @staticmethod
    def heartbeat_ping(session_id: str) -> Message:
        return Message(
            MessageType.HEARTBEAT,
            "ping",
            session_id
        )

    @staticmethod
    def heartbeat_pong(session_id: str) -> Message:
        return Message(
            MessageType.HEARTBEAT,
            "pong",
            session_id
        )

    @staticmethod
    def error(content: str, session_id: Optional[str] = None) -> Message:
        return Message(
            MessageType.ERROR,
            content,
            session_id
        )

    @staticmethod
    def disconnect(session_id: str) -> Message:
        return Message(
            MessageType.DISCONNECT,
            "Client disconnecting",
            session_id
        )

    @staticmethod
    def user_message(content: str, session_id: str) -> Message:
        return Message(
            MessageType.MESSAGE,
            content,
            session_id
        )


class JSONMessageHandler(IMessageHandler):
    """JSON格式消息处理器"""

    def encode_message(self, message: Union[dict, Message]) -> bytes:
        """编码消息为字节串

        Args:
            message: 消息对象或字典

        Returns:
            bytes: 编码后的字节串
        """
        if isinstance(message, Message):
            message = message.to_dict()
        return json.dumps(message).encode('utf-8')

    def decode_message(self, data: bytes) -> Message:
        """解码字节串为消息对象

        Args:
            data: 要解码的字节串

        Returns:
            Message: 解码后的消息对象

        Raises:
            ValueError: 解码失败时抛出
        """
        try:
            message_dict = json.loads(data.decode('utf-8'))
            return Message.from_dict(message_dict)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")
        except Exception as e:
            raise ValueError(f"Failed to decode message: {e}")

    def validate_message(self, message: Union[dict, Message]) -> bool:
        """验证消息格式是否有效

        Args:
            message: 要验证的消息对象或字典

        Returns:
            bool: 消息格式是否有效
        """
        try:
            if isinstance(message, dict):
                message = Message.from_dict(message)
            return (isinstance(message, Message) and
                    message.type in MessageType and
                    isinstance(message.content, str))
        except Exception:
            return False

