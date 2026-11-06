#!/usr/bin/env python3
"""Install desktop launcher and enable login startup for this checkout."""
from task_grove.desktop import install, AUTOSTART

if __name__ == '__main__':
    print('应用菜单：', install())
    print('登录自启动：', AUTOSTART)
