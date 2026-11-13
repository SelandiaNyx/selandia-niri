# 挂起后屏幕无法点亮：证据与采集

2026-10-11 结论：**未能复现，不能宣称已修复或电源正常。** 之前的隔离锁屏测试只证明 Wayland 锁定就绪、超时及服务管理，不涉及真实硬件挂起→唤醒。

上一启动 ID `69f5a48fca3b4cfeb0156721b816d402` 的日志保存在 `.validation/resume-rust-20261011/`。本机是 Intel 双 GPU，驱动为 i915 与 xe，非 AMD/NVIDIA。Niri 记录 475 次 `Page flip commit failed ... Device or resource busy`。18:24:42 的 DP-6 断连后出现 `missing surface in vblank callback`、无输出；20:25:52 同一 DP-6 重新连接，选择 3840×2160@160Hz。日志中没有 `PM: suspend entry/exit`，也没有 systemd-suspend.service 执行记录。因此**已证实 DRM 提交失败和显示连接中断，尚不能把它归因于系统挂起恢复**。这也可能是显示器深度休眠/链路断连，或记录丢失；仅凭现有日志无法区分。

不在没有实测的情况下修改内核参数、降低刷新率、换驱动或更换锁屏链路。保持独立 sleep-lock 的 before-sleep 锁屏和 after-resume power-on 路径；这不是正常性证明。由于无法代替用户按实体唤醒键并观察屏幕，本轮没有主动使正式机器进入挂起。

## 下一次真实尝试（用户操作）

先保存工作。在桌面终端进入项目并启动只读记录器，保持此终端运行：

```bash
cd "/home/SelandiaNyx/Selandia's Niri"
timeout --kill-after=2s 3600s python3 -B tools/resume_probe.py record --output .validation/resume-actual
```

总预算 1 小时，用于等待一次真实挂起和唤醒；仅从用户的正式终端运行，不在受限沙箱里连接系统总线。总线连接最多 5 秒，每条采集命令最多 8 秒。记录器先保存基线，然后监听 login1 PrepareForSleep，分别记录事件及唤醒后快照、15 秒后的快照。它不挂起、不解锁、不重启服务、不改显示器状态，输出在项目内持久目录。

在另一终端进行**真正系统挂起**，并用键盘/电源键唤醒：

```bash
timeout --kill-after=2s 15s systemctl suspend
```

单次快照最多约 11 条命令，每条 8 秒，故总预算 100 秒。唤醒成功后立即采集，30 秒后再采一次（使用同一 after 标签，文件名唯一），然后 Ctrl+C 停止记录器：

```bash
timeout --kill-after=2s 100s python3 -B tools/resume_probe.py capture --label after --output .validation/resume-actual
sleep 30
timeout --kill-after=2s 100s python3 -B tools/resume_probe.py capture --label after --output .validation/resume-actual
```

如果黑屏但能 SSH/切到 TTY，在强制重启之前运行 `capture --label failure`；TTY 若没有 NIRI_SOCKET，先从记录器的 start JSON 读取 `compositor_socket` 并在该命令前设置 `NIRI_SOCKET=实际路径`。若连 SSH/TTY 都无响应，重启后**先保留上一启动日志**：

```bash
mkdir -p .validation/resume-actual
timeout --kill-after=2s 15s journalctl -b -1 -k --no-pager -o short-monotonic > .validation/resume-actual/previous-kernel.log
timeout --kill-after=2s 15s journalctl -b -1 _COMM=niri --no-pager -o short-monotonic > .validation/resume-actual/previous-niri-process.log
timeout --kill-after=2s 15s journalctl -b -1 --user -u niri.service -u 'selandia-niri@sleep-lock.service' -u 'selandia-lock@*' --no-pager -o short-monotonic > .validation/resume-actual/previous-user.log
timeout --kill-after=2s 15s journalctl -b -1 -u systemd-suspend.service -u systemd-logind.service --no-pager -o short-monotonic > .validation/resume-actual/previous-sleep.log
```

若 dmesg 因权限被拒绝，快照保留错误，不当作空/成功；请在自己的终端运行 `sudo timeout --kill-after=2s 15s dmesg --time-format iso > .validation/resume-actual/dmesg.log` 并输入密码。记录器同时采集 `niri.service` 和 `_COMM=niri` 日志，兼容由登录管理器直接启动的 Niri；还收集可读的 kernel journal、GPU 驱动和连接器/sys状态、Niri outputs、锁屏/空闲/睡眠单元与阻塞位置、inhibitors，命令有超时且快照唯一命名/原子保存。

判定时比较 boot ID、单调时间、PrepareForSleep true/false、内核 PM entry/exit、GPU/DRM 错误、连接器与 outputs、sleep-lock/lock 进程和单元结果。只有在真实挂起和唤醒链条均记录到时，才描述“真实恢复通过”；失败时区分整机未醒、GPU未恢复、DP链路断开和锁屏卡住。
