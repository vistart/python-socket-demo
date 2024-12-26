import asyncio
import aioconsole
from base_client import BaseAsyncClient


class AsyncTCPClient(BaseAsyncClient):
    """从文件读取命令的TCP客户端"""

    def __init__(self, host: str = 'localhost', port: int = 9999):
        super().__init__()
        self.host = host
        self.port = port

    async def connect(self) -> bool:
        """连接到TCP服务器"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host,
                self.port
            )

            # 处理握手
            init_data = await self.reader.read(1024)
            if not await self._handle_handshake(init_data):
                return False

            self.connected = True
            self.running = True
            print(f"Connected to server at {self.host}:{self.port}")
            print(f"Session established: {self.session_id}")
            return True

        except Exception as e:
            print(f"Failed to connect to server: {e}")
            return False

    async def start(self, message_source: str) -> None:
        """启动客户端并处理消息"""
        if not await self.connect():
            return

        try:
            tasks = [
                asyncio.create_task(self.receive_messages()),
                asyncio.create_task(self.send_heartbeat()),
                asyncio.create_task(self.send_messages_from_file(message_source))
            ]

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

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
        """从文件读取并发送消息"""
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


class InteractiveTCPClient(AsyncTCPClient):
    """交互式TCP客户端"""

    async def start(self, message_source: str = None) -> None:
        """启动交互式客户端

        Args:
            message_source: 该参数在交互模式下被忽略
        """
        if not await self.connect():
            return

        try:
            tasks = [
                asyncio.create_task(self.receive_messages()),
                asyncio.create_task(self.send_heartbeat()),
                asyncio.create_task(self.interactive_loop())
            ]

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

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

    async def interactive_loop(self) -> None:
        """交互式命令循环"""
        print("Enter messages (type 'exit' to quit):")
        while self.running:
            try:
                # 使用aioconsole进行异步输入
                line = await aioconsole.ainput('> ')
                message = line.strip()

                if message:
                    if message.lower() == 'exit':
                        break
                    await self.send_message(message)

            except EOFError:
                break
            except Exception as e:
                print(f"Error reading input: {e}")
                break


async def run_file_client(message_file: str, host: str = 'localhost', port: int = 9999):
    """运行文件读取模式的客户端"""
    client = AsyncTCPClient(host, port)
    try:
        await client.start(message_file)
    except KeyboardInterrupt:
        await client.disconnect()


async def run_interactive_client(host: str = 'localhost', port: int = 9999):
    """运行交互式客户端"""
    client = InteractiveTCPClient(host, port)
    try:
        await client.start()
    except KeyboardInterrupt:
        await client.disconnect()


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python tcp_client.py [file|interactive] [message_file] [host] [port]")
        sys.exit(1)

    mode = sys.argv[1]
    host = sys.argv[3] if len(sys.argv) > 3 else 'localhost'
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 9999

    if mode == 'file':
        if len(sys.argv) < 3:
            print("Error: message file required for file mode")
            sys.exit(1)
        asyncio.run(run_file_client(sys.argv[2], host, port))
    elif mode == 'interactive':
        asyncio.run(run_interactive_client(host, port))
    else:
        print("Invalid mode. Use 'file' or 'interactive'")
        sys.exit(1)