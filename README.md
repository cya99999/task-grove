# 枝序 · Task Grove

一个为「程序还在跑，这段时间我能做什么？」设计的本地桌面任务管理器。每类工作是一棵树，步骤从左向右生长。把脑中的交错步骤放到树枝上，再从当前可做的动作中挑一件。

原生 Python / Qt 窗口，适用于 Linux 桌面。任务离线存储，不需要账号或服务器。

![枝序桌面窗口](assets/screenshot.png)

## 开始使用

```bash
git clone https://github.com/cya99999/task-grove.git
cd task-grove
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python install.py
./run.sh
```

`install.py` 添加应用菜单入口，并启用**当前用户登录桌面后自动启动**。之后可以在应用菜单搜索「枝序」，也可以点系统托盘中的树枝图标打开或收起窗口。Ubuntu GNOME 需要 AppIndicator 扩展；Ubuntu 默认桌面通常已启用。如果没有可用托盘，应用会保留任务栏入口。自启动可以在「使用说明 / 更多」中关闭。

首次打开是空白树，可以直接创建自己的类别，也可以从「使用说明 / 更多 → 载入示例任务树」体验交互。

## 让步骤长在树上

- **新类别**：创建一棵树。点击树干的 `＋` 添加任务。
- **添加后续分支**：先做当前步骤，再做新步骤。一个节点可有多个后续分支。
- **在此前插入一步**：`前一步 → 当前` 变为 `前一步 → 新步骤 → 当前`。
- **在此后插入一步**：`当前 → 后续分支` 变为 `当前 → 新步骤 → 后续分支`。
- **添加同层并行任务**：和当前任务拥有相同的前置节点，可以并行。
- **点击任务文字完成**：当前节点消失，所有后续分支按原顺序接到前面的节点；不会删除后续任务。
- **拖动任务**：拖动节点会携带整条后续分支。放到另一节点中间，成为其后续；放到节点上/下边缘，在同层前/后重排。拖到左侧类别名，可跨类移动。绿色提示显示放置位置，循环依赖会被拒绝。
- **收起分支**：点击节点右下角的小箭头。右键可以编辑、等待、移动、插入或删除整条分支。

同层节点没有额外的顺序依赖；拖动到上/下边缘只改变排列顺序。需要增加前后依赖时，拖入节点中间，或使用「插入一步」。

## 在空档中选下一步

窗口下方只显示直接连接到类别树干、且没有处于等待状态的任务。它们没有尚未完成的前置步骤。

编辑任务时填写预计分钟数，再按「5 / 10 / 15 / 30 / 60 分钟内」筛选。限定时长时，**未估时的任务不参与筛选**。筛选会跟随左侧所选类别；选择「所有任务树」可以跨类别挑选。

编译、训练或下载时，可以右键将任务设为等待。等待期间，其后续分支也不会成为可做任务；时间到了会通过托盘提醒（运行时每 15 秒检查一次，首次启动后也会检查已过期的等待）。等待结束不会自动完成任务，需确认结果后点击完成。程序关闭期间不会发通知；系统勿扰设置可能隐藏桌面通知。

## 快捷键与窗口

