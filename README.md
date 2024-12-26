# Async Socket Chat

A demonstration of asynchronous socket-based client-server communication supporting both TCP and Unix sockets, with enhanced message handling and session management.

## Features

- Supports both TCP and Unix socket communication
- Multiple client connection modes (interactive CLI and file-based input)
- Robust message protocol with encryption and integrity checks
- Session management with heartbeat monitoring
- Asynchronous I/O using Python's asyncio
- Extensible base classes for custom implementations

## Architecture

### Core Components

- **Message Protocol**: Enhanced binary protocol with CRC32 checksums and HMAC authentication
- **Session Management**: UUID-based session tracking with heartbeat monitoring
- **Base Classes**: Abstract implementations for server, client, and session management
- **Interface Definitions**: Clear contract definitions through abstract base classes

### Message Types

- SESSION_INIT/ACK: Session establishment
- HEARTBEAT: Connection health monitoring
- MESSAGE: Regular communication
- ERROR: Error notifications
- DISCONNECT: Clean session termination

## Installation

```bash
pip install -r requirements.txt
```

The server will handle all client interactions concurrently, maintaining separate sessions for each connection.

## Usage

### Starting the Server

TCP Server:
```bash
python tcp_server.py [host] [port]
# Default: localhost:9999
```

Unix Socket Server:
```bash
python unix_server.py [socket_path]
# Default: /tmp/chat.sock
```

### Running Clients

#### TCP Client

Interactive Mode:
```bash
python tcp_client.py interactive [host] [port]
```

File Input Mode:
```bash
python tcp_client.py file messages.txt [host] [port]
```

#### Unix Socket Client

Interactive Mode:
```bash
python unix_client.py interactive [socket_path]
```

File Input Mode:
```bash
python unix_client.py file messages.txt [socket_path]
```

### Client Commands

- Type messages and press Enter to send
- Type 'exit' to close connection
- Ctrl+C to force quit

### Concurrent Client Support

Both TCP and Unix socket servers support multiple simultaneous client connections. To demonstrate:

1. Start the server (TCP or Unix socket)
2. Run multiple clients simultaneously:
```bash
# Terminal 1
python tcp_client.py file messages.txt

# Terminal 2 
python tcp_client.py file messages2.txt

# Terminal 3 (optional)
python tcp_client.py interactive
```

## Protocol Details

The message protocol includes:
- 8-byte magic number
- 2-byte version
- 2-byte message type
- Header length and CRC32
- Content length and CRC32
- HMAC-SHA256 authentication
- JSON-encoded headers
- Binary message content

## Integration Guide

### Using in Your Project

1. Core Module Integration:
```python
from message import EnhancedMessageHandler, Message
from base_server import BaseServer
from base_client import BaseAsyncClient
from session import BaseSession
```

2. Implement Custom Communication:
```python
class MyCustomServer(BaseServer):
    async def process_message(self, session: ISession, message: Message) -> None:
        # Custom business logic
        response = process_business_logic(message.content)
        await self.send_message(session, response)

class MyCustomClient(BaseAsyncClient):
    async def start(self, message_source: str) -> None:
        # Custom startup logic
        await self.connect()
        await self.custom_message_handling()
```

3. Message Protocol Usage:
```python
# Server-side message handling
handler = EnhancedMessageHandler(hmac_key=b'your-secret-key')
message = Message.from_dict({
    'type': MessageType.MESSAGE,
    'content': your_data,
    'content_type': 'application/json'
})
encoded = handler.encode_message(message)
```

4. Session Management:
```python
class CustomSession(BaseSession):
    def __init__(self, session_id: str, writer: asyncio.StreamWriter):
        super().__init__(session_id, writer)
        self.add_extra_info('custom_data', {})
        
    async def custom_cleanup(self):
        # Custom cleanup logic
        await self.close()
```

### Key Integration Points

1. **Message Protocol**: Use `message.py` for robust message encoding/decoding
2. **Session Management**: Extend `BaseSession` for custom session handling
3. **Server Implementation**: Inherit `BaseServer` for custom server logic
4. **Client Implementation**: Extend `BaseAsyncClient` for custom client behavior

### Best Practices

- Maintain heartbeat mechanisms for connection health
- Handle session cleanup properly
- Use the message protocol's security features (HMAC, CRC32)
- Implement proper error handling and logging
- Consider implementing retry mechanisms for critical operations

## Development

### Project Structure

```
├── base_client.py     # Abstract client implementation
├── base_server.py     # Abstract server implementation
├── message.py         # Message protocol implementation
├── session.py         # Session management
├── tcp_client.py      # TCP client implementation
├── tcp_server.py      # TCP server implementation
├── unix_client.py     # Unix socket client
└── unix_server.py     # Unix socket server
```

### Extending the System

1. Create custom session types:
```python
class CustomSession(BaseSession):
    def __init__(self, session_id: str, writer: asyncio.StreamWriter):
        super().__init__(session_id, writer)
        # Add custom initialization
```

2. Implement custom servers:
```python
class CustomServer(BaseServer):
    async def process_message(self, session: ISession, message: Message) -> None:
        # Custom message handling
```

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)