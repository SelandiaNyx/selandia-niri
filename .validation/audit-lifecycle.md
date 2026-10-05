# 电源与锁屏只读自检（2026-10-04）

本轮没有更改项目源码、用户配置、服务或睡眠抑制器；只读取运行状态，并在临时目录执行假进程与隔离 PATH 的命令测试。

## L1 · 高优先级：锁屏进程与触发服务的生命周期没有隔离

位置：`niri/shell/lock_session.py:83–85`、`systemd/selandia-niri@.service.in:8–12`、`niri/scripts/components:43–48`、`niri/shell/sleep_guard.py:91–98,130`。

`idle`、`sleep-lock` 服务中的 swayidle 调用 `desktop lock`，该脚本直接执行 lock_session.py，后者用 `Popen(start_new_session=True)` 启动 swaylock。这会创建新的进程会话，但不转移 systemd cgroup。真实服务只读查询均返回 `KillMode=control-group`。因而停止或重启触发服务时，它启动的锁屏进程也会被终止。

复现证据：在 `/tmp` 用假锁屏进程执行真实 `lock_session.lock()`，得到 `parent_sid=1`、`fake_lock_sid=4`，但父子 `/proc/*/cgroup` 均为 `/user.slice/user-1000.slice/user@1000.service/app.slice/kitty-2047-0.scope`；`same_cgroup=true`、`different_session=true`。没有在用户桌面实际触发服务重启或锁屏。

[systemd 官方实现文档](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.kill.xml)规定 `control-group` 会在服务停止时终止该组剩余进程。[Wayland 会话锁协议](https://raw.githubusercontent.com/wayland-mirror/wayland-protocols/main/staging/ext-session-lock/ext-session-lock-v1.xml)规定锁客户端死亡时会话必须继续保持锁定；能否安全恢复由合成器决定，可能留下无法正常解锁的黑屏。

这是已确认的进程归属缺陷及协议风险；没有证明它就是之前“整夜闲置后无信号”的原因。当前定时器关闭，故当前不会由 idle 自动触发这一流程。

交给其他 AI 的修改指令：

> 给锁屏进程建立独立、按 Wayland display 区分的 systemd 用户服务或 scope，使其 cgroup 不属于 idle、sleep-lock、控制中心或临时调用终端。保留 ready-fd 成功确认、display/PID/start-time 校验和并发互斥；启动服务成功不能替代锁屏 ready 确认。保护已经成功的锁屏，设置更新或触发服务重启不得结束它。不要仅将共享服务模板的 KillMode 改为 process/none，也不要通过杀死锁屏“恢复”。隔离测试应覆盖：由 idle 与 sleep-lock 分别触发锁屏后，停止/重启触发服务，锁屏 PID 保持存活、仍可正常解锁；同 display 多次调用复用已确认进程；不同 display 不互相影响；没有 ready 时拒绝执行睡眠。先在独立嵌套 Niri 和测试专用 unit 中验证，不触碰真实桌面锁屏。

## L2 · 中优先级：被阻止的手动睡眠先锁屏，失败没有界面说明

位置：`niri/scripts/desktop:105–113`，尤其第 109 行；自动睡眠生成入口位于 `niri/shell/system_settings.py:137`。

当前只读状态为 `awake=true, available=true, error=false, timers_enabled=false`，即 logind 睡眠抑制器正在生效。电源菜单仍无条件显示“睡眠”，选择后执行 `lock && systemctl suspend`，没有预检抑制状态、错误捕获或通知。

隔离 PATH 测试完整选择 Suspend，并令 systemctl 返回睡眠被抑制错误，调用顺序为 `fuzzel → lock_session.py → systemctl suspend`；退出码 1；标准错误为 `Call to Suspend failed: Sleep is inhibited by Selandia Niri`；`notify-send` 调用次数 0。真实锁屏和真实睡眠均未执行。图形界面用户因此只会进入锁屏，无法得知睡眠请求被拒绝的原因。

交给其他 AI 的修改指令：

> 将睡眠动作统一为可测试的入口。在锁屏前检查本项目 sleep_guard 的真实 inhibitor 状态；保护开启时禁止发出睡眠请求，并显示“保持唤醒正在阻止睡眠，请先关闭该保护”等当前语言提示，或者在菜单中禁用并说明。不得暗中关闭守卫、使用忽略 inhibitor 参数或绕过用户保护。未被阻止时保持“锁屏 ready 成功后才睡眠”的顺序，捕获 systemctl 请求失败并提供可见且可追溯的错误。让手动及自动入口复用同一实现，补充 guard 开启、锁屏失败、systemctl 失败与成功四种测试；guard 开启时不锁屏、不发睡眠命令且有明确提示。

## 验证边界

现有锁屏单测覆盖 readiness、进程复用、不同 display、过期记录与启动失败，但没有 systemd cgroup 生命周期测试。嵌套烟雾测试可以验证私有合成器内实际锁屏 ready/复用；不能证明真实硬件在整夜闲置、DP 断连、息屏或 S3/deep 睡眠之后必然恢复。

既有 `.validation/power-incident.md` 显示历史日志的显示输出断连与 page-flip 错误，但没有确定硬件根因。本轮不应把“所有测试通过”写成“唤醒问题已经解决”。
