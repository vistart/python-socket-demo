import os
import sys
import tempfile

import pytest
from functools import wraps
from typing import Optional, Callable

def is_windows() -> bool:
    """检查是否为 Windows 系统"""
    return sys.platform.startswith('win')


def skip_on_windows(func: Optional[Callable] = None, reason: str = "Unix sockets not supported on Windows"):
    """
    装饰器: 在 Windows 系统上跳过测试
    可以装饰类或方法

    用法:
        @skip_on_windows
        class TestUnixSocket:
            ...

        @skip_on_windows
        def test_unix_socket():
            ...

        @skip_on_windows(reason="Custom skip reason")
        def test_custom_skip():
            ...
    """
    if func is None:
        # 带参数的装饰器调用
        return lambda f: skip_on_windows(f, reason=reason)

    @wraps(func)
    def wrapper(*args, **kwargs):
        if is_windows():
            pytest.skip(reason)
        return func(*args, **kwargs)

    # 处理类装饰器情况
    if isinstance(func, type):
        # 如果是类，修改 setUp 或创建一个新的
        original_setup = getattr(func, 'setUp', None)

        def new_setup(self, *args, **kwargs):
            if is_windows():
                pytest.skip(reason)
            if original_setup:
                original_setup(self, *args, **kwargs)

        func.setUp = new_setup
        return func

    return wrapper


def get_socket_path() -> Optional[str]:
    """
    根据操作系统获取适当的套接字路径
    Windows 上返回 None
    """
    if is_windows():
        return None
    return os.path.join(tempfile.gettempdir(), f'test_{os.getpid()}.sock')
