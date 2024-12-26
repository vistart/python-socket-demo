import asyncio
import time
import uuid
from typing import Dict

from message import JSONMessageHandler
from tcp_interfaces import IServer, ISession


class Session(ISession):
    """TCP会话实现类"""

    def __init__(self, session_id: str, writer: asyncio.StreamWriter,
                 client_address: str):
        self._session_id = session_id
        self._writer = writer
        self._client_address = client_address
        self._last_heartbeat = time.time()
        self._connected = True

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_heartbeat(self) -> float:
        return self._last_heartbeat

    @property
    def writer(self) -> asyncio.StreamWriter:
        return self._writer

    def update_heartbeat(self) -> None:
        self._last_heartbeat = time.time()

    async def close(self) -> None:
        self._connected = False
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception as e:
            print(f"Error closing session {self.session_id}: {e}")

    def __str__(self):
        return f"Session({self._session_id[:8]}..., {self._client_address})"


class AsyncTCPServer(IServer):
    """异步TCP服务器实现类"""

    def __init__(self, host: str = 'localhost', port: int = 9999):
        self.host = host
        self.port = port
        self.sessions: Dict[str, ISession] = {}
        self.running = True
        self.message_handler = JSONMessageHandler()

    async def start(self) -> None:
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )

        print(f"Server started on {self.host}:{self.port}")

        try:
            # 启动心跳检查
            heartbeat_task = asyncio.create_task(self.check_sessions())
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            print("Server shutdown initiated")
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.running = False
        for session_id in list(self.sessions.keys()):
            await self.remove_session(session_id)
        print("Server stopped")

    async def handle_client(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter
    ) -> None:
        """处理新的客户端连接,包含会话建立过程"""
        addr = writer.get_extra_info('peername')
        client_address = f"{addr[0]}:{addr[1]}"
        session_id = str(uuid.uuid4())
        session = Session(session_id, writer, client_address)

        # 发送会话建立消息
        try:
            handshake_message = {
                'type': 'session_init',
                'content': 'Session established',
                'session_id': session_id
            }
            data = self.message_handler.encode_message(handshake_message)
            writer.write(data)
            await writer.drain()

            # 等待客户端确认
            client_response = await reader.read(1024)
            if not client_response:
                print(f"Client {client_address} disconnected during handshake")
                return

            response = self.message_handler.decode_message(client_response)
            if (not self.message_handler.validate_message(response) or
                    response.get('type') != 'session_ack' or
                    response.get('session_id') != session_id):
                print(f"Invalid session acknowledgment from {client_address}")
                return

            # 握手成功,保存会话
            self.sessions[session_id] = session
            print(f"New connection established: {session}")

            # 开始正常的消息处理循环
            while self.running and session.is_connected:
                data = await reader.read(1024)
                if not data:
                    break

                try:
                    message = self.message_handler.decode_message(data)
                    if not self.message_handler.validate_message(message):
                        print(f"Invalid message format from {session}")
                        continue

                    # 验证消息中的会话ID
                    if message.get('session_id') != session_id:
                        print(f"Invalid session ID from {session}")
                        break

                    await self.process_message(session, message)

                except ValueError as e:
                    print(f"Error processing message from {session}: {e}")

        except Exception as e:
            print(f"Error handling client {client_address}: {e}")
        finally:
            if session_id in self.sessions:
                await self.remove_session(session_id)

    async def process_message(
            self,
            session: ISession,
            message: dict
    ) -> None:
        msg_type = message.get('type')
        content = message.get('content')

        if msg_type == 'heartbeat':
            session.update_heartbeat()
            print(f"New heartbeat message from {session}")
            response = {'type': 'heartbeat', 'content': 'pong'}
            await self.send_message(session, response)

        elif msg_type == 'message':
            print(f"Received from {session}: {content}")
            response = {
                'type': 'message',
                'content': f'Server received: {content}',
                'session_id': session.session_id
            }
            await self.send_message(session, response)

    async def send_message(
            self,
            session: ISession,
            message: dict
    ) -> None:
        if session.is_connected:
            try:
                data = self.message_handler.encode_message(message)
                session.writer.write(data)  # 这里需要访问内部writer
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
                if (current_time - session.last_heartbeat
                        > timeout * max_retries):  # 访问内部状态
                    print(f"Session {session} heartbeat timeout")
                    await self.remove_session(session_id)

    async def remove_session(self, session_id: str):
        """移除会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.close()
            del self.sessions[session_id]
            print(f"Session {session} closed")


async def main():
    server = AsyncTCPServer()
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


if __name__ == '__main__':
    asyncio.run(main())