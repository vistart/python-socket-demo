import hashlib
import hmac
import json
import struct
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

# 在 MessageType 中添加新的消息类型
class MessageType(Enum):
    """消息类型枚举"""
    SESSION_INIT = "session_init"
    SESSION_ACK = "session_ack"
    HEARTBEAT = "heartbeat"
    MESSAGE = "message"
    CHUNK = "chunk"  # 新增的分片消息类型
    ERROR = "error"
    DISCONNECT = "disconnect"


@dataclass
class Message:
    """预定义消息结构"""
    type: str
    content: bytes
    session_id: Optional[str] = None
    content_type: Optional[str] = "application/octet-stream"

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "type": MessageType(self.type),
            "content": self.content,
            "session_id": self.session_id,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Message':
        """从字典创建消息对象"""
        try:
            msg_type = MessageType(data.get("type")).value
            content = data.get("content")
            session_id = data.get("session_id")
            content_type = data.get("content_type", "application/octet-stream")
            return cls(msg_type, content, session_id, content_type)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid message format: {e}")

    def validate(self) -> bool:
        return self.content and isinstance(self.content, bytes) and len(self.content) > 0 and self.content_type


class IMessageHandler(ABC):
    """消息处理器接口,定义消息的编码解码和验证"""

    @abstractmethod
    def encode_message(self, message: Message) -> bytes:
        """将消息对象编码为字节串

        Args:
            message: 要编码的消息对象

        Returns:
            bytes: 编码后的字节串
        """
        pass

    @abstractmethod
    def decode_message(self, data: bytes) -> Message:
        """将字节串解码为消息对象

        Args:
            data: 要解码的字节串

        Returns:
            Message: 解码后的消息对象

        Raises:
            ValueError: 解码失败时抛出
        """
        pass

    @abstractmethod
    def validate_message(self, message: Message) -> bool:
        """验证消息格式是否有效

        Args:
            message: 要验证的消息对象

        Returns:
            bool: 消息格式是否有效
        """
        pass


class PresetMessages:
    """预设消息工厂"""

    @staticmethod
    def session_init(session_id: str) -> Message:
        return Message(
            MessageType.SESSION_INIT.value,
            "Session established".encode(),
            session_id
        )

    @staticmethod
    def session_ack(session_id: str) -> Message:
        return Message(
            MessageType.SESSION_ACK.value,
            "Session acknowledged".encode(),
            session_id
        )

    @staticmethod
    def heartbeat_ping(session_id: str) -> Message:
        return Message(
            MessageType.HEARTBEAT.value,
            "ping".encode(),
            session_id
        )

    @staticmethod
    def heartbeat_pong(session_id: str) -> Message:
        return Message(
            MessageType.HEARTBEAT.value,
            "pong".encode(),
            session_id
        )

    @staticmethod
    def error(content: str, session_id: Optional[str] = None) -> Message:
        return Message(
            MessageType.ERROR.value,
            content.encode(),
            session_id
        )

    @staticmethod
    def disconnect(session_id: str) -> Message:
        return Message(
            MessageType.DISCONNECT.value,
            "Client disconnecting".encode(),
            session_id
        )

    @staticmethod
    def user_message(content: bytes, session_id: str, content_type: Optional[str] = 'text/plain') -> Message:
        return Message(
            MessageType.MESSAGE.value,
            content,
            session_id,
            content_type
        )


