import pytest
import asyncio
import os
import socket
import tempfile
import time
from typing import Generator, Tuple
import pytest_asyncio

from tcp_server import AsyncTCPServer, TCPSession
from unix_server import AsyncUnixServer, UnixSession
from tcp_client import AsyncTCPClient
from unix_client import AsyncUnixClient
from message import Message, MessageType


# Helper functions
def find_free_port() -> int:
    """Find an available TCP port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def get_temp_socket_path() -> str:
    """Get a temporary Unix socket path"""
    return os.path.join(tempfile.gettempdir(), f'test_chat_{time.time_ns()}.sock')


# Common fixtures
@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Base test configuration mixins
class TCPTestConfig:
    """TCP server/client configuration"""

    @pytest.fixture(autouse=True)
    def tcp_config(self):
        """Configure TCP test parameters"""
        self.port = find_free_port()
        self.host = 'localhost'
        self.server_class = AsyncTCPServer
        self.server_args = (self.host, self.port)
        self.client_class = AsyncTCPClient
        self.client_args = (self.host, self.port)


class UnixTestConfig:
    """Unix socket server/client configuration"""

    @pytest.fixture(autouse=True)
    def unix_config(self):
        """Configure Unix socket test parameters"""
        self.socket_path = get_temp_socket_path()
        self.server_class = AsyncUnixServer
        self.server_args = (self.socket_path,)
        self.client_class = AsyncUnixClient
        self.client_args = (self.socket_path,)
        yield
        # Cleanup socket file
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


class ServerClientFixtures:
    """Common server and client fixtures"""

    @pytest_asyncio.fixture
    async def server(self):
        """Start server fixture"""
        server = self.server_class(*self.server_args)
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)  # Wait for server to start
        yield server
        await server.stop()
        await server_task

    @pytest_asyncio.fixture
    async def client(self):
        """Create a test client"""
        client = self.client_class(*self.client_args)
        yield client
        await client.disconnect()


# Enhanced server for testing
class EnhancedServer(AsyncTCPServer):
    """Server with custom message processing for testing"""

    async def process_message(self, session, message):
        if message.type == MessageType.MESSAGE.value:
            # Echo message with count
            if not hasattr(session, 'message_count'):
                session.add_extra_info('message_count', 0)
            count = session.get_extra_info('message_count') + 1
            session.add_extra_info('message_count', count)

            response_content = f"Echo #{count}: {message.content.decode()}"
            response = Message(
                MessageType.MESSAGE.value,
                response_content.encode(),
                session.session_id,
                'text/plain'
            )
            await self.send_message(session, response)
        else:
            await super().process_message(session, message)


# Test cases
class TestBasicServerMixin:
    """Common test cases for both TCP and Unix servers"""

    @pytest.mark.asyncio
    async def test_basic_connection(self, server, client):
        """Test basic client connection and disconnection"""
        assert await client.connect()
        assert client.connected
        assert client.session_id is not None
        await client.disconnect()
        assert not client.connected

    @pytest.mark.asyncio
    async def test_heartbeat(self, server, client):
        """Test heartbeat mechanism"""
        assert await client.connect()
        await asyncio.sleep(0.1)
        await client.send_heartbeat(interval=0.1)
        await asyncio.sleep(0.3)
        assert client.connected
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_message_echo(self, server, client):
        """Test basic message sending and receiving"""
        assert await client.connect()
        test_message = "Hello, Server!"
        await client.send_message(test_message)
        await asyncio.sleep(0.1)  # Wait for response
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_messages(self, server, client):
        """Test sending multiple messages in sequence"""
        assert await client.connect()
        messages = ["Message 1", "Message 2", "Message 3"]
        for msg in messages:
            await client.send_message(msg)
            await asyncio.sleep(0.1)
        await client.disconnect()


class TestBenchmarkMixin:
    """Common benchmark tests"""

    async def run_concurrent_clients(self, num_clients, messages_per_client):
        """Helper to run multiple clients concurrently"""
        clients = []
        for i in range(num_clients):
            client = self.client_class(*self.client_args)
            assert await client.connect()
            clients.append(client)

        tasks = []
        for client in clients:
            for j in range(messages_per_client):
                message = f"Message {j} from client"
                task = asyncio.create_task(client.send_message(message))
                tasks.append(task)

        await asyncio.gather(*tasks)
        await asyncio.sleep(0.1)  # Wait for responses

        for client in clients:
            await client.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_concurrent_clients(self, server):
        """Benchmark concurrent client connections"""
        start_time = time.time()
        await self.run_concurrent_clients(num_clients=50, messages_per_client=10)
        duration = time.time() - start_time
        print(f"\nConcurrent clients benchmark: {duration:.2f} seconds")

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_large_message_throughput(self, server):
        """Benchmark large message throughput"""
        client = self.client_class(*self.client_args)
        assert await client.connect()

        large_message = "X" * 1000000  # 1MB message
        start_time = time.time()
        for _ in range(10):  # Send 10MB total
            await client.send_message(large_message)
            await asyncio.sleep(0.01)
        duration = time.time() - start_time

        await client.disconnect()
        print(f"\nLarge message throughput: {duration:.2f} seconds")

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_small_message_throughput(self, server):
        """Benchmark small message throughput"""
        client = self.client_class(*self.client_args)
        assert await client.connect()

        small_message = "ping"  # Small message
        start_time = time.time()
        for _ in range(1000):  # Send 1000 small messages
            await client.send_message(small_message)
            await asyncio.sleep(0.001)
        duration = time.time() - start_time

        await client.disconnect()
        print(f"\nSmall message throughput: {duration:.2f} seconds")


# Concrete test classes
class TestTCPServer(TCPTestConfig, ServerClientFixtures, TestBasicServerMixin):
    """TCP server test implementation"""
    pass


class TestUnixServer(UnixTestConfig, ServerClientFixtures, TestBasicServerMixin):
    """Unix server test implementation"""
    pass


class TestEnhancedTCPServer(TCPTestConfig, ServerClientFixtures):
    """Test cases for enhanced TCP server functionality"""

    @pytest.fixture(autouse=True)
    def enhanced_config(self, tcp_config):
        """Override server class with enhanced version"""
        self.server_class = EnhancedServer

    @pytest.mark.asyncio
    async def test_enhanced_message_processing(self, server, client):
        """Test enhanced message processing with message counting"""
        assert await client.connect()
        messages = ["First", "Second", "Third"]
        for msg in messages:
            await client.send_message(msg)
            await asyncio.sleep(0.1)
        await client.disconnect()


class TestTCPBenchmark(TCPTestConfig, ServerClientFixtures, TestBenchmarkMixin):
    """TCP benchmark implementation"""
    pass


class TestUnixBenchmark(UnixTestConfig, ServerClientFixtures, TestBenchmarkMixin):
    """Unix benchmark implementation"""
    pass