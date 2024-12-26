import asyncio
import uuid

from base_server import BaseServer
from session import BaseSession


class TCPSession(BaseSession):
    """TCP会话实现类"""

    def __init__(self, session_id: str, writer: asyncio.StreamWriter, client_address: str):
        super().__init__(session_id, writer)
        self.add_extra_info('client_address', client_address)

    def __str__(self):
        client_address = self.get_extra_info('client_address', 'unknown')
        return f"TCPSession({self._session_id[:8]}..., {client_address})"


class AsyncTCPServer(BaseServer):
    """TCP服务器实现类"""

    def __init__(self, host: str = 'localhost', port: int = 9999):
        super().__init__(TCPSession)
        self.host = host
        self.port = port

    async def start(self) -> None:
        """启动TCP服务器"""
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )

        print(f"TCP server started on {self.host}:{self.port}")

        try:
            heartbeat_task = asyncio.create_task(self.check_sessions())
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            print("Server shutdown initiated")
        finally:
            await self.stop()

    async def _create_session(self, writer: asyncio.StreamWriter) -> TCPSession:
        """创建TCP会话"""
        session_id = str(uuid.uuid4())
        addr = writer.get_extra_info('peername')
        client_address = f"{addr[0]}:{addr[1]}"
        return TCPSession(session_id, writer, client_address)

async def run_tcp_server(host: str = 'localhost', port: int = 9999):
    server = AsyncTCPServer(host, port)
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()

if __name__ == '__main__':
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    asyncio.run(run_tcp_server(host, port))
