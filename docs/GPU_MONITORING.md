# 显卡监控的读数与范围

系统与维护页按显卡 PCI 地址分别展示读数。支持的全卡接口继续使用 `gpu_busy_percent` 或 NVIDIA 的可选查询；Intel i915、Xe 则可按需读取当前用户可访问的 DRM 客户端计数器。总览、顶栏和隐藏的系统页不启动这项客户端扫描。

客户端读数表示**可读客户端的最忙引擎占比**，并非整张显卡所有工作的精确总利用率。它可能遗漏其他用户、权限受限和刚退出的客户端，也没有把不同引擎的百分比相加。`—` 表示首样本、权限不足、设备休眠或接口不可用；稳定的两次有效采样确实没有新增工作时才显示 0%。新客户端最多等待 10 秒发现。

实现无需安装监控包或取得管理员权限。i915 使用引擎忙碌纳秒的增量；Xe 使用忙周期与同一 GPU 时钟的总周期增量。相同 PCI 地址和客户端 ID 的重复、共享文件描述符只计一次；有多个同类硬件引擎时按容量归一化。首次采样、设备恢复、进程身份变化、GPU 时钟重置或长时间未采样后重新建立基线；进程启动时间不可读时持续显示不可用，避免跨进程复用计算速率。计数器暂时回退时保留高水位，避免负值或异常尖峰。这些口径来自 [Linux DRM 客户端统计规范](https://docs.kernel.org/gpu/drm-usage-stats.html) 和 [Xe 实现说明](https://docs.kernel.org/gpu/xe/xe-drm-usage-stats.html)。

客户端显存保留逐个客户端及内存区域的 resident/shared 数值，不相加冒充全卡显存：不同客户端可以持有同一份共享缓冲区；GPU 系统内存也不同于专用 VRAM。全卡显存接口没有读数时保持不可用。

采样器只在页面需要时被调用，没有额外常驻进程或线程。新客户端发现默认每 10 秒一次；已知客户端按页面刷新间隔读取。每轮发现有 50 毫秒的用户态检查预算和 16384 个描述符上限，超限会标注覆盖不完整。该预算约束扫描循环，不能打断已经进入内核的单次文件读取。

读取硬件计数器也可能影响功耗。已休眠或正在切换电源状态的显卡跳过动态读数，恢复后重新预热；这减少主动唤醒，但状态检查与随后的读取之间仍有竞争窗口。Xe 的 [fdinfo 实现](https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/xe/xe_drm_client.c) 和 [hwmon 读取](https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/xe/xe_hwmon.c) 包含运行时电源管理操作，因此仅在打开监控页时采样。

`idle_residency_ms`、`rc6_residency_ms` 记录 GT 在低功耗状态的驻留时间；其反比可以描述非低功耗状态的时间比例，不能直接作为执行引擎利用率。频率读数同样不能替代占用率。Xe 的 [GT Idle 实现](https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/xe/xe_gt_idle.c) 明确区分 C0/C6，读取驻留计数器本身也可能涉及运行时电源管理。hwmon 的 `energy*_input` 是累计能量，需要单位换算和两次时间差才能估算平均功率，不能直接标成瓦数。
