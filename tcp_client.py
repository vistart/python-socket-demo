import asyncio
import aioconsole
from typing import Optional

from message import JSONMessageHandler
from tcp_interfaces import IClient


class AsyncTCPClient(IClient):
    """异步TCP客户端实现类"""

    def __init__(self, host: str = 'localhost', port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.connected = False
        self.session_id: Optional[str] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_handler = JSONMessageHandler()

    async def connect(self) -> bool:
        """连接到服务器并完成会话建立"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host,
                self.port
            )

            # 等待服务器的会话初始化消息
            init_data = await self.reader.read(1024)
            if not init_data:
                print("Connection closed by server during handshake")
                return False

            init_message = self.message_handler.decode_message(init_data)
            if (not self.message_handler.validate_message(init_message) or
                    init_message.get('type') != 'session_init'):
                print("Invalid session initialization from server")
                return False

            # 保存会话ID
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

            self.connected = True
            self.running = True
            print(f"Connected to server at {self.host}:{self.port}")
            print(f"Session established: {self.session_id}")
            return True

        except Exception as e:
            print(f"Failed to connect to server: {e}")
            return False

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

    async def start(self, message_source: str) -> None:
        """启动客户端并处理消息

        Args:
            message_source: 消息源文件路径
        """
        if not await self.connect():
            return

        try:
            # 创建所有任务
            tasks = [
                asyncio.create_task(self.receive_messages()),
                asyncio.create_task(self.send_heartbeat()),
                asyncio.create_task(self.send_messages_from_file(message_source))
            ]

            # 等待任何一个任务完成
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            # 取消其他正在运行的任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            print(f"Error in client tasks: {e}")
        finally:
            await self.disconnect()

    async def send_messages_from_file(self, message_file: str) -> None:
        """从文件读取并发送消息

        Args:
            message_file: 消息文件路径
        """
        try:
            with open(message_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not self.running:
                        break

                    message = line.strip()
                    if message:
                        await self.send_message(message)
                        await asyncio.sleep(1)  # 控制发送频率

                        if message.lower() == 'exit':
                            break

        except FileNotFoundError:
            print(f"Message file {message_file} not found")
        except Exception as e:
            print(f"Error reading message file: {e}")

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

class InteractiveTCPClient(IClient):
    """交互式异步TCP客户端实现类"""

    def __init__(self, host: str = 'localhost', port: int = 9999):
        self.host = host
        self.port = port
        self.running = False
        self.connected = False
        self.session_id: Optional[str] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.message_handler = JSONMessageHandler()

    async def connect(self) -> bool:
        """连接到服务器并完成会话建立"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host,
                self.port
            )

            # 等待服务器的会话初始化消息
            init_data = await self.reader.read(1024)
            if not init_data:
                print("Connection closed by server during handshake")
                return False

            init_message = self.message_handler.decode_message(init_data)
            if (not self.message_handler.validate_message(init_message) or
                    init_message.get('type') != 'session_init'):
                print("Invalid session initialization from server")
                return False

            # 保存会话ID
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

            self.connected = True
            self.running = True
            print(f"Connected to server at {self.host}:{self.port}")
            print(f"Session established: {self.session_id}")
            print("Type your messages (type 'exit' to quit):")
            return True

        except Exception as e:
            print(f"Failed to connect to server: {e}")
            return False

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

    async def start(self, message_source: str = '') -> None:
        """启动客户端并处理消息"""
        if not await self.connect():
            return

        try:
            # 创建所有任务
            tasks = [
                asyncio.create_task(self.receive_messages()),
                asyncio.create_task(self.send_heartbeat()),
                asyncio.create_task(self.handle_user_input())
            ]

            # 等待任何一个任务完成
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            # 取消其他正在运行的任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            print(f"Error in client tasks: {e}")
        finally:
            await self.disconnect()

    async def handle_user_input(self) -> None:
        """处理用户输入"""
        try:
            while self.running:
                message = await aioconsole.ainput()
                if not message:
                    continue

                if message.lower() == 'exit':
                    self.running = False
                    break

                await self.send_message(message)

        except EOFError:
            self.running = False
        except Exception as e:
            print(f"Error handling user input: {e}")
            self.running = False

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
                    print(f"Server: {content}")

            except ValueError as e:
                print(f"Error decoding message: {e}")
            except Exception as e:
                print(f"Error receiving message: {e}")
                break

        self.running = False

async def mainAsync():
    client = AsyncTCPClient()
    try:
        await client.start('messages.txt')
    except KeyboardInterrupt:
        await client.disconnect()

async def mainInteractive():
    client = InteractiveTCPClient()
    try:
        await client.start()
    except KeyboardInterrupt:
        await client.disconnect()


if __name__ == '__main__':
    asyncio.run(mainInteractive())