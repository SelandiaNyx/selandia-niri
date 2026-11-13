# 已替代组件的离线恢复

2026-10-11 按用户明确授权清理 Waybar 与 Kitty。旧组件不再安装或提供日常切换入口。Fuzzel dmenu、SwayNC、SwayBG、SwayIdle、SwayLock 仍承担功能，不属于已被完全替代的软件，继续保留，理由见 [组件清单](RUST_COMPONENTS.md)。旧的回退演练结果属于历史记录，不代表当前仍能调用已删除程序。

当前必需组件安装：

```sh
paru -S --needed eww anyrun
sudo pacman -S --needed alacritty
```

删除前保存四个包的版本、SHA256 与签名，位于 `.validation/rust-prune-20261011/packages/`，清单 `packages.json`。只删除显式列出的四个包，不使用 `-Rns`，不清理共享依赖。项目源码改动/删除也在 `release/journal.json` 备份，故障或强杀后可恢复。

如要恢复旧组件，在自己的终端输入 sudo 密码，先恢复本地签名包：

```sh
sudo pacman -U -- .validation/rust-prune-20261011/packages/waybar-0.15.0-3-x86_64.pkg.tar.zst .validation/rust-prune-20261011/packages/kitty-0.49.2-1-x86_64.pkg.tar.zst .validation/rust-prune-20261011/packages/kitty-terminfo-0.49.2-1-x86_64.pkg.tar.zst .validation/rust-prune-20261011/packages/kitty-shell-integration-0.49.2-1-x86_64.pkg.tar.zst
python3 -B tools/live_update.py rollback --journal .validation/rust-prune-20261011/release
niri/scripts/desktop daily-components
```

源码回滚会恢复原本的生成分支、配置与入口，也回滚本轮日历点击修改；回滚后可使用旧 `emergency-fallback` 入口切换到旧组件。此路径无需网络或重新编译，不重启 Niri。若后续改动与回滚冲突，工具先报告冲突，不覆盖用户修改。恢复目录及暂存目录不要在发布后立即清除；保留到下一次已验证发布，之后由用户决定删除。包重新安装的 sudo 密码只在终端或系统认证提示中输入，不写入项目。
