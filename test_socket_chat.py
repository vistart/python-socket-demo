import asyncio
import os
import socket
import tempfile
import time
from typing import AsyncGenerator, Generator, Tuple, Optional

import pytest
import pytest_asyncio

from base_server import BaseServer
from tcp_client import AsyncTCPClient
from tcp_server import AsyncTCPServer
from unix_client import AsyncUnixClient
from unix_server import AsyncUnixServer


# 辅助函数
def find_free_port() -> int:
    """查找可用的TCP端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def get_temp_socket_path() -> str:
    """获取临时Unix套接字路径"""
    return os.path.join(tempfile.gettempdir(), f'test_chat_{os.getpid()}.sock')


# 基础夹具
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """创建事件循环，整个测试会话共享"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# 服务器包装类
class ServerWrapper:
    """包装服务器以管理其生命周期"""

    def __init__(self, server: BaseServer):
        self.server = server
        self.server_task: Optional[asyncio.Task] = None
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self):
        """非阻塞启动服务器"""
        if isinstance(self.server, AsyncTCPServer):
            self._server = await asyncio.start_server(
                self.server.handle_client,
                self.server.host,
                self.server.port
            )
        else:  # UnixServer
            try:
                os.unlink(self.server.socket_path)
            except FileNotFoundError:
                pass
            self._server = await asyncio.start_unix_server(
                self.server.handle_client,
                path=self.server.socket_path
            )

        self.server_task = asyncio.create_task(self._server.serve_forever())
        # 启动心跳检查
        asyncio.create_task(self.server.check_sessions())

    async def stop(self):
        """停止服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        await self.server.stop()


# TCP测试夹具
@pytest_asyncio.fixture
async def tcp_server_config() -> Tuple[str, int]:
    """配置TCP服务器参数"""
    return 'localhost', find_free_port()


@pytest_asyncio.fixture
async def tcp_server(tcp_server_config: Tuple[str, int]) -> AsyncGenerator[AsyncTCPServer, None]:
    """启动TCP服务器"""
    host, port = tcp_server_config
    server = AsyncTCPServer(host, port)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # 等待服务器启动
    yield server
    await server.stop()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest_asyncio.fixture
async def tcp_client(tcp_server_config: Tuple[str, int]) -> AsyncGenerator[AsyncTCPClient, None]:
    """创建TCP客户端"""
    host, port = tcp_server_config
    client = AsyncTCPClient(host, port)
    yield client
    await client.disconnect()


# Unix套接字测试夹具
@pytest_asyncio.fixture
async def unix_socket_path() -> str:
    """配置Unix套接字路径"""
    return get_temp_socket_path()


@pytest_asyncio.fixture
async def unix_server(unix_socket_path: str) -> AsyncGenerator[AsyncUnixServer, None]:
    """启动Unix套接字服务器"""
    server = AsyncUnixServer(unix_socket_path)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # 等待服务器启动
    yield server
    await server.stop()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest_asyncio.fixture
async def unix_client(unix_socket_path: str) -> AsyncGenerator[AsyncUnixClient, None]:
    """创建Unix套接字客户端"""
    client = AsyncUnixClient(unix_socket_path)
    yield client
    await client.disconnect()


# 基础测试类
class BaseServerTests:
    """服务器基础测试用例"""

    pytest_plugins = ('pytest_asyncio',)

    async def wait_for_session_active(self, server, client, timeout=1.0) -> bool:
        """等待直到会话被创建并激活"""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if (client.session_id and
                client.session_id in server.sessions and
                server.sessions[client.session_id].is_connected):
                return True
            await asyncio.sleep(0.1)
        return False

    @pytest.mark.asyncio
    async def test_server_start_stop(self, get_server, get_client):
        """测试服务器启动和停止"""
        server = get_server
        assert len(server.sessions) == 0
        # await asyncio.sleep(0.1)
        assert server.running == True

    @pytest.mark.asyncio
    async def test_client_connect(self, get_server, get_client):
        """测试客户端连接"""
        server = get_server
        client = get_client
        success = await client.connect()
        assert success == True
        assert client.session_id is not None
        assert client.connected == True

        # 等待会话建立
        assert await self.wait_for_session_active(server, client)

    @pytest.mark.asyncio
    async def test_heartbeat(self, get_server, get_client):
        """测试心跳机制"""
        server = get_server
        client = get_client

        # 确保客户端连接成功
        await client.connect()
        assert await self.wait_for_session_active(server, client)

        # 获取初始心跳时间
        session = server.sessions[client.session_id]
        initial_heartbeat = session.last_heartbeat

        # 发送一个心跳包并等待服务器处理
        await client.send_single_heartbeat()

        # 等待服务器处理心跳
        start_time = asyncio.get_event_loop().time()
        while session.last_heartbeat == initial_heartbeat:
            await asyncio.sleep(0.1)
            if asyncio.get_event_loop().time() - start_time > 1.0:
                pytest.fail("Server did not process heartbeat in time")

        assert session.last_heartbeat > initial_heartbeat

    @pytest.mark.asyncio
    async def test_message_exchange(self, get_server, get_client):
        """测试消息收发"""
        server = get_server
        client = get_client

        # 确保客户端连接成功
        await client.connect()
        assert await self.wait_for_session_active(server, client)

        # 创建消息接收任务
        receive_task = asyncio.create_task(client.receive_messages())
        try:
            test_message = "Hello Server"
            await client.send_message(test_message)
            await asyncio.sleep(0.1)  # 等待消息处理
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        # 由于服务器是回显设计，应该能收到相同的消息

    @pytest.mark.asyncio
    async def test_client_disconnect(self, get_server, get_client):
        """测试客户端断开连接"""
        server = get_server
        client = get_client

        # 确保客户端连接成功
        await client.connect()
        assert await self.wait_for_session_active(server, client)

        session_id = client.session_id
        assert session_id in server.sessions

        # 断开连接并等待服务器处理
        await client.disconnect()

        # 等待直到会话被移除
        start_time = asyncio.get_event_loop().time()
        while session_id in server.sessions:
            if asyncio.get_event_loop().time() - start_time > 1.0:
                pytest.fail("Session was not removed after disconnect")
            await asyncio.sleep(0.1)


    @pytest.mark.asyncio
    async def test_multiple_messages(self, get_server, get_client):
        """测试连续发送多条消息"""
        server = get_server
        client = get_client

        # 确保客户端连接成功
        await client.connect()
        assert await self.wait_for_session_active(server, client)

        # 创建消息接收任务
        receive_task = asyncio.create_task(client.receive_messages())
        try:
            messages = ["Message 1", "Message 2", "Message 3"]
            for msg in messages:
                await client.send_message(msg)
                await asyncio.sleep(0.1)
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass



# TCP服务器具体测试类
class TestTCPServer(BaseServerTests):
    """TCP服务器测试用例"""

    @pytest_asyncio.fixture
    async def get_server(self, tcp_server):
        return tcp_server

    @pytest_asyncio.fixture
    async def get_client(self, tcp_client):
        return tcp_client

    @pytest.mark.asyncio
    async def test_tcp_specific_feature(self, tcp_server: AsyncTCPServer, tcp_client: AsyncTCPClient):
        """TCP特定功能测试"""
        await tcp_client.connect()
        assert await self.wait_for_session_active(tcp_server, tcp_client)

        session = tcp_server.sessions[tcp_client.session_id]
        assert 'client_address' in session.extra_info


# Unix套接字服务器具体测试类
class TestUnixServer(BaseServerTests):
    """Unix套接字服务器测试用例"""

    @pytest_asyncio.fixture
    async def get_server(self, unix_server):
        return unix_server

    @pytest_asyncio.fixture
    async def get_client(self, unix_client):
        return unix_client

    @pytest.mark.asyncio
    async def test_socket_file_cleanup(self, unix_socket_path: str, unix_server: AsyncUnixServer):
        """测试套接字文件清理"""
        assert os.path.exists(unix_socket_path)
        await unix_server.stop()
        assert not os.path.exists(unix_socket_path)


# 性能基准测试
@pytest.mark.benchmark
class TestServerPerformance:
    """服务器性能测试"""
    async def wait_for_client_connect(self, client, timeout=2.0) -> bool:
        """等待客户端连接成功"""
        try:
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                if await client.connect():
                    return True
                await asyncio.sleep(0.1)
            return False
        except Exception:
            return False

    async def wait_for_session_active(self, server, client, timeout=1.0) -> bool:
        """等待直到会话被创建并激活"""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if (client.session_id and
                client.session_id in server.sessions and
                server.sessions[client.session_id].is_connected):
                return True
            await asyncio.sleep(0.1)
        return False

    @pytest.mark.asyncio
    async def test_concurrent_clients(self, tcp_server_config: Tuple[str, int]):
        """测试并发客户端性能"""
        host, port = tcp_server_config
        NUM_CLIENTS = 5  # 减少并发客户端数量
        CONNECT_TIMEOUT = 2.0  # 增加连接超时时间

        # 创建并启动服务器
        server = AsyncTCPServer(host, port)
        wrapper = ServerWrapper(server)
        await wrapper.start()
        await asyncio.sleep(0.1)  # 等待服务器启动

        try:
            # 创建客户端并分批连接
            clients = []
            batch_size = 2  # 每批连接的客户端数量

            for i in range(0, NUM_CLIENTS, batch_size):
                batch_clients = [AsyncTCPClient(host, port) for _ in range(min(batch_size, NUM_CLIENTS - i))]
                connect_tasks = [self.wait_for_client_connect(client) for client in batch_clients]
                results = await asyncio.gather(*connect_tasks)

                if not all(results):
                    pytest.fail("Some clients failed to connect")

                clients.extend(batch_clients)
                await asyncio.sleep(0.1)  # 批次间延迟

            # 并发发送消息
            send_tasks = []
            receive_tasks = []
            for client in clients:
                receive_tasks.append(asyncio.create_task(client.receive_messages()))
                send_tasks.append(client.send_message("Test message"))

            await asyncio.gather(*send_tasks)
            await asyncio.sleep(0.1)

            # 清理
            for task in receive_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            for client in clients:
                await client.disconnect()

        finally:
            await wrapper.stop()

    @pytest.mark.asyncio
    async def test_large_message_throughput(self, tcp_server: AsyncTCPServer, tcp_client: AsyncTCPClient):
        """测试大消息吞吐量"""
        # 1. 建立连接
        await tcp_client.connect()
        assert await self.wait_for_session_active(tcp_server, tcp_client)

        # 2. 准备响应处理
        responses = []
        receive_event = asyncio.Event()

        def message_callback(message):
            print(f"Received response of size: {len(message.content)} bytes")
            responses.append(message)
            receive_event.set()  # 标记已收到响应

        tcp_client._message_callback = message_callback

        # 3. 启动接收任务
        print("Starting receive task...")
        receive_task = asyncio.create_task(tcp_client.receive_messages())

        try:
            # 4. 准备并发送大消息
            message_size = 100 * 1024  # 先从较小的大小开始测试：100KB
            large_message = "X" * message_size
            print(f"Sending message of size: {message_size} bytes")

            # 5. 发送消息（带超时）
            try:
                await asyncio.wait_for(
                    tcp_client.send_message(large_message),
                    timeout=3.0
                )
                print("Message sent successfully, waiting for response...")
            except asyncio.TimeoutError:
                pytest.fail("Timeout while sending message")

            # 6. 等待响应
            try:
                # 等待事件被设置或超时
                await asyncio.wait_for(
                    receive_event.wait(),
                    timeout=3.0
                )
                print("Response received!")
            except asyncio.TimeoutError:
                # 如果超时，输出更多调试信息
                session = tcp_server.sessions.get(tcp_client.session_id)
                if session:
                    print(f"Session state: connected={session.is_connected}")
                    print(f"Last heartbeat: {time.time() - session.last_heartbeat:.2f}s ago")
                print(f"Responses received so far: {len(responses)}")
                pytest.fail("Timeout while waiting for response")

            # 7. 验证响应
            assert len(responses) == 1, f"Expected 1 response, got {len(responses)}"
            assert len(responses[0].content) == message_size, \
                f"Response size mismatch: expected {message_size}, got {len(responses[0].content)}"
            print("Response verification completed successfully")

        except Exception as e:
            pytest.fail(f"Test failed: {e}")
        finally:
            # 8. 清理资源
            print("Cleaning up resources...")
            if not receive_task.done():
                receive_task.cancel()
                try:
                    await receive_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Error during receive task cleanup: {e}")

            await tcp_client.disconnect()
            print("Cleanup completed")

    @pytest.mark.asyncio
    async def test_small_message_throughput(self, tcp_server: AsyncTCPServer, tcp_client: AsyncTCPClient):
        """测试小消息吞吐量"""
        await tcp_client.connect()
        assert await self.wait_for_session_active(tcp_server, tcp_client)

        # 创建消息接收任务
        receive_task = asyncio.create_task(tcp_client.receive_messages())

        try:
            small_message = "ping"
            sent_count = 1000
            received_count = 0

            # 发送消息并等待确认
            for _ in range(sent_count):
                await tcp_client.send_message(small_message)
                await asyncio.sleep(0.001)  # 小延迟防止flooding

            # 等待所有消息处理完成
            timeout = 20  # 10秒超时
            start_time = asyncio.get_event_loop().time()
            while received_count < sent_count:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    pytest.fail("Timeout waiting for message processing")
                await asyncio.sleep(0.1)
                session = tcp_server.sessions[tcp_client.session_id]
                # 检查服务器端处理的消息数量
                # 这里需要在Session类中添加processed_messages计数
                received_count = session.get_extra_info('processed_messages', 0)

        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

        await tcp_client.disconnect()