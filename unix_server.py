import asyncio
import os

from base_server import BaseServer
from session import BaseSession


class UnixSession(BaseSession):
    """Unix套接字会话实现类"""

    def __init__(self, session_id: str, writer: asyncio.StreamWriter):
        super().__init__(session_id, writer)

    def __str__(self):
        return f"UnixSession({self._session_id[:8]}...)"


class AsyncUnixServer(BaseServer):
    """Unix套接字服务器实现类"""

    def __init__(self, socket_path: str = '/tmp/chat.sock'):
        super().__init__(UnixSession)
        self._socket_path = socket_path

    async def start(self) -> None:
        """完整的服务器启动流程"""
        await super().start()
        if self._server:
            async with self._server:
                await self._server.serve_forever()

    async def start_server(self) -> None:
        """启动Unix套接字文件"""
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        self._server = await asyncio.start_unix_server(
            self.handle_client,
            path=self.socket_path
        )
        print(f"Unix socket server started at {self.socket_path}")

    async def _cleanup(self) -> None:
        """清理Unix套接字文件"""
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


async def run_unix_server(socket_path: str = '/tmp/chat.sock'):
    server = AsyncUnixServer(socket_path)
    try:
        await server.start()
    except KeyboardInterrupt:
        await server.stop()


if __name__ == '__main__':
    import sys

    socket_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/chat.sock'
    asyncio.run(run_unix_server(socket_path))