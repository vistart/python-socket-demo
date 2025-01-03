import asyncio
import json
import struct
from abc import abstractmethod
from typing import Optional
from message import EnhancedMessageHandler, Message, MessageType, PresetMessages, MessageEnvelope
from interfaces import IClient


class BaseAsyncClient(IClient):
    """异步客户端基类"""

    @abstractmethod
    async def connect(self) -> bool:
        pass

    def __init__(self):
        self.running = False
        self.connected = False
        self.session_id: Optional[str] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_handler = EnhancedMessageHandler()

    async def disconnect(self) -> None:
        """断开连接并清理资源"""
        if self.connected and self.session_id:
            try:
                # 发送断开连接消息
                disconnect_msg = PresetMessages.disconnect(self.session_id)
                await self._send_message_internal(disconnect_msg)
                # 等待服务器处理断开连接的消息
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error sending disconnect message: {e}")

        self.running = False
        self.connected = False
        self.session_id = None  # 确保清理会话ID

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                print(f"Error closing connection: {e}")
            finally:
                self.writer = None  # 确保清理writer
                self.reader = None  # 确保清理reader

    async def send_message(self, content: str) -> None:
        """发送消息到服务器"""
        if not self.connected or not self.writer or not self.session_id:
            return

        try:
            # 确保字符串被正确编码为bytes
            message = PresetMessages.user_message(
                content.encode('utf-8'),
                self.session_id,
                'text/plain; charset=utf-8'
            )
            await self._send_message_internal(message)
            await self.writer.drain()  # 确保数据被完全发送
            print(f"Sent: {content}")
        except Exception as e:
            print(f"Error sending message: {e}")
            self.running = False

    async def _send_message_internal(self, message: Message) -> None:
        """内部消息发送方法"""
        if message.type != MessageType.SESSION_ACK.value and not self.connected or not self.writer:
            return

        try:
            data = self.message_handler.encode_message(message)
            CHUNK_SIZE = 8192  # 8KB chunks

            # 首先发送完整的消息头
            header_size = MessageEnvelope.HEADER_SIZE
            self.writer.write(data[:header_size])
            await self.writer.drain()

            # 然后分块发送剩余数据
            remaining_data = data[header_size:]
            for i in range(0, len(remaining_data), CHUNK_SIZE):
                chunk = remaining_data[i:i + CHUNK_SIZE]
                self.writer.write(chunk)
                await self.writer.drain()

        except Exception as e:
            print(f"Error sending message: {e}")
            raise

    async def _receive_complete_message(self) -> bytes:
        """接收完整的消息,采用按需读取策略

        Returns:
            bytes: 完整的消息数据
        """
        if not self.reader:
            return b''

        try:
            # 1. 先读取一个缓冲区的数据
            initial_data = await self.reader.read(1024)
            if len(initial_data) < MessageEnvelope.HEADER_SIZE:
                print("Incomplete header received")
                return b''

            # 2. 从initial_data中解析头部信息
            header_data = initial_data[:MessageEnvelope.HEADER_SIZE]
            (magic, version, msg_type, header_len, header_crc,
             content_len, content_crc, hmac_digest) = struct.unpack(
                MessageEnvelope.HEADER_FORMAT,
                header_data
            )

            # 3. 验证魔数
            if magic != MessageEnvelope.MAGIC:
                print(f"Invalid magic number in header")
                return b''

            # 4. 计算需要读取的总长度
            total_needed = MessageEnvelope.HEADER_SIZE + header_len + content_len
            data = bytearray(initial_data)

            # 5. 如果initial_data不足,继续读取剩余数据
            remaining = total_needed - len(initial_data)
            while remaining > 0:
                chunk = await self.reader.read(min(remaining, 1024))
                if not chunk:  # EOF
                    return b''
                data.extend(chunk)
                remaining = total_needed - len(data)

            return bytes(data)

        except asyncio.IncompleteReadError:
            print("Connection closed by server")
            return b''
        except Exception as e:
            print(f"Error in _receive_complete_message: {e}")
            return b''

    async def _read_exactly(self, n: int) -> bytes:
        """准确读取指定字节数的数据

        Args:
            n: 需要读取的字节数

        Returns:
            bytes: 读取到的数据

        Raises:
            ValueError: 如果无法读取足够的数据
        """
        if not self.reader:
            return b''

        data = b''
        remaining = n

        while remaining > 0:
            chunk = await self.reader.read(remaining)
            if not chunk:  # EOF
                raise ValueError(f"Connection closed while reading, got {len(data)} bytes, expected {n}")
            data += chunk
            remaining -= len(chunk)

        return data

    async def send_single_heartbeat(self) -> None:
        """发送单次心跳包"""
        if self.connected and self.session_id:
            try:
                message = PresetMessages.heartbeat_ping(self.session_id)
                await self._send_message_internal(message)
            except Exception as e:
                print(f"Error sending heartbeat: {e}")
                self.running = False

    async def send_heartbeat(self, interval: int = 5) -> None:
        """发送心跳包（循环）"""
        while self.running and self.connected and self.session_id:
            try:
                await self.send_single_heartbeat()
                await asyncio.sleep(interval)
            except Exception as e:
                print(f"Error in heartbeat loop: {e}")
                self.running = False
                break

    async def receive_messages(self) -> None:
        """接收并处理服务器消息"""
        while self.running and self.connected and self.reader:
            try:
                data = await self._receive_complete_message()
                if not data:
                    break

                message = self.message_handler.decode_message(data)
                await self._handle_message(message)

            except ValueError as e:
                print(f"Error decoding message: {e}")
            except Exception as e:
                print(f"Error receiving message: {e}")
                break

        self.running = False

    async def _handle_message(self, message: Message) -> None:
        """处理接收到的消息"""
        if message.type == MessageType.MESSAGE.value:
            print(f"Received: {message.content}")
            if message.content_type == 'text/plain' or message.content_type == 'text/plain; charset=utf-8':
                print(f"Decoded: {message.content.decode('utf-8')}")
        elif message.type == MessageType.ERROR.value:
            print(f"Error from server: {message.content}")
            self.running = False
        elif message.type == MessageType.DISCONNECT.value:
            try:
                if message.content_type == 'application/json':
                    disconnect_info = json.loads(message.content.decode('utf-8'))
                    reason = disconnect_info.get('reason', 'No reason provided')
                    print(f"Server requested disconnect: {reason}")
                else:
                    print("Server requested disconnect")
            except json.JSONDecodeError:
                print("Server requested disconnect")
            except Exception as e:
                print(f"Error processing disconnect message: {e}")
            finally:
                self.running = False

    async def _handle_handshake(self, init_data: bytes) -> bool:
        """处理握手过程

        Args:
            init_data: 从服务器接收的初始化数据

        Returns:
            bool: 握手是否成功
        """
        if not init_data:
            print("Connection closed by server during handshake")
            return False

        try:
            init_message = self.message_handler.decode_message(init_data)
            if init_message.type != MessageType.SESSION_INIT.value:
                print("Invalid session initialization from server")
                return False

            self.session_id = init_message.session_id
            if not self.session_id:
                print("No session ID received from server")
                return False

            # 发送确认消息并等待确认完成
            ack_message = PresetMessages.session_ack(self.session_id)
            await self._send_message_internal(ack_message)
            await asyncio.sleep(0.1)  # 给服务器处理确认消息的时间

            return True
        except Exception as e:
            print(f"Error in handshake: {e}")
            return False

    async def _cleanup(self) -> None:
        """子类可以重写此方法以添加额外的清理操作"""
        pass

    async def start(self, message_source: str) -> None:
        """启动客户端并处理消息

        这是一个抽象方法，子类必须实现
        """
        raise NotImplementedError("Subclasses must implement start()")
