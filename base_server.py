import asyncio
import struct
import time
import uuid
from abc import abstractmethod
from typing import Dict, Optional, Type

from message import EnhancedMessageHandler, Message, MessageType, PresetMessages, MessageEnvelope
from session import BaseSession
from interfaces import IServer, ISession


class BaseServer(IServer):
    """服务器基类"""
    def __init__(self, session_cls: Type[BaseSession]):
        self.sessions: Dict[str, ISession] = {}
        self.running = True
        self.message_handler = EnhancedMessageHandler()
        self.session_cls = session_cls
        self._server: Optional[asyncio.AbstractServer] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    @abstractmethod
    async def start(self) -> None:
        """完整的服务器启动流程"""
        await self.start_server()
        self._heartbeat_task = asyncio.create_task(self.check_sessions())

    async def stop(self) -> None:
        """停止服务器并清理所有资源"""
        self.running = False

        # 停止心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # 停止服务器监听
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # 清理所有会话
        for session_id in list(self.sessions.keys()):
            await self.remove_session(session_id)

        await self._cleanup()
        print("Server stopped")

    @abstractmethod
    async def start_server(self) -> None:
        """启动服务器基础设施

        子类必须实现此方法以启动具体的服务器类型
        """
        pass

    async def _cleanup(self) -> None:
        """子类特定的清理操作"""
        pass

    async def _read_exactly(self, reader: asyncio.StreamReader, n: int,
                            chunk_size: int = 65536,
                            max_retries: int = 3) -> Optional[bytes]:
        """准确读取指定字节数的数据，支持重试和连接状态检查"""
        if n <= 0:
            return b''

        data = bytearray()
        remaining = n
        retries = 0

        try:
            while remaining > 0 and retries < max_retries:
                try:
                    current_chunk_size = min(remaining, chunk_size)
                    chunk = await reader.read(current_chunk_size)

                    if not chunk:  # EOF
                        if retries < max_retries - 1:
                            print(f"No data received, retrying... ({retries + 1}/{max_retries})")
                            retries += 1
                            await asyncio.sleep(0.1 * (retries + 1))  # 指数退避
                            continue
                        else:
                            print("Max retries reached, connection might be closed")
                            return None

                    data.extend(chunk)
                    remaining -= len(chunk)
                    retries = 0  # 成功读取后重置重试计数

                except (ConnectionError, asyncio.CancelledError) as e:
                    print(f"Connection error while reading: {e}")
                    return None

                except Exception as e:
                    if retries < max_retries - 1:
                        print(f"Error while reading chunk, retrying... ({retries + 1}/{max_retries}): {e}")
                        retries += 1
                        await asyncio.sleep(0.1 * (retries + 1))
                    else:
                        print(f"Max retries reached: {e}")
                        return None

            return bytes(data) if len(data) == n else None

        except Exception as e:
            print(f"Error in _read_exactly: {e}")
            return None

    async def _read_complete_message(self, reader: asyncio.StreamReader) -> Optional[bytes]:
        """读取完整的消息,采用按需读取策略

        Args:
            reader: StreamReader对象

        Returns:
            Optional[bytes]: 完整的消息数据,如果出错则返回None
        """
        try:
            # 1. 先读取固定大小的头部(先读一个缓冲区)
            initial_data = await reader.read(1024)
            if len(initial_data) < MessageEnvelope.HEADER_SIZE:
                print("Incomplete header received")
                return None

            # 2. 从initial_data中解析头部信息
            header_data = initial_data[:MessageEnvelope.HEADER_SIZE]
            (magic, version, msg_type, header_len, header_crc,
             content_len, content_crc, hmac_digest) = struct.unpack(
                MessageEnvelope.HEADER_FORMAT,
                header_data
            )

            # 3. 验证魔数
            if magic != MessageEnvelope.MAGIC:
                print(f"Invalid magic number")
                return None

            # 4. 计算需要读取的总长度
            total_needed = MessageEnvelope.HEADER_SIZE + header_len + content_len
            data = bytearray(initial_data)

            # 5. 如果initial_data不足,继续读取剩余数据
            remaining = total_needed - len(initial_data)
            while remaining > 0:
                chunk = await reader.read(min(remaining, 1024))
                print(f"remaining: {remaining}")
                if not chunk:  # EOF
                    return None
                data.extend(chunk)
                remaining = total_needed - len(data)

            return bytes(data)

        except asyncio.IncompleteReadError:
            print("Connection closed while reading")
            return None
        except Exception as e:
            print(f"Error in _read_complete_message: {e}")
            return None

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
            client_response = await self._read_complete_message(reader)
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
                try:
                    data = await self._read_complete_message(reader)
                    if not data:
                        break

                    message = self.message_handler.decode_message(data)
                    if message.session_id != session.session_id:
                        print(f"Invalid session ID from {session}")
                        break

                    await self.process_message(session, message)

                except ValueError as e:
                    print(f"Error processing message from {session}: {e}")
                except Exception as e:
                    print(f"Error in message loop: {e}")
                    break

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

    async def process_message(self, session: ISession, message: Message) -> None:
        """处理收到的消息"""
        if message.type == MessageType.HEARTBEAT.value:
            session.update_heartbeat()
            response = PresetMessages.heartbeat_pong(session.session_id)
            await self.send_message(session, response)

        elif message.type == MessageType.MESSAGE.value:
            print(f"Received from {session}: {message.content}")
            response = PresetMessages.user_message(
                message.content,  # 原样返回
                session.session_id
            )
            await self.send_message(session, response)

            # 更新处理消息计数
            current_count = session.get_extra_info('processed_messages', 0)
            session.add_extra_info('processed_messages', current_count + 1)

        elif message.type == MessageType.DISCONNECT.value:
            await self.remove_session(session.session_id)

    async def _send_complete_message(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        """分块发送完整消息

        Args:
            writer: StreamWriter对象
            data: 要发送的完整消息数据
        """
        CHUNK_SIZE = 8192  # 8KB chunks

        # 分块发送
        for i in range(0, len(data), CHUNK_SIZE):
            chunk = data[i:i + CHUNK_SIZE]
            writer.write(chunk)
            try:
                await writer.drain()  # 等待数据发送完成
            except ConnectionError as e:
                print(f"Connection error while sending: {e}")
                raise
            except Exception as e:
                print(f"Error sending message chunk: {e}")
                raise

    async def send_message(self, session: ISession, message: Message) -> None:
        """发送消息到指定会话"""
        if session.is_connected:
            try:
                data = self.message_handler.encode_message(message)
                await self._send_complete_message(session.writer, data)
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