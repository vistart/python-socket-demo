import json
from typing import Any, Dict

from tcp_interfaces import IMessageHandler


class JSONMessageHandler(IMessageHandler):
    """JSON格式消息处理器"""

    def encode_message(self, message: Dict[str, Any]) -> bytes:
        return json.dumps(message).encode('utf-8')

    def decode_message(self, data: bytes) -> Dict[str, Any]:
        try:
            return json.loads(data.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")

    def validate_message(self, message: Dict[str, Any]) -> bool:
        return isinstance(message, dict) and 'type' in message and 'content' in message
