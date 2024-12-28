import asyncio
import os
import socket
import sys
import tempfile
import time
from typing import AsyncGenerator, Generator, Tuple, Optional, Callable, Any

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
@pytest.mark.skipif(sys.platform.startswith('win'), reason="not supported on Windows")
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
@pytest.mark.skipif(sys.platform.startswith('win'), reason="not supported on Windows")
class TestServerPerformance:
    """Server performance benchmark tests for both TCP and Unix sockets"""

    @pytest.fixture(params=['tcp', 'unix'])
    def server_client_pair(self, request) -> Tuple[BaseServer, Callable, str]:
        """Fixture to provide server-client pairs for both TCP and Unix sockets"""
        if request.param == 'tcp':
            host, port = 'localhost', find_free_port()
            return (
                AsyncTCPServer(host, port),
                lambda: AsyncTCPClient(host, port),
                f'TCP({host}:{port})'
            )
        else:
            socket_path = get_temp_socket_path()
            return (
                AsyncUnixServer(socket_path),
                lambda: AsyncUnixClient(socket_path),
                f'Unix({socket_path})'
            )

    async def wait_for_session_active(self, server, client, timeout=1.0) -> bool:
        """Wait until session is created and activated"""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if (client.session_id and
                client.session_id in server.sessions and
                server.sessions[client.session_id].is_connected):
                return True
            await asyncio.sleep(0.1)
        return False

    async def wait_for_client_connect(self, client, timeout=2.0) -> bool:
        """Wait for client to connect successfully"""
        try:
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                if await client.connect():
                    return True
                await asyncio.sleep(0.1)
            return False
        except Exception:
            return False

    async def setup_connection(self, server: BaseServer, client_factory: Callable) -> Tuple[ServerWrapper, Any]:
        """Helper function to setup server and client"""
        # Start server
        wrapper = ServerWrapper(server)
        await wrapper.start()
        await asyncio.sleep(0.1)

        # Create and connect client
        client = client_factory()
        await client.connect()
        assert await self.wait_for_session_active(server, client)

        return wrapper, client

    @pytest.mark.asyncio
    async def test_large_message_throughput(self, server_client_pair, benchmark):
        """Test large message throughput for both TCP and Unix sockets"""
        server, client_factory, connection_type = server_client_pair
        wrapper, client = await self.setup_connection(server, client_factory)

        try:
            # Setup message handling
            responses = []
            receive_event = asyncio.Event()
            original_handle_message = client._handle_message

            async def test_handle_message(message):
                await original_handle_message(message)
                responses.append(message)
                receive_event.set()

            client._handle_message = test_handle_message
            receive_task = asyncio.create_task(client.receive_messages())

            # Prepare large message
            message_size = 100 * 1024  # 100KB
            large_message = "X" * message_size

            # Benchmark function
            async def send_receive_cycle():
                responses.clear()
                receive_event.clear()
                await client.send_message(large_message)
                try:
                    await asyncio.wait_for(receive_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pytest.fail(f"{connection_type}: Timeout waiting for response")
                assert len(responses) == 1
                assert len(responses[0].content) == message_size

            # Run benchmark with description
            benchmark.extra_info.update({
                'connection_type': connection_type,
                'test_name': 'large_message'
            })
            await benchmark.pedantic(
                send_receive_cycle,
                iterations=10,
                rounds=50,
                warmup_rounds=2
            )

        finally:
            # Cleanup
            client._handle_message = original_handle_message
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
            await client.disconnect()
            await wrapper.stop()

    @pytest.mark.asyncio
    async def test_small_message_batch(self, server_client_pair, benchmark):
        """Test small message batch processing for both TCP and Unix sockets"""
        server, client_factory, connection_type = server_client_pair
        wrapper, client = await self.setup_connection(server, client_factory)

        try:
            receive_task = asyncio.create_task(client.receive_messages())

            # Benchmark function
            async def send_batch():
                small_message = "ping"
                batch_size = 100
                for _ in range(batch_size):
                    await client.send_message(small_message)
                    await asyncio.sleep(0.001)

                # Wait for server processing
                session = server.sessions[client.session_id]
                start_time = asyncio.get_event_loop().time()
                while session.get_extra_info('processed_messages', 0) < batch_size:
                    if asyncio.get_event_loop().time() - start_time > 5:
                        pytest.fail(f"{connection_type}: Timeout waiting for batch processing")
                    await asyncio.sleep(0.1)

            # Run benchmark with description
            benchmark.extra_info.update({
                'connection_type': connection_type,
                'test_name': 'small_message_batch'
            })
            await benchmark.pedantic(
                send_batch,
                iterations=5,
                rounds=20,
                warmup_rounds=1
            )

        finally:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
            await client.disconnect()
            await wrapper.stop()

    @pytest.mark.asyncio
    async def test_concurrent_clients(self, server_client_pair, benchmark):
        """Test concurrent client performance for both TCP and Unix sockets"""
        server, client_factory, connection_type = server_client_pair
        wrapper = ServerWrapper(server)
        await wrapper.start()
        await asyncio.sleep(0.1)

        try:
            async def concurrent_test():
                NUM_CLIENTS = 5
                # Create and connect clients
                clients = []
                for _ in range(NUM_CLIENTS):
                    client = client_factory()
                    assert await self.wait_for_client_connect(client)
                    clients.append(client)

                # Send test messages
                tasks = []
                for client in clients:
                    tasks.append(asyncio.create_task(client.send_message("Test message")))

                await asyncio.gather(*tasks)

                # Cleanup clients
                for client in clients:
                    await client.disconnect()

            # Run benchmark with description
            benchmark.extra_info.update({
                'connection_type': connection_type,
                'test_name': 'concurrent_clients'
            })
            await benchmark.pedantic(
                concurrent_test,
                iterations=3,
                rounds=10,
                warmup_rounds=1
            )

        finally:
            await wrapper.stop()

    @pytest.mark.asyncio
    async def test_message_latency(self, server_client_pair, benchmark):
        """Test message round-trip latency for both TCP and Unix sockets"""
        server, client_factory, connection_type = server_client_pair
        wrapper, client = await self.setup_connection(server, client_factory)

        try:
            # Setup message handling
            response_received = asyncio.Event()
            original_handle_message = client._handle_message

            async def test_handle_message(message):
                await original_handle_message(message)
                response_received.set()

            client._handle_message = test_handle_message
            receive_task = asyncio.create_task(client.receive_messages())

            # Benchmark function
            async def measure_latency():
                response_received.clear()
                start_time = time.time()
                await client.send_message("ping")
                try:
                    await asyncio.wait_for(response_received.wait(), timeout=1.0)
                    latency = time.time() - start_time
                    return latency
                except asyncio.TimeoutError:
                    pytest.fail(f"{connection_type}: Timeout measuring latency")

            # Run benchmark with description
            benchmark.extra_info.update({
                'connection_type': connection_type,
                'test_name': 'message_latency'
            })
            await benchmark.pedantic(
                measure_latency,
                iterations=100,
                rounds=10,
                warmup_rounds=2
            )

        finally:
            client._handle_message = original_handle_message
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
            await client.disconnect()
            await wrapper.stop()


def visualize_benchmark_results(json_file):
    """
    读取 pytest-benchmark 的 JSON 输出并创建可视化图表
    """
    # 读取基准测试结果
    import json
    import matplotlib.pyplot as plt
    import numpy as np
    with open(json_file) as f:
        results = json.load(f)

    # 提取测试数据
    benchmarks = results['benchmarks']

    # 按测试名称和连接类型组织数据
    test_data = {}
    for bench in benchmarks:
        test_name = bench['extra_info']['test_name']
        conn_type = bench['extra_info']['connection_type'].split('(')[0]  # 提取 TCP 或 Unix

        if test_name not in test_data:
            test_data[test_name] = {'TCP': None, 'Unix': None}

        # 存储均值（秒）和标准差
        test_data[test_name][conn_type] = {
            'mean': bench['stats']['mean'],
            'stddev': bench['stats']['stddev']
        }

    # 创建图表
    plt.style.use('seaborn-v0_8-deep')
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
    fig.suptitle('Socket Performance Benchmark Results', fontsize=16)

    # 配置子图
    plots = {
        'large_message': {
            'ax': ax1,
            'title': 'Large Message Throughput',
            'ylabel': 'Time (seconds)'
        },
        'small_message_batch': {
            'ax': ax2,
            'title': 'Small Message Batch Processing',
            'ylabel': 'Time (seconds)'
        },
        'concurrent_clients': {
            'ax': ax3,
            'title': 'Concurrent Clients Setup',
            'ylabel': 'Time (seconds)'
        },
        'message_latency': {
            'ax': ax4,
            'title': 'Message Round-trip Latency',
            'ylabel': 'Time (milliseconds)'
        }
    }

    # 绘制每个测试的结果
    bar_width = 0.35
    for test_name, plot_info in plots.items():
        ax = plot_info['ax']
        data = test_data[test_name]

        # 准备数据
        tcp_data = data['TCP']
        unix_data = data['Unix']

        # 转换延迟测试的单位为毫秒
        if test_name == 'message_latency':
            tcp_data = {
                'mean': tcp_data['mean'] * 1000,
                'stddev': tcp_data['stddev'] * 1000
            }
            unix_data = {
                'mean': unix_data['mean'] * 1000,
                'stddev': unix_data['stddev'] * 1000
            }

        # 绘制柱状图
        x = np.arange(1)
        ax.bar(x - bar_width / 2, tcp_data['mean'], bar_width,
               label='TCP', color='#2ecc71',
               yerr=tcp_data['stddev'], capsize=5)
        ax.bar(x + bar_width / 2, unix_data['mean'], bar_width,
               label='Unix', color='#3498db',
               yerr=unix_data['stddev'], capsize=5)

        # 设置图表属性
        ax.set_title(plot_info['title'])
        ax.set_ylabel(plot_info['ylabel'])
        ax.set_xticks([])
        ax.legend()

        # 添加数值标签
        def add_value_label(x, value, yerr):
            ax.text(x, value + yerr + (ax.get_ylim()[1] * 0.02),
                    f'{value:.3f}',
                    ha='center', va='bottom')

        add_value_label(x - bar_width / 2, tcp_data['mean'], tcp_data['stddev'])
        add_value_label(x + bar_width / 2, unix_data['mean'], unix_data['stddev'])

    plt.tight_layout()
    plt.savefig('benchmark_results.png', dpi=300, bbox_inches='tight')
    plt.close()