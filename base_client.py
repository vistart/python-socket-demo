import asyncio
from abc import abstractmethod
from typing import Optional
from message import EnhancedMessageHandler, Message, MessageType, PresetMessages
from tcp_interfaces import IClient


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
            except Exception:
                pass  # 忽略断开连接时的发送错误

        self.running = False
        self.connected = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                print(f"Error closing connection: {e}")

    async def send_message(self, content: str) -> None:
        """发送消息到服务器"""
        if not self.connected or not self.writer or not self.session_id:
            return

        try:
            message = PresetMessages.user_message(content.encode(), self.session_id)
            await self._send_message_internal(message)
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
            self.writer.write(data)
            await self.writer.drain()
        except Exception as e:
            print(f"Error sending message: {e}")
            raise

    async def send_heartbeat(self, interval: int = 5) -> None:
        """发送心跳包"""
        while self.running and self.connected and self.session_id:
            try:
                message = PresetMessages.heartbeat_ping(self.session_id)
                await self._send_message_internal(message)
                await asyncio.sleep(interval)
            except Exception as e:
                print(f"Error sending heartbeat: {e}")
                self.running = False
                break

    async def receive_messages(self) -> None:
        """接收并处理服务器消息"""
        while self.running and self.connected and self.reader:
            try:
                data = await self.reader.read(1024)
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
        if message.type == MessageType.MESSAGE:
            print(f"Received: {message.content}")
        elif message.type == MessageType.ERROR:
            print(f"Error from server: {message.content}")
            self.running = False
        elif message.type == MessageType.DISCONNECT:
            print("Server requested disconnect")
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
            if init_message.type != MessageType.SESSION_INIT:
                print("Invalid session initialization from server")
                return False

            self.session_id = init_message.session_id
            if not self.session_id:
                print("No session ID received from server")
                return False

            # 发送确认消息
            ack_message = PresetMessages.session_ack(self.session_id)
            await self._send_message_internal(ack_message)

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