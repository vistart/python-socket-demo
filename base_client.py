import asyncio
from typing import Optional
from message import JSONMessageHandler
from tcp_interfaces import IClient


class BaseAsyncClient(IClient):
    """异步客户端基类"""

    def __init__(self):
        self.running = False
        self.connected = False
        self.session_id: Optional[str] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_handler = JSONMessageHandler()

    async def disconnect(self) -> None:
        """断开连接并清理资源"""
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
            message = {
                'type': 'message',
                'content': content,
                'session_id': self.session_id
            }
            data = self.message_handler.encode_message(message)
            self.writer.write(data)
            await self.writer.drain()
            print(f"Sent: {content}")
        except Exception as e:
            print(f"Error sending message: {e}")
            self.running = False

    async def send_heartbeat(self, interval: int = 5) -> None:
        """发送心跳包"""
        while self.running and self.connected and self.session_id:
            try:
                message = {
                    'type': 'heartbeat',
                    'content': 'ping',
                    'session_id': self.session_id
                }
                data = self.message_handler.encode_message(message)
                self.writer.write(data)
                await self.writer.drain()
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
                if not self.message_handler.validate_message(message):
                    print("Invalid message format")
                    continue

                msg_type = message.get('type')
                content = message.get('content')

                if msg_type == 'message':
                    print(f"Received: {content}")

            except ValueError as e:
                print(f"Error decoding message: {e}")
            except Exception as e:
                print(f"Error receiving message: {e}")
                break

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
            if (not self.message_handler.validate_message(init_message) or
                    init_message.get('type') != 'session_init'):
                print("Invalid session initialization from server")
                return False

            self.session_id = init_message.get('session_id')
            if not self.session_id:
                print("No session ID received from server")
                return False

            # 发送确认消息
            ack_message = {
                'type': 'session_ack',
                'content': 'Session acknowledged',
                'session_id': self.session_id
            }
            ack_data = self.message_handler.encode_message(ack_message)
            self.writer.write(ack_data)
            await self.writer.drain()

            return True
        except Exception as e:
            print(f"Error in handshake: {e}")
            return False