| 操作 | 快捷键 |
| --- | --- |
| 新增任务 / 类别 | `Ctrl+N` / `Ctrl+Shift+N` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Shift+Z` |
| 查找步骤（含收起的分支） | `Ctrl+F` |
| 缩放任务树 | `Ctrl+滚轮`、工具栏 `−` / `＋` |
| 移动画布 | 拖动画布空白处，或使用滚动条 |
| 收起到托盘 | `Esc`、关闭或最小化窗口 |
| 完全退出 | 托盘菜单或更多菜单 → 退出枝序 |

同一数据目录只运行一个实例；再次启动会唤起已有窗口。窗口尺寸和位置会保留，也可从更多菜单打开「窗口置顶」。

## 数据与备份

默认文件位置：

```text
~/.local/share/task-grove/tasks.json       # 当前任务树
~/.local/share/task-grove/tasks.json.bak   # 前一次成功保存
~/.config/autostart/task-grove.desktop    # 当前用户自启动入口
~/.local/share/applications/task-grove.desktop
```

遵守 `XDG_DATA_HOME` / `XDG_CONFIG_HOME`。任务每次修改都会经过结构验证并原子保存。主文件损坏时尝试恢复上一份备份，同时保留损坏原文件。无法恢复时会报告错误，不会自动清空数据。

通过更多菜单导出 / 导入 JSON。导入会替换当前树，可撤销；最近 100 次修改可以在当前会话中撤销，退出后不保留撤销记录。任务内容、个人备份和虚拟环境不会提交到 Git 仓库。

修改代码后无需重新安装；若移动整个项目目录，请重新运行 `install.py` 更新启动路径。卸载入口：

```bash
rm -f ~/.config/autostart/task-grove.desktop
rm -f ~/.local/share/applications/task-grove.desktop
```

退出应用后可删除仓库。以上操作保留个人任务数据。

## 搜狗中文输入（Ubuntu / Fcitx 4）

搜狗使用 Fcitx 4；PySide6 的官方 wheel 默认不包含 Fcitx 插件。Ubuntu 的系统插件依赖系统 Qt 私有 ABI，不能直接复制给不同版本的 Qt。本项目在启动前为应用加载 `.qt-plugins/<Qt版本>/platforminputcontexts/` 中匹配的插件；只向 Qt 暴露这个专用目录，避免混入系统平台插件。尊重已有的 `QT_IM_MODULE`，不会修改桌面全局输入法设置。

当前本机已构建并验证 Qt 6.12.0 专用插件：通过真实 X11 键盘事件输入 `zhongwen` 并选词，编辑框得到「中文」。依赖固定为已验证版本；升级 Qt 后需要重新构建。二进制插件和 SDK 不进入 Git，下面是新机器上的重建方法（无需 sudo）：

```bash
python3 -m venv /tmp/task-grove-buildenv
/tmp/task-grove-buildenv/bin/python -m pip install aqtinstall
/tmp/task-grove-buildenv/bin/python -m aqt install-qt linux desktop 6.12.0 linux_gcc_64 --archives qtbase --outputdir /tmp/task-grove-sdk
mkdir -p /tmp/task-grove-deps
(cd /tmp/task-grove-deps
 apt-get download extra-cmake-modules libxkbcommon-dev libgl-dev libglx-dev libopengl-dev libegl-dev libglvnd-core-dev
 for deb in *.deb; do dpkg-deb -x "$deb" root; done)
.venv/bin/python scripts/build_fcitx_plugin.py --qt-prefix /tmp/task-grove-sdk/6.12.0/gcc_64 --dev-prefix /tmp/task-grove-deps/root/usr
```

需要本机已有 CMake、Ninja、G++ 和搜狗/Fcitx。脚本下载固定版本的 [Fcitx 官方插件源码](https://github.com/fcitx/fcitx-qt5/tree/c328b03f32a4276d9aeb3213d1f3f959ef6848f2)，在临时目录编译、验证后安装到应用专用目录，并保留上游许可证。退出并重新打开枝序后生效。插件自身遵守上游许可证，不适用本项目的 MIT 许可证。

## 开发与测试

```bash
.venv/bin/python -m unittest discover -s tests -v
# 独立数据目录，不影响日常任务
./run.sh --data-dir /tmp/task-grove-demo
```

测试覆盖模型的接续、前后插入、跨类别迁移、同层重排、循环保护、撤销重做、空档过滤、保存失败、损坏恢复、导入导出，以及 Qt 窗口的点击完成、拖放、搜索展开、筛选和倒计时。GUI 测试使用 Qt offscreen 后端。

使用 [Qt Graphics View](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-graphicsview.html) 绘制树和处理交互，使用 [QSystemTrayIcon](https://doc.qt.io/qt-6/qsystemtrayicon.html) 集成桌面托盘。

MIT License。Qt / PySide6 由 Qt 项目按其自身许可证发布。
