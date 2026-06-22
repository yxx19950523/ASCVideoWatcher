# ASC视频监控助手（Python版）

中文桌面工具，用于 App Store Connect 的 Product Page Optimization 视频反复上传测试。

当前流程：

- 只选择一个本地视频。
- 打开 App Store Connect 后，手动切到主语言国家和 PPO 测试方案页面。
- 默认处理页面里的第一个测试方案。
- 自动上传这个视频。
- 上传后视频会排到媒体列表第一位。
- 第一位出现灰色占位图时声音/通知提示。
- 第一位出现视频预览图时再次声音/通知提示。
- 程序悬停第一位媒体，点击左上角红色移除按钮。
- 删除后台视频后，继续重新上传同一个本地视频。

## 运行

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

首次启动后会打开 Chrome。请在浏览器里登录 App Store Connect，并进入 PPO 视频页面。登录 Cookie 保存在应用数据目录，下次会自动复用。

## 页面要求

请先在浏览器里手动完成这些步骤：

1. 登录 App Store Connect。
2. 进入 Product Page Optimization 页面。
3. 切换到主语言国家。
4. 停留在包含多个“测试方案”的页面。

工具默认处理第一个测试方案，也就是界面里的 `测试方案序号` 为 `0`。如果要处理第二个测试方案，填 `1`。

## 选择器

默认情况下可以不填选择器。工具会自动寻找包含这些文案的测试方案区域：

- `选择文件`
- `全部删除`
- `App 预览` / `张截屏`

如果 Apple 后台页面改版导致识别不准，可以在界面里填写：

- `测试方案选择器`：锁定测试方案容器。
- `第一位媒体选择器`：锁定媒体列表第一位。
- `上传 input 选择器`：默认 `input[type=file]`。
- `红色移除按钮选择器`：悬停媒体后出现的左上角红色按钮。
- `删除确认按钮选择器`：弹窗里的确认删除按钮。

## macOS 打包 APP

```bash
chmod +x build_tools/build_macos.sh
./build_tools/build_macos.sh
```

产物：

```text
dist/ASC视频监控助手.app
```

## Windows 打包 EXE

在 Windows 机器的 PowerShell 中运行：

```powershell
.\build_tools\build_windows.ps1
```

产物：

```text
dist\ASC视频监控助手\ASC视频监控助手.exe
```

## 为什么 Windows EXE 要在 Windows 上打

PyInstaller 不支持在 macOS 上直接交叉编译 Windows EXE。同一份源码可以打两个系统，但需要分别在对应系统执行打包脚本。如果要完全自动化，可以用 GitHub Actions 的 macOS 和 Windows runner 同时产出两个安装包。

## 自动生成两个系统产物

已经提供 GitHub Actions：

```text
.github/workflows/build-asc-video-watcher.yml
```

推送到 GitHub 后，打开 Actions 里的 `Build ASC Video Watcher`，可以手动运行 `workflow_dispatch`。完成后下载两个 artifact：

- `ASC视频监控助手-macOS`
- `ASC视频监控助手-Windows`
