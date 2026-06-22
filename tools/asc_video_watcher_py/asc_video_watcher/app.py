from __future__ import annotations

import asyncio
import json
import os
import platform
import queue
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from playwright.async_api import async_playwright

from .detector import CLICK_UPLOAD_BUTTON_SCRIPT, FIRST_MEDIA_STATUS_SCRIPT, REMOVE_FIRST_MEDIA_SCRIPT


APP_NAME = "ASC视频监控助手"
DEFAULT_URL = "https://appstoreconnect.apple.com/apps"


def app_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    path = base / "ASCVideoWatcher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class Settings:
    product_url: str = DEFAULT_URL
    refresh_seconds: int = 20
    plan_index: int = 0
    plan_selector: str = ""
    media_selector: str = ""
    upload_button_selector: str = ""
    upload_selector: str = "input[type=file]"
    placeholder_selector: str = ""
    preview_selector: str = ""
    remove_selector: str = ""
    confirm_selector: str = ""
    auto_cycle: bool = True
    notify_enabled: bool = False
    sound_enabled: bool = True
    browser_channel: str = "chrome"


class WatcherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1120x760")
        self.root.minsize(980, 660)

        self.data_dir = app_data_dir()
        self.profile_dir = self.data_dir / "browser_profile"
        self.log_file = self.data_dir / "watcher.log"
        self.settings_file = self.data_dir / "settings.json"
        self.settings = self.load_settings()

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.running = False
        self.started_at = 0.0
        self.placeholder_at = 0.0
        self.last_phase = "idle"
        self.next_refresh_at = 0.0
        self.video_path = ""
        self.cycle_count = 0

        self.build_ui()
        self.apply_settings_to_ui()
        self.root.after(200, self.drain_events)
        self.root.after(300, self.update_clock)

    def load_settings(self) -> Settings:
        if not self.settings_file.exists():
            return Settings()
        try:
            data = json.loads(self.settings_file.read_text("utf-8"))
            defaults = asdict(Settings())
            return Settings(**{**defaults, **data})
        except Exception:
            return Settings()

    def save_settings(self) -> None:
        self.settings = Settings(
            product_url=self.product_url_var.get().strip() or DEFAULT_URL,
            refresh_seconds=max(5, int(self.refresh_var.get() or 20)),
            plan_index=max(0, int(self.plan_index_var.get() or 0)),
            plan_selector=self.plan_selector_var.get().strip(),
            media_selector=self.media_selector_var.get().strip(),
            upload_button_selector=self.upload_button_selector_var.get().strip(),
            upload_selector=self.upload_selector_var.get().strip() or "input[type=file]",
            placeholder_selector=self.placeholder_var.get().strip(),
            preview_selector=self.preview_var.get().strip(),
            remove_selector=self.remove_selector_var.get().strip(),
            confirm_selector=self.confirm_selector_var.get().strip(),
            auto_cycle=bool(self.auto_cycle_var.get()),
            notify_enabled=False,
            sound_enabled=bool(self.sound_var.get()),
            browser_channel=self.browser_var.get().strip() or "chrome",
        )
        self.settings_file.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), "utf-8")

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, font=("", 20, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="只处理主语言当前页面里的第一个测试方案：上传同一个视频，监控第一位媒体，预览出现后移除并循环重传。").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.status_var = tk.StringVar(value="待机")
        ttk.Label(header, textvariable=self.status_var, font=("", 13, "bold")).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self.root, padding=(16, 8, 16, 16))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)

        form = ttk.LabelFrame(body, text="设置", padding=12)
        form.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 12))

        self.product_url_var = tk.StringVar()
        self.refresh_var = tk.StringVar()
        self.plan_index_var = tk.StringVar()
        self.plan_selector_var = tk.StringVar()
        self.media_selector_var = tk.StringVar()
        self.upload_button_selector_var = tk.StringVar()
        self.upload_selector_var = tk.StringVar()
        self.placeholder_var = tk.StringVar()
        self.preview_var = tk.StringVar()
        self.remove_selector_var = tk.StringVar()
        self.confirm_selector_var = tk.StringVar()
        self.browser_var = tk.StringVar()
        self.auto_cycle_var = tk.BooleanVar()
        self.notify_var = tk.BooleanVar()
        self.sound_var = tk.BooleanVar()
        self.refresh_var.trace_add("write", self.on_refresh_change)

        video_box = ttk.LabelFrame(form, text="第 1 步：选择视频", padding=10)
        video_box.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        video_box.columnconfigure(0, weight=1)
        self.selected_video_var = tk.StringVar(value="尚未选择视频")
        ttk.Label(video_box, textvariable=self.selected_video_var, width=34).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(video_box, text="选择视频...", command=self.pick_video).grid(row=0, column=1, sticky="e")

        fields = [
            ("产品优化页面地址", self.product_url_var, 42),
            ("刷新间隔（秒）", self.refresh_var, 12),
            ("测试方案序号（0=第一个）", self.plan_index_var, 12),
        ]
        for row, (label, var, width) in enumerate(fields):
            base_row = row * 2 + 1
            ttk.Label(form, text=label).grid(row=base_row, column=0, sticky="w", pady=(0 if row == 0 else 7, 3))
            ttk.Entry(form, textvariable=var, width=width).grid(row=base_row + 1, column=0, sticky="ew")

        browser_row = len(fields) * 2 + 1
        ttk.Label(form, text="浏览器").grid(row=browser_row, column=0, sticky="w", pady=(7, 3))
        browser_combo = ttk.Combobox(
            form,
            textvariable=self.browser_var,
            values=("chrome", "msedge", "chromium", "firefox", "webkit"),
            state="readonly",
            width=39,
        )
        browser_combo.grid(row=browser_row + 1, column=0, sticky="ew")

        checkbox_row = browser_row + 2
        ttk.Checkbutton(form, text="预览出现后移除后台视频并重传同一个视频", variable=self.auto_cycle_var).grid(row=checkbox_row, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(form, text="声音提示", variable=self.sound_var).grid(row=checkbox_row + 1, column=0, sticky="w", pady=(5, 0))
        sound_test = ttk.Frame(form)
        sound_test.grid(row=checkbox_row + 2, column=0, sticky="ew", pady=(8, 0))
        sound_test.columnconfigure((0, 1), weight=1)
        ttk.Button(sound_test, text="测试占位音", command=lambda: self.play_sound("placeholder")).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(sound_test, text="测试预览音", command=lambda: self.play_sound("ready")).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        buttons = ttk.Frame(form)
        buttons.grid(row=checkbox_row + 3, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1), weight=1)
        self.start_btn = ttk.Button(buttons, text="第 2 步：打开浏览器", command=self.start)
        self.start_btn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.ready_btn = ttk.Button(buttons, text="页面已准备好，开始监听", command=self.mark_page_ready, state="disabled")
        self.ready_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.stop_btn = ttk.Button(buttons, text="停止", command=self.stop, state="disabled")
        self.stop_btn.grid(row=2, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="打开日志", command=self.open_logs).grid(row=2, column=1, sticky="ew", padx=(6, 0))

        metrics = ttk.LabelFrame(body, text="状态", padding=12)
        metrics.grid(row=0, column=1, sticky="ew")
        metrics.columnconfigure((0, 1, 2), weight=1)
        self.phase_var = tk.StringVar(value="未开始")
        self.elapsed_var = tk.StringVar(value="00:00")
        self.next_refresh_var = tk.StringVar(value="--")
        self.notice_var = tk.StringVar(value="暂无")
        self.video_var = tk.StringVar(value="未选择")
        self.cycle_var = tk.StringVar(value="0")
        for col, (title, var) in enumerate([("当前阶段", self.phase_var), ("总计时", self.elapsed_var), ("下次刷新", self.next_refresh_var)]):
            ttk.Label(metrics, text=title).grid(row=0, column=col, sticky="w")
            ttk.Label(metrics, textvariable=var, font=("", 15, "bold")).grid(row=1, column=col, sticky="w", pady=(3, 0))
        ttk.Label(metrics, text="循环次数").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(metrics, textvariable=self.cycle_var, font=("", 13, "bold")).grid(row=3, column=0, sticky="w")
        ttk.Label(metrics, text="当前视频").grid(row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Label(metrics, textvariable=self.video_var).grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Label(metrics, text="最新提示").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(metrics, textvariable=self.notice_var, font=("", 13, "bold")).grid(row=5, column=0, columnspan=3, sticky="w")

        hint = ttk.LabelFrame(body, text="操作提示", padding=12)
        hint.grid(row=1, column=1, sticky="ew", pady=(12, 12))
        ttk.Label(hint, text="先在 App Store Connect 手动切到主语言国家，并停留在包含测试方案的页面；程序默认处理页面中的第一个测试方案。").grid(row=0, column=0, sticky="w")
        ttk.Label(hint, text="视频上传后会排到第一位。程序监控第一位媒体：灰色占位响一次，预览图出现再响一次，然后悬停并点击左上角红色移除按钮。").grid(row=1, column=0, sticky="w", pady=(5, 0))

        auto_info = ttk.LabelFrame(body, text="自动识别", padding=12)
        auto_info.grid(row=2, column=1, sticky="ew", pady=(0, 12))
        ttk.Label(auto_info, text="无需手动填写选择器。程序会自动识别：第一个测试方案、页面里的“选择文件”、媒体列表第一位、悬停后左上角红色移除按钮。").grid(row=0, column=0, sticky="w")
        ttk.Label(auto_info, text="如果某一步失败，请直接看运行日志里的失败原因，把那一句发给我即可。").grid(row=1, column=0, sticky="w", pady=(5, 0))

        log_frame = ttk.LabelFrame(body, text="运行日志", padding=8)
        log_frame.grid(row=3, column=1, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=18, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def apply_settings_to_ui(self) -> None:
        self.product_url_var.set(self.settings.product_url)
        self.refresh_var.set(str(self.settings.refresh_seconds))
        self.plan_index_var.set(str(self.settings.plan_index))
        self.plan_selector_var.set(self.settings.plan_selector)
        self.media_selector_var.set(self.settings.media_selector)
        self.upload_button_selector_var.set(self.settings.upload_button_selector)
        self.upload_selector_var.set(self.settings.upload_selector)
        self.placeholder_var.set(self.settings.placeholder_selector)
        self.preview_var.set(self.settings.preview_selector)
        self.remove_selector_var.set(self.settings.remove_selector)
        self.confirm_selector_var.set(self.settings.confirm_selector)
        self.auto_cycle_var.set(self.settings.auto_cycle)
        self.notify_var.set(self.settings.notify_enabled)
        self.sound_var.set(self.settings.sound_enabled)
        self.browser_var.set(self.settings.browser_channel)

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_refresh_change(self, *_args) -> None:
        try:
            seconds = max(5, int(self.refresh_var.get() or 20))
        except ValueError:
            return
        self.settings.refresh_seconds = seconds
        if self.running:
            self.next_refresh_at = time.time() + seconds
            self.next_refresh_var.set(f"{seconds} 秒")

    def play_sound(self, kind: str = "info") -> None:
        threading.Thread(target=self._play_sound_worker, args=(kind,), daemon=True).start()

    def _play_sound_worker(self, kind: str = "info") -> None:
        try:
            if platform.system() == "Windows":
                import winsound
                alias = "SystemAsterisk" if kind == "placeholder" else "SystemExclamation"
                frequency = 650 if kind == "placeholder" else 1200 if kind == "ready" else 900
                duration = 220 if kind == "placeholder" else 360 if kind == "ready" else 220
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
                time.sleep(0.08)
                winsound.Beep(frequency, duration)
                if kind == "ready":
                    winsound.Beep(frequency + 180, duration)
                return
            if platform.system() == "Darwin":
                sound = "/System/Library/Sounds/Ping.aiff" if kind == "placeholder" else "/System/Library/Sounds/Glass.aiff"
                subprocess.Popen(["afplay", sound])
                return
            self.root.bell()
        except Exception:
            try:
                self.root.bell()
            except Exception:
                pass

    def notify(self, title: str, body: str, kind: str = "info") -> None:
        self.notice_var.set(f"{title}：{body}")
        if self.settings.sound_enabled:
            self.play_sound(kind)
        self.log(f"{title}：{body}")

    def toast(self, title: str, body: str) -> None:
        try:
            if platform.system() == "Darwin":
                script = f'display notification {json.dumps(body)} with title {json.dumps(title)}'
                subprocess.Popen(["osascript", "-e", script])
                return
            if platform.system() == "Windows":
                safe_title = title.replace("'", "''")
                safe_body = body.replace("'", "''")
                subprocess.Popen([
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"[reflection.assembly]::loadwithpartialname('System.Windows.Forms') > $null; "
                    f"[reflection.assembly]::loadwithpartialname('System.Drawing') > $null; "
                    f"$n=new-object system.windows.forms.notifyicon; "
                    f"$n.icon=[system.drawing.systemicons]::information; "
                    f"$n.visible=$true; $n.showballoontip(5000,'{safe_title}','{safe_body}','Info'); "
                    f"Start-Sleep -Seconds 6; $n.dispose()"
                ], creationflags=0x08000000)
                return
        except Exception:
            pass
        messagebox.showinfo(title, body)

    def pick_video(self) -> None:
        path = filedialog.askopenfilename(
            title="选择一个视频文件",
            filetypes=[("视频文件", "*.mov *.mp4 *.m4v"), ("所有文件", "*.*")]
        )
        if path:
            self.video_path = path
            self.selected_video_var.set(Path(path).name)
            self.video_var.set(Path(path).name)
            self.notice_var.set(f"已选择视频：{Path(path).name}，下一次上传会使用它")
            self.log(f"已选择视频：{path}")

    def open_logs(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if platform.system() == "Darwin":
            subprocess.Popen(["open", str(self.log_file.parent)])
        elif platform.system() == "Windows":
            os.startfile(self.log_file.parent)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(self.log_file.parent)])

    def start(self) -> None:
        if self.running:
            return
        if not self.video_path:
            messagebox.showerror(APP_NAME, "请先选择一个本地视频。")
            return
        if not Path(self.video_path).exists():
            messagebox.showerror(APP_NAME, "选择的视频文件不存在。")
            return
        try:
            self.save_settings()
        except ValueError:
            messagebox.showerror(APP_NAME, "刷新间隔和测试方案序号必须是数字。")
            return

        self.running = True
        self.stop_event.clear()
        self.ready_event.clear()
        self.started_at = time.time()
        self.placeholder_at = 0
        self.last_phase = "idle"
        self.cycle_count = 0
        self.cycle_var.set("0")
        self.status_var.set("监控中")
        self.phase_var.set("浏览器启动中")
        self.start_btn.configure(state="disabled")
        self.ready_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.log("正在打开浏览器。请先在网页里登录并进入 PPO 测试方案页面。")
        self.worker = threading.Thread(target=self.worker_entry, daemon=True)
        self.worker.start()

    def mark_page_ready(self) -> None:
        if not self.running:
            return
        self.ready_event.set()
        self.ready_btn.configure(state="disabled")
        self.status_var.set("开始监听")
        self.phase_var.set("页面已确认，准备刷新和上传")
        self.notice_var.set("页面已准备好：开始刷新、上传和监听")
        self.log("用户确认页面已准备好，开始执行刷新、上传和监听。")

    def stop(self) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.ready_event.set()
        self.running = False
        self.status_var.set("已停止")
        self.start_btn.configure(state="normal")
        self.ready_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        self.next_refresh_var.set("--")
        self.log("监控已停止。")

    def worker_entry(self) -> None:
        asyncio.run(self.watch())

    async def watch(self) -> None:
        async with async_playwright() as p:
            browser_choice = self.settings.browser_channel
            browser_type = p.chromium
            if browser_choice == "firefox":
                browser_type = p.firefox
            elif browser_choice == "webkit":
                browser_type = p.webkit
            launch_args = {
                "headless": False,
                "user_data_dir": str(self.profile_dir),
                "viewport": {"width": 1440, "height": 900},
            }
            if browser_choice in {"chrome", "msedge"}:
                launch_args["channel"] = browser_choice
            try:
                context = await browser_type.launch_persistent_context(**launch_args)
            except Exception as exc:
                self.events.put(("error", f"浏览器启动失败：{exc}"))
                return

            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(self.settings.product_url)
            self.events.put(("browser_opened", "浏览器已打开。请登录并切到主语言国家的 PPO 测试方案页面，然后回到工具点击“页面已准备好，开始监听”。"))

            while not self.ready_event.is_set() and not self.stop_event.is_set():
                await asyncio.sleep(0.2)

            uploaded = False
            while not self.stop_event.is_set():
                self.next_refresh_at = time.time() + self.settings.refresh_seconds
                try:
                    if uploaded:
                        self.events.put(("log", "刷新网页，准备执行本轮监听。"))
                        await page.reload(wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)

                    if not uploaded:
                        uploaded = await self.upload_video(page)
                        if uploaded:
                            self.events.put(("uploaded", self.video_path))
                            await page.wait_for_timeout(2500)

                    result = await self.detect_first_media(page)
                    self.events.put(("detect_debug", result))
                    self.events.put(("phase", result))

                    if uploaded and result.get("phase") == "no_video":
                        uploaded = False
                        self.events.put(("log", "检测到后台已经没有 App 预览视频，可能已被手动删除；下一轮将重新上传。"))
                        await page.wait_for_timeout(1000)
                        continue

                    if uploaded and result.get("phase") == "ready" and self.settings.auto_cycle:
                        removed = await self.remove_remote_video(page)
                        self.events.put(("removed", removed))
                        if removed.get("ok"):
                            uploaded = False
                            await page.wait_for_timeout(2500)
                except Exception as exc:
                    self.events.put(("log", f"自动流程失败：{exc}"))

                for _ in range(self.settings.refresh_seconds * 10):
                    if self.stop_event.is_set():
                        break
                    await asyncio.sleep(0.1)

            await context.close()

    async def upload_video(self, page) -> bool:
        video_path = self.video_path
        if not video_path or not Path(video_path).exists():
            self.events.put(("log", f"当前选择的视频不存在：{video_path}"))
            return False
        try:
            await page.wait_for_timeout(1500)
            text_button = page.get_by_text("选择文件", exact=True)
            text_count = await text_button.count()
            if text_count:
                index = min(self.settings.plan_index, text_count - 1)
                async with page.expect_file_chooser(timeout=8000) as chooser_info:
                    await text_button.nth(index).click()
                chooser = await chooser_info.value
                await chooser.set_files(video_path)
                self.events.put(("log", f"已点击第 {index + 1} 个“选择文件”按钮，并把视频交给 ASC 文件选择器。"))
                return True
        except Exception as exc:
            self.events.put(("log", f"直接点击“选择文件”失败，尝试 DOM 定位：{exc}"))

        try:
            async with page.expect_file_chooser(timeout=8000) as chooser_info:
                result = await page.evaluate(CLICK_UPLOAD_BUTTON_SCRIPT, {
                    "planIndex": self.settings.plan_index,
                    "planSelector": self.settings.plan_selector,
                    "uploadButtonSelector": self.settings.upload_button_selector,
                })
                if not result.get("ok"):
                    self.events.put(("log", f"点击网页选择文件按钮失败：{result.get('message')}"))
                    raise RuntimeError(result.get("message"))
            chooser = await chooser_info.value
            await chooser.set_files(video_path)
            self.events.put(("log", "已点击网页“选择文件”按钮，并把视频交给 ASC 文件选择器。"))
            return True
        except Exception as exc:
            self.events.put(("log", f"网页按钮上传失败，尝试备用 input 上传：{exc}"))

        selector = self.settings.upload_selector or "input[type=file]"
        locator = page.locator(selector)
        count = await locator.count()
        if count == 0:
            self.events.put(("log", f"没有找到备用上传控件：{selector}。如果页面还没登录或未进入测试方案页，请先手动切过去。"))
            return False
        index = min(self.settings.plan_index, count - 1)
        await locator.nth(index).set_input_files(video_path)
        self.events.put(("log", f"已通过备用 input 上传：{selector}"))
        return True

    async def detect_first_media(self, page) -> dict:
        return await page.evaluate(FIRST_MEDIA_STATUS_SCRIPT, {
            "planIndex": self.settings.plan_index,
            "planSelector": self.settings.plan_selector,
            "mediaSelector": self.settings.media_selector,
            "placeholderSelector": self.settings.placeholder_selector,
            "previewSelector": self.settings.preview_selector,
        })

    async def remove_remote_video(self, page) -> dict:
        result = await page.evaluate(REMOVE_FIRST_MEDIA_SCRIPT, {
            "planIndex": self.settings.plan_index,
            "planSelector": self.settings.plan_selector,
            "mediaSelector": self.settings.media_selector,
            "removeSelector": self.settings.remove_selector,
            "confirmSelector": self.settings.confirm_selector,
        })
        if result.get("ok"):
            return result

        if self.settings.browser_channel not in {"chrome", "msedge", "chromium"}:
            result["message"] = f"{result.get('message')}；当前浏览器不支持 CDP 后台鼠标事件，已避免移动系统鼠标"
            return result

        status = await self.detect_first_media(page)
        rect = status.get("rect") or {}
        if not rect:
            return result

        try:
            session = await page.context.new_cdp_session(page)
            x = float(rect.get("x", 0)) + 12
            y = float(rect.get("y", 0)) + 12
            await session.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
                "buttons": 0,
            })
            await page.wait_for_timeout(700)
            result = await page.evaluate(REMOVE_FIRST_MEDIA_SCRIPT, {
                "planIndex": self.settings.plan_index,
                "planSelector": self.settings.plan_selector,
                "mediaSelector": self.settings.media_selector,
                "removeSelector": self.settings.remove_selector,
                "confirmSelector": self.settings.confirm_selector,
            })
            if result.get("ok"):
                result["message"] = f"CDP 后台悬停后移除成功：{result.get('message')}"
        except Exception as exc:
            result["message"] = f"{result.get('message')}；CDP 后台悬停失败：{exc}"

        return result

    def drain_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self.log(str(payload))
            elif event == "browser_opened":
                self.status_var.set("等待页面确认")
                self.phase_var.set("请在网页操作完成后点击确认按钮")
                self.notice_var.set("浏览器已打开：请登录并进入 PPO 测试方案页面")
                self.ready_btn.configure(state="normal")
                self.log(str(payload))
            elif event == "error":
                self.status_var.set("异常")
                self.log(str(payload))
                messagebox.showerror(APP_NAME, str(payload))
                self.stop()
            elif event == "uploaded":
                self.cycle_count += 1
                self.cycle_var.set(str(self.cycle_count))
                self.last_phase = "idle"
                self.placeholder_at = 0
                self.status_var.set("已上传")
                self.phase_var.set(f"第 {self.cycle_count} 轮：等待灰色占位图")
                self.notice_var.set(f"第 {self.cycle_count} 轮已上传，等待灰色占位图")
                self.log(f"第 {self.cycle_count} 轮已上传同一个视频：{payload}")
            elif event == "phase":
                self.handle_phase(payload)
            elif event == "detect_debug":
                self.log(
                    "识别结果："
                    f"phase={payload.get('phase')}，"
                    f"reason={payload.get('reason') or '-'}，"
                    f"planCount={payload.get('planCount')}，"
                    f"appPreviewCount={payload.get('appPreviewCount')}，"
                    f"chooseFileCount={payload.get('chooseFileCount')}，"
                    f"previewCounterCount={payload.get('previewCounterCount')}，"
                    f"testPlanTextCount={payload.get('testPlanTextCount')}"
                )
            elif event == "removed":
                if payload.get("ok"):
                    self.status_var.set("已移除")
                    self.phase_var.set("已移除后台视频，准备重传")
                    self.notice_var.set("已移除后台第一位视频，准备重传")
                    self.log(f"已移除后台第一位视频：{payload.get('message')}")
                else:
                    self.notice_var.set(f"移除后台视频失败：{payload.get('message')}")
                    self.log(f"移除后台视频失败：{payload.get('message')}")

        self.root.after(200, self.drain_events)

    def handle_phase(self, result: dict) -> None:
        phase = result.get("phase")
        if phase == "placeholder" and self.last_phase != "placeholder":
            self.placeholder_at = time.time()
            self.last_phase = "placeholder"
            self.status_var.set("灰色占位图")
            self.phase_var.set("第一位媒体是灰色占位图")
            self.notify("检测到灰色占位图", "第一位视频正在处理，已开始记录占位阶段。", "placeholder")
        elif phase == "ready" and self.last_phase != "ready":
            self.last_phase = "ready"
            self.status_var.set("可预览")
            self.phase_var.set("第一位媒体已出现视频预览图")
            total = fmt_duration(time.time() - self.started_at)
            stage = fmt_duration(time.time() - self.placeholder_at) if self.placeholder_at else "--"
            self.notify("视频预览图已出现", f"总耗时 {total}，占位图阶段 {stage}。即将移除后台视频并重传。", "ready")
        elif phase == "no_video":
            self.last_phase = "idle"
            self.status_var.set("未检测到视频")
            self.phase_var.set("后台没有 App 预览视频，准备重新上传")
            self.notice_var.set("未检测到视频：下一轮会重新上传当前选择的视频")
        elif phase == "waiting" and self.last_phase == "idle":
            self.phase_var.set(result.get("reason") or "等待第一位媒体变化")

    def update_clock(self) -> None:
        if self.running:
            self.elapsed_var.set(fmt_duration(time.time() - self.started_at))
            remaining = max(0, int(self.next_refresh_at - time.time()))
            self.next_refresh_var.set(f"{remaining} 秒")
        self.root.after(300, self.update_clock)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    WatcherApp().run()


if __name__ == "__main__":
    main()