@dataclass
class MessageEnvelope:
    """消息封装，处理消息的打包和解包"""
    # 添加常量配置
    MAX_HEADER_SIZE = 1024 * 64  # 64KB
    MAX_CONTENT_SIZE = 1024 * 1024 * 10  # 10MB
    CHUNK_SIZE = 8192  # 8KB for streaming

    # 使用更复杂的魔数序列，减少冲突可能性
    MAGIC = bytes.fromhex('89 50 4E 47 0E 0B 1B 0B')  # 有别于PNG文件的魔数
    VERSION = 1  # 协议版本号

    # 消息类型常量
    TYPE_NORMAL = 0  # 普通消息

    # 头部格式:
    # - 8字节魔数
    # - 2字节版本号
    # - 2字节消息类型
    # - 4字节头部长度
    # - 4字节头部CRC32
    # - 8字节内容长度
    # - 4字节内容CRC32
    # - 32字节HMAC-SHA256
    HEADER_FORMAT = '!8sHHIIQI32s'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    msg_type: MessageType = MessageType.SESSION_INIT
    content: bytes = b""
    session_id: Optional[str] = None
    content_type: Optional[str] = "application/octet-stream"

    def __init__(self, message: Message, hmac_key: bytes):
        """初始化消息封装

        Args:
            message: 消息
            hmac_key: HMAC密钥
        """
        if not message.validate():
            raise ValueError(f"Invalid message format: {message}")
        self.msg_type = MessageType(message.type)
        self.content = message.content
        self.content_type = message.content_type
        self.session_id = message.session_id
        self._hmac_key = hmac_key
        self._header = {
            'type': message.type,
            'content_type': message.content_type,
            'session_id': message.session_id
        }

    @property
    def header_json(self) -> bytes:
        """获取JSON格式的头部数据"""
        return json.dumps(self._header).encode('utf-8')

    @classmethod
    def validate_sizes(cls, header_len: int, content_len: int) -> None:
        """验证消息大小是否在允许范围内"""
        if header_len > cls.MAX_HEADER_SIZE:
            raise ValueError(f"Header too large: {header_len} bytes")
        if content_len > cls.MAX_CONTENT_SIZE:
            raise ValueError(f"Content too large: {content_len} bytes")

    def pack(self) -> bytes:
        """将消息打包为字节序列"""
        header_json = self.header_json

        # 验证大小限制
        self.validate_sizes(len(header_json), len(self.content))

        # 计算头部和内容的CRC32
        header_crc = zlib.crc32(header_json)
        content_crc = zlib.crc32(self.content)

        # 计算HMAC
        h = hmac.new(self._hmac_key, digestmod=hashlib.sha256)
        h.update(header_json)
        h.update(self.content)
        hmac_digest = h.digest()

        # 打包头部
        header = struct.pack(
            self.HEADER_FORMAT,
            self.MAGIC,
            self.VERSION,
            self.TYPE_NORMAL,
            len(header_json),
            header_crc,
            len(self.content),
            content_crc,
            hmac_digest
        )

        # 组装完整消息
        return header + header_json + self.content

    @classmethod
    def unpack(cls, data: bytes, hmac_key: bytes) -> 'MessageEnvelope':
        """从字节序列解包消息

        Args:
            data: 要解包的字节序列
            hmac_key: HMAC密钥

        Returns:
            MessageEnvelope: 解包后的消息封装

        Raises:
            ValueError: 当消息格式无效、校验失败等情况时
        """
        # 检查数据长度
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"Message too short: got {len(data)} bytes, need at least {cls.HEADER_SIZE}")

        # 解析头部
        try:
            header_fields = struct.unpack(
                cls.HEADER_FORMAT,
                data[:cls.HEADER_SIZE]
            )
            (magic, version, msg_type, header_len, header_crc,
             content_len, content_crc, hmac_digest) = header_fields
        except struct.error as e:
            raise ValueError(f"Failed to unpack header: {e}")

        # print(f"Message size: {len(data)}, header_fields: {header_fields}")

        # 验证魔数
        if magic != cls.MAGIC:
            raise ValueError(f"Invalid magic number: expected {cls.MAGIC.hex()}, got {magic.hex()}")

        # 验证版本号
        if version != cls.VERSION:
            raise ValueError(f"Unsupported version: {version}")

        # 验证总长度
        total_expected_length = cls.HEADER_SIZE + header_len + content_len
        if len(data) != total_expected_length:
            raise ValueError(
                f"Data length mismatch: got {len(data)}, "
                f"expected {total_expected_length} "
                f"(header:{cls.HEADER_SIZE} + header_len:{header_len} + content_len:{content_len})"
            )

        # 提取header和content
        header_start = cls.HEADER_SIZE
        header_end = header_start + header_len
        content_end = header_end + content_len

        try:
            header_json = data[header_start:header_end]
            content = data[header_end:content_end]
        except Exception as e:
            raise ValueError(f"Failed to extract header/content: {e}")

        # 验证头部CRC32
        calculated_header_crc = zlib.crc32(header_json)
        if calculated_header_crc != header_crc:
            raise ValueError(
                f"Header CRC mismatch: calculated {calculated_header_crc}, "
                f"expected {header_crc}"
            )

        # 验证内容CRC32
        calculated_content_crc = zlib.crc32(content)
        if calculated_content_crc != content_crc:
            raise ValueError(
                f"Content CRC mismatch: calculated {calculated_content_crc}, "
                f"expected {content_crc}"
            )

        # 验证HMAC
        try:
            h = hmac.new(hmac_key, digestmod=hashlib.sha256)
            h.update(header_json)
            h.update(content)
            calculated_hmac = h.digest()
            if not hmac.compare_digest(calculated_hmac, hmac_digest):
                raise ValueError("HMAC verification failed")
        except Exception as e:
            raise ValueError(f"HMAC calculation failed: {e}")

        # 解析header JSON
        try:
            header = json.loads(header_json.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid header JSON: {e}")

        try:
            return cls(
                Message(
                    header.get('type'),
                    content,
                    header.get('session_id'),
                    header.get('content_type')
                ),
                hmac_key
            )
        except Exception as e:
            raise ValueError(f"Failed to create message: {e}")

    def to_message(self) -> Message:
        return Message(self.msg_type.value, self.content, self.session_id, self.content_type)


class EnhancedMessageHandler(IMessageHandler):
    """增强的消息处理器，支持二进制内容"""

    def __init__(self, hmac_key: bytes = b'default-key'):
        """初始化处理器

        Args:
            hmac_key: 用于消息认证的密钥
        """
        self._hmac_key = hmac_key

    def validate_message(self, message: Message) -> bool:
        """验证消息格式是否有效

        Args:
            message: 要验证的消息对象

        Returns:
            bool: 消息格式是否有效
        """
        return message and message.validate()

    def encode_message(self, message: Message) -> bytes:
        """将消息对象编码为字节串

        Args:
            message: 要编码的消息对象

        Returns:
            bytes: 编码后的字节串

        Raises:
            ValueError: 当消息格式无效时抛出
        """
        envelope = MessageEnvelope(message, self._hmac_key)
        return envelope.pack()

    def decode_message(self, data: bytes) -> Message:
        """将字节串解码为消息对象

        Args:
            data: 要解码的字节串

        Returns:
            Dict[str, Any]: 解码后的消息对象

        Raises:
            ValueError: 解码失败时抛出
        """
        return MessageEnvelope.unpack(data, self._hmac_key).to_message()


def test_message_handler():
    # 初始化消息处理器
    handler = EnhancedMessageHandler(hmac_key=b'test-key-12345')

    # 1. 处理文本消息
    print("\n=== 测试文本消息 ===")
    text_message = Message.from_dict({
        'type': MessageType.MESSAGE,
        'content': 'Hello, World!'.encode(),
        'content_type': 'text/plain'
    })

    # 验证消息格式
    print(f"验证文本消息格式: {handler.validate_message(text_message)}")

    # 编码消息
    encoded_text = handler.encode_message(text_message)
    print(f"编码后的消息长度: {len(encoded_text)} 字节")

    # 解码消息
    decoded_text = handler.decode_message(encoded_text)
    print(f"解码后的消息: {decoded_text}")

    # 2. 处理二进制消息
    print("\n=== 测试二进制消息 ===")
    binary_message = Message.from_dict({
        'type': MessageType.MESSAGE,
        'content': bytes([0xFF, 0xD8, 0xFF, 0xE0] + [0] * 12),  # 模拟 JPEG 头部
        'content_type': 'image/jpeg'
    })

    # 验证消息格式
    print(f"验证二进制消息格式: {handler.validate_message(binary_message)}")

    # 编码消息
    encoded_binary = handler.encode_message(binary_message)
    print(f"编码后的消息长度: {len(encoded_binary)} 字节")

    # 解码消息
    decoded_binary = handler.decode_message(encoded_binary)
    print(f"解码后的消息类型: {decoded_binary.content_type}")
    print(f"解码后的内容长度: {len(decoded_binary.content)} 字节")

    # 3. 错误处理示例
    print("\n=== 测试错误处理 ===")

    # 3.1 无效的消息格式
    try:
        invalid_message = Message.from_dict({
            'type': MessageType.MESSAGE,
            # 缺少必需的 content 字段
            'content_type': 'text/plain'
        })
        handler.encode_message(invalid_message)
    except ValueError as e:
        print(f"预期的格式错误被捕获: {e}")

    # 3.2 无效的消息内容类型
    try:
        invalid_type_message = Message.from_dict({
            'type': MessageType.MESSAGE,
            'content': 123,  # 数字不是有效的内容类型
            'content_type': 'text/plain'
        })
        handler.encode_message(invalid_type_message)
    except ValueError as e:
        print(f"预期的类型错误被捕获: {e}")

    # 3.3 无效的消息数据
    try:
        handler.decode_message(b'invalid data')
    except ValueError as e:
        print(f"预期的解码错误被捕获: {e}")

    # 3.4 尝试篡改的消息
    try:
        # 获取有效消息然后修改一些字节
        valid_encoded = handler.encode_message(text_message)
        tampered_message = bytearray(valid_encoded)
        tampered_message[-1] ^= 0xFF  # 修改最后一个字节
        handler.decode_message(bytes(tampered_message))
    except ValueError as e:
        print(f"预期的消息完整性错误被捕获: {e}")


if __name__ == '__main__':
    test_message_handler()