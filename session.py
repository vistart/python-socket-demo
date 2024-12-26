import asyncio
import time

from tcp_interfaces import ISession


class BaseSession(ISession):
    """会话基类"""

    def __init__(self, session_id: str, writer: asyncio.StreamWriter):
        self._session_id = session_id
        self._writer = writer
        self._last_heartbeat = time.time()
        self._connected = True
        self._extra_info = {}  # 用于存储子类特定的额外信息

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

    @property
    def extra_info(self) -> dict:
        return self._extra_info

    def update_heartbeat(self) -> None:
        self._last_heartbeat = time.time()

    async def close(self) -> None:
        self._connected = False
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception as e:
            print(f"Error closing session {self.session_id}: {e}")

    def add_extra_info(self, key: str, value: any) -> None:
        """添加额外的会话信息"""
        self._extra_info[key] = value

    def get_extra_info(self, key: str, default: any = None) -> any:
        """获取额外的会话信息"""
        return self._extra_info.get(key, default)

    def __str__(self):
        """默认的字符串表示"""
        return f"Session({self._session_id[:8]}...)"