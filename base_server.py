import asyncio
import time
import uuid
from abc import abstractmethod
from typing import Dict, Optional, Type

from message import EnhancedMessageHandler, Message, MessageType, PresetMessages
from session import BaseSession
from tcp_interfaces import IServer, ISession


class BaseServer(IServer):
    """服务器基类"""

    @abstractmethod
    async def start(self) -> None:
        pass

    def __init__(self, session_cls: Type[BaseSession]):
        self.sessions: Dict[str, ISession] = {}
        self.running = True
        self.message_handler = EnhancedMessageHandler()
        self.session_cls = session_cls

    async def stop(self) -> None:
        """停止服务器并清理所有资源"""
        self.running = False
        for session_id in list(self.sessions.keys()):
            await self.remove_session(session_id)
        await self._cleanup()
        print("Server stopped")

    async def _cleanup(self) -> None:
        """子类特定的清理操作"""
        pass

    async def handle_client(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter
    ) -> None:
        """处理新的客户端连接"""
        session = await self._create_session(writer)
        if not session:
            return

        try:
            # 发送会话建立消息
            init_message = PresetMessages.session_init(session.session_id)
            await self.send_message(session, init_message)

            # 等待客户端确认
            client_response = await reader.read(1024)
            if not client_response:
                print(f"Client disconnected during handshake")
                return

            try:
                response = self.message_handler.decode_message(client_response)
                if (response.type != MessageType.SESSION_ACK.value or
                        response.session_id != session.session_id):
                    print(f"Invalid session acknowledgment")
                    return
            except ValueError as e:
                print(f"Invalid handshake response: {e}")
                return

            # 握手成功,保存会话
            self.sessions[session.session_id] = session
            print(f"New connection established: {session}")

            # 开始正常的消息处理循环
            while self.running and session.is_connected:
                data = await reader.read(1024)
                if not data:
                    break

                try:
                    message = self.message_handler.decode_message(data)
                    if message.session_id != session.session_id:
                        print(f"Invalid session ID from {session}")
                        break

                    await self.process_message(session, message)

                except ValueError as e:
                    print(f"Error processing message from {session}: {e}")

        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            if session.session_id in self.sessions:
                await self.remove_session(session.session_id)

    async def _create_session(
            self,
            writer: asyncio.StreamWriter
    ) -> Optional[BaseSession]:
        """创建新的会话"""
        session_id = str(uuid.uuid4())
        return self.session_cls(session_id, writer)

    async def process_message(
            self,
            session: ISession,
            message: Message
    ) -> None:
        """处理收到的消息"""
        if message.type == MessageType.HEARTBEAT.value:
            session.update_heartbeat()
            response = PresetMessages.heartbeat_pong(session.session_id)
            await self.send_message(session, response)

        elif message.type == MessageType.MESSAGE.value:
            print(f"Received from {session}: {message.content}")
            response = PresetMessages.user_message(
                # f"Server received: {message.content}".encode(),
                message.content,  # 原样返回。
                session.session_id
            )
            await self.send_message(session, response)

        elif message.type == MessageType.DISCONNECT.value:
            await self.remove_session(session.session_id)

    async def send_message(
            self,
            session: ISession,
            message: Message
    ) -> None:
        """发送消息到指定会话"""
        if session.is_connected:
            try:
                data = self.message_handler.encode_message(message)
                session.writer.write(data)
                await session.writer.drain()
            except Exception as e:
                print(f"Error sending message to {session}: {e}")
                await self.remove_session(session.session_id)

    async def check_sessions(self, timeout: int = 10, max_retries: int = 3):
        """检查所有会话的心跳状态"""
        while self.running:
            await asyncio.sleep(timeout)
            current_time = time.time()

            for session_id, session in list(self.sessions.items()):
                if current_time - session.last_heartbeat > timeout * max_retries:
                    print(f"Session {session} heartbeat timeout")
                    await self.remove_session(session_id)

    async def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.close()
            del self.sessions[session_id]
            print(f"Session {session} closed")