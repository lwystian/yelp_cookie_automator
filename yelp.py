import os
import time
import random
import string
import psutil
import threading
import configparser
import tkinter as tk
import subprocess
from tkinter import messagebox, filedialog
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class AppState:
    def __init__(self):
        self.is_running = False
        self.stop_event = threading.Event()
        self.active_drivers = []
        self.lock = threading.Lock()

    def add_driver(self, driver):
        with self.lock:
            self.active_drivers.append(driver)

    def remove_driver(self, driver):
        with self.lock:
            try:
                self.active_drivers.remove(driver)
            except ValueError:
                pass

    def cleanup_drivers(self):
        with self.lock:
            for driver in self.active_drivers[:]:
                try:
                    # 先尝试正常退出
                    driver.quit()
                except:
                    pass

                try:
                    # 强制终止相关进程
                    if hasattr(driver, 'service') and driver.service.process:
                        driver.service.process.terminate()
                except:
                    pass

                self.active_drivers.remove(driver)

            # 额外清理可能残留的chrome进程
            self.kill_chrome_processes()

    def kill_chrome_processes(self):
        """强制终止所有Chrome相关进程"""
        try:
            for proc in psutil.process_iter():
                try:
                    # 更标准的方式获取进程名
                    name = proc.name().lower()
                    if 'chrome' in name:
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except ImportError:
            # 回退方案：使用系统命令
            try:
                if os.name == 'nt':  # Windows
                    subprocess.run(['taskkill', '/f', '/im', 'chrome.exe'],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(['pkill', '-f', 'chrome'],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            except:
                pass

app_state = AppState()

def generate_random_zipcode():
    return ''.join([random.choice(string.digits) for _ in range(5)])

def get_zss_cookie(driver):
    cookies = driver.get_cookies()
    for cookie in cookies:
        if cookie['name'] == 'zss':
            return f"zss={cookie['value']};"
    return None

def random_delay(min_delay=0.5, max_delay=1):
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)

def smart_wait(driver, selectors, timeout=15, required=2):
    """等待至少N个选择器对应的元素出现"""
    start = time.time()
    found = set()

    while time.time() - start < timeout:
        if app_state.stop_event.is_set():
            raise Exception("操作被中止")

        for selector in selectors:
            try:
                if selector not in found and driver.find_element(By.CSS_SELECTOR, selector):
                    found.add(selector)
                    if len(found) >= required:
                        return True
            except:
                pass
        time.sleep(0.1)
    return False

def yelp_register(first_name, last_name, email, zip_code, password, log_text, debug_mode=False):
    """优化后的注册函数，通过API响应判断注册结果"""

    def log(message):
        log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        log_text.see(tk.END)

    options = webdriver.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheet": 2,
        "profile.managed_default_content_settings.javascript": 1,
        "profile.managed_default_content_settings.media_stream": 2,
    })
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-web-security")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-extensions")
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument("--window-size=800,600")

    if not debug_mode:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        app_state.add_driver(driver)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(0.5)  # 减少隐式等待时间

        log("🌐 正在加载注册页面...")

        # 使用JavaScript直接导航，不等待页面完全加载
        driver.execute_script("window.location.href = 'https://www.yelp.com/signup'")

        # 准备填写数据
        fields_to_fill = [
            ("first_name", first_name),
            ("last_name", last_name),
            ("email", email),
            ("password", password),
            ("zip_code", zip_code)
        ]

        # 立即开始渐进式填写
        progressive_field_filling(driver, fields_to_fill, log_text)

        # 提交表单前启用网络监控
        log("🔄 正在提交注册表单...")
        driver.execute_script("""
            window._registrationResponse = null;
            const originalOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function() {
                if (arguments[1] === '/signup') {
                    this.addEventListener('load', function() {
                        if (this.responseText) {
                            try {
                                window._registrationResponse = JSON.parse(this.responseText);
                            } catch (e) {}
                        }
                    });
                }
                originalOpen.apply(this, arguments);
            };
        """)

        # 等待提交按钮可点击
        submit_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#signup-button.ybtn--primary")))
        driver.execute_script("arguments[0].click();", submit_button)

        # 等待响应
        response = None
        start_time = time.time()
        while time.time() - start_time < 15:
            if app_state.stop_event.is_set():
                raise Exception("操作被中止")

            response = driver.execute_script("return window._registrationResponse;")
            if response:
                break
            time.sleep(0.5)
        else:
            raise Exception("未能获取注册响应")

        # 解析响应
        if not response:
            raise Exception("无有效响应数据")

        if response.get("success"):
            zss_cookie = None
            for _ in range(5):
                zss_cookie = get_zss_cookie(driver)
                if zss_cookie:
                    break
                time.sleep(1)
            else:
                raise Exception("未能获取zss cookie")

            log(f"✅ 注册成功！Cookie: {zss_cookie[:30]}...")

            with open("yelp_cookies.txt", "a") as f:
                f.write(zss_cookie + "\n")

            return True
        else:
            errors = response.get("errors", [])
            if errors:
                error_msg = " | ".join(errors)
                if "human" in error_msg.lower() or "bot" in error_msg.lower():
                    raise Exception("触发人机验证,请更换IP")
                elif "eligible" in error_msg.lower():
                    raise Exception("账号不符合注册资格,请更换IP")
                else:
                    raise Exception(error_msg)
            else:
                raise Exception("未知注册错误")

    except Exception as e:
        error_msg = str(e)
        if "human" in error_msg.lower() or "bot" in error_msg.lower():
            log("❌ 注册失败: 触发人机验证,请更换IP")
        elif "eligible" in error_msg.lower():
            log("❌ 注册失败: 账号不符合注册资格,请更换IP")
        elif "timeout" in error_msg.lower():
            log("⏳ 操作超时，可能网络不稳定")
        else:
            log(f"❌ 注册失败: {error_msg.splitlines()[0]}")
        return False
    finally:
        if driver:
            try:
                # 确保关闭所有窗口
                for handle in driver.window_handles:
                    driver.switch_to.window(handle)
                    driver.close()
                driver.quit()
            except:
                pass
            finally:
                app_state.remove_driver(driver)
                app_state.kill_chrome_processes()
def progressive_field_filling(driver, fields_to_fill, log_text):
    """改进版渐进式字段填写，立即开始填写已加载的字段"""

    def log(message):
        log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        log_text.see(tk.END)

    # 定义字段优先级和选择器映射
    field_selectors = {
        'first_name': '#first_name',
        'last_name': '#last_name',
        'email': '#email',
        'password': 'input[type="password"][name="password"]',
        'zip_code': 'input[name="zip"], input[placeholder*="ZIP"]'
    }

    # 记录已填写的字段
    filled_fields = set()

    # 最大等待时间（秒）
    max_wait_time = 15
    start_time = time.time()

    while len(filled_fields) < len(fields_to_fill) and time.time() - start_time < max_wait_time:
        if app_state.stop_event.is_set():
            raise Exception("操作被中止")

        for field_id, value in fields_to_fill:
            if field_id in filled_fields:
                continue

            selector = field_selectors.get(field_id)
            if not selector:
                continue
            try:
                # 尝试立即查找元素，不等待
                elem = driver.find_element(By.CSS_SELECTOR, selector)

                # 清除现有内容
                elem.clear()
                time.sleep(0.2)
                if elem.get_attribute('value'):
                    driver.execute_script("arguments[0].value = '';", elem)
                    time.sleep(0.2)

                # 模拟人工输入
                for char in value:
                    if app_state.stop_event.is_set():
                        raise Exception("操作被中止")
                    elem.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))

                filled_fields.add(field_id)
                # log(f"✓ 已填写 {field_id}")

            except Exception:
                # 元素尚未加载，继续尝试其他字段
                pass

        # 短暂暂停后重试
        time.sleep(0.1)

    # 检查是否所有字段都已填写
    if len(filled_fields) < len(fields_to_fill):
        missing_fields = [f[0] for f in fields_to_fill if f[0] not in filled_fields]
        raise Exception(f"以下字段未能加载: {', '.join(missing_fields)}")

def start_registration_thread(total_accounts, accounts_per_ip, log_text, dial_enabled,dial_connection, dial_username, dial_password, root, debug_mode=False):
    """启动注册线程"""

    def log(message, with_time=True):
        if with_time:
            prefix = f"{time.strftime('%H:%M:%S')} - "
        else:
            prefix = ""
        log_text.insert(tk.END, f"{prefix}{message}\n")
        log_text.see(tk.END)

    class BatchTracker:
        def __init__(self):
            self.lock = threading.Lock()
            self.attempted = 0
            self.succeeded = 0
            self.current_batch = 1
            self.worker_counter = 0
            self.batch_success = {}
            self.batch_attempt = {}

    tracker = BatchTracker()

    def worker():
        with tracker.lock:
            worker_id = tracker.worker_counter + 1
            tracker.worker_counter += 1

        while True:
            if app_state.stop_event.is_set():
                return

            # 获取当前批次
            with tracker.lock:
                if tracker.attempted >= total_accounts:
                    return
                batch_num = (tracker.attempted // accounts_per_ip) + 1

                # 新批次开始
                if batch_num > tracker.current_batch:
                    return

                    # 初始化批次计数器
                if batch_num not in tracker.batch_attempt:
                    tracker.batch_attempt[batch_num] = 0
                    tracker.batch_success[batch_num] = 0

                tracker.attempted += 1
                tracker.batch_attempt[batch_num] += 1

            try:
                # 生成账号信息
                first_name = ''.join(random.sample(string.ascii_lowercase, 4)) + str(random.randint(100, 999))
                last_name = ''.join(random.sample(string.ascii_lowercase, 4)) + str(random.randint(100, 999))
                email = f"{first_name}.{last_name}{random.randint(100, 999)}@gmail.com"
                zip_code = generate_random_zipcode()
                password = ''.join([random.choice(string.ascii_letters + string.digits + "!@#$%") for _ in range(10)])

                log(f"[批次{batch_num}][账号{worker_id}] 开始注册", with_time=True)

                # 执行注册
                success = yelp_register(first_name, last_name, email, zip_code, password, log_text, debug_mode=debug_mode)

                if success:
                    with tracker.lock:
                        tracker.succeeded += 1
                        tracker.batch_success[batch_num] += 1

            except Exception as e:
                log(f"⚠️ 线程{worker_id}异常: {str(e)}")

    def batch_controller():
        for batch in range(1, (total_accounts + accounts_per_ip - 1) // accounts_per_ip + 1):
            # 检查是否已停止
            if app_state.stop_event.is_set():
                break

            # 打印批次头
            log("=========================================================", with_time=False)
            log(f"批次 {batch}/{(total_accounts + accounts_per_ip - 1) // accounts_per_ip}")

            # 启动线程
            threads = []
            for _ in range(min(accounts_per_ip, total_accounts - (batch - 1) * accounts_per_ip)):
                if app_state.stop_event.is_set():
                    break
                t = threading.Thread(target=worker, daemon=True)
                t.start()
                threads.append(t)

            # 等待本批次完成
            for t in threads:
                if app_state.stop_event.is_set():
                    break
                t.join()

            # 检查是否已停止
            if app_state.stop_event.is_set():
                break

            # 打印批次统计
            with tracker.lock:
                batch_success = tracker.batch_success.get(batch, 0)
                batch_attempt = tracker.batch_attempt.get(batch, 0)
                remaining = max(0, total_accounts - tracker.attempted)

                log(f"▪ 成功: {batch_success}/{batch_attempt}")
                log(f"▪ 剩余: {remaining}")

            # 拨号换IP - 只有在未停止且还有剩余时才执行
            if not app_state.stop_event.is_set() and dial_enabled and remaining > 0:
                log("=========================================================", with_time=False)
                log("🔄 正在更换IP...")
                if dial_ip(dial_connection.get(), dial_username.get(), dial_password.get(), log_text):
                    log("✅ IP更换完成")
                else:
                    app_state.stop_event.set()
                    break

            tracker.current_batch += 1

    def run():
        try:
            # 初始拨号
            if dial_enabled:
                log("=========================================================", with_time=False)
                log("🔄 正在初始化拨号...")
                if dial_ip(dial_connection.get(), dial_username.get(), dial_password.get(), log_text):
                    log("✅ 拨号成功")
                else:
                    return

            batch_controller()

            # 最终统计
            log("=========================================================", with_time=False)
            log("任务完成")
            log(f"▪ 总尝试: {tracker.attempted}")
            log(f"▪ 成功注册: {tracker.succeeded}")
            log(f"▪ 成功率: {tracker.succeeded / max(1, tracker.attempted) * 100:.1f}%")
            log("=========================================================", with_time=False)

        except Exception as e:
            log(f"❌ 系统异常: {str(e)}")
        finally:
            app_state.is_running = False
            app_state.stop_event.set()
            root.event_generate('<<TaskComplete>>')

    # 初始化计数器
    tracker = BatchTracker()
    app_state.is_running = True
    app_state.stop_event.clear()
    threading.Thread(target=run, daemon=True).start()

def get_available_connections():
    """获取系统中已配置的宽带连接"""
    try:
        result = subprocess.run(
            ["rasdial"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            # 解析输出，获取所有已配置的连接
            lines = result.stdout.splitlines()
            connections = []
            for line in lines:
                if "已连接" in line or "Connected" in line:
                    parts = line.split()
                    if parts:
                        connections.append(parts[0])
            return connections
    except Exception:
        pass
    return []


def dial_ip(connection_name, username, password, log_text):
    """使用rasdial进行拨号换IP（完整改进版）"""

    def log(message):
        log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        log_text.see(tk.END)

    try:
        # 1. 清理所有浏览器实例
        log("🔄 准备拨号 - 正在清理浏览器实例...")
        app_state.cleanup_drivers()
        time.sleep(2)  # 确保所有浏览器实例已关闭

        # 2. 断开现有连接
        log("⏳ 正在断开当前网络连接...")
        disconnect_process = subprocess.run(
            ["rasdial", connection_name, "/DISCONNECT"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=20
        )

        # 检查断开结果
        if disconnect_process.returncode != 0 and "没有连接" not in disconnect_process.stdout:
            log(f"⚠️ 断开连接时出现异常: {disconnect_process.stderr[:200]}...")
            return False

        time.sleep(5)  # 确保完全断开

        # 3. 建立新连接
        log(f"⏳ 正在使用账号 {username} 建立新连接...")
        connect_process = subprocess.run(
            ["rasdial", connection_name, username, password],
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )

        # 4. 验证连接结果
        if connect_process.returncode == 0:
            log("✅ 网络连接成功！等待网络稳定...")
            time.sleep(8)  # 重要：等待网络完全稳定
            return True

        # 错误处理
        error_msg = connect_process.stdout + connect_process.stderr
        if "already connected" in error_msg.lower():
            log("⚠️ 已存在有效连接，继续使用当前IP")
            return True

        log(f"❌ 连接失败: {error_msg[:200]}...")
        return False

    except subprocess.TimeoutExpired:
        log("⌛ 操作超时！可能原因：\n1. 请以管理员身份运行\n2. 检查宽带名称\n3. 确认物理连接正常")
        return False
    except Exception as e:
        log(f"❌ 发生未知错误: {str(e)}")
        return False


def test_dial(connection_name, username, password, log_text):
    """测试拨号连接"""

    def log(message):
        log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        log_text.see(tk.END)

    log("🔍 开始测试拨号连接...")
    try:
        # 先断开
        subprocess.run(["rasdial", connection_name, "/DISCONNECT"],shell=True, timeout=10)
        time.sleep(3)

        # 再连接
        result = subprocess.run(["rasdial", connection_name, username, password],shell=True, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            log("✅ 拨号测试成功！")
            return True
        else:
            log(f"❌ 拨号测试失败: {result.stderr[:200]}")
            return False
    except Exception as e:
        log(f"❌ 拨号测试异常: {str(e)}")
        return False

def export_zss_cookie(log_text):
    """导出zss cookie"""
    file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
    if file_path:
        try:
            # 读取原始数据
            with open("yelp_cookies.txt", "r") as f:
                raw_cookies = f.readlines()

            # 处理数据

            cleaned_cookies = []
            for cookie in raw_cookies:
                # 移除首尾空白和引号
                cleaned = cookie.strip().strip('"')
                if cleaned:
                    cleaned_cookies.append(cleaned)

            # 写入文件
            with open(file_path, "w") as f:
                f.write("\n".join(cleaned_cookies))

            log_text.insert(tk.END, f"✅ 成功导出{len(cleaned_cookies)}条Cookie到：{file_path}\n")
        except Exception as e:
            log_text.insert(tk.END, f"导出失败: {str(e)}\n")


# 配置文件路径
CONFIG_FILE = "settings.ini"

# 创建configparser对象
config = configparser.ConfigParser()

# 默认设置
DEFAULT_SETTINGS = {
    "dial_username": "",
    "dial_password": ""
}

# 加载配置文件
def load_settings():
    """加载配置文件"""
    try:
        config.read(CONFIG_FILE)
        # 如果配置文件存在，则加载其中的设置
        dial_username = config.get("Settings", "dial_username", fallback=DEFAULT_SETTINGS["dial_username"])
        dial_password = config.get("Settings", "dial_password", fallback=DEFAULT_SETTINGS["dial_password"])
    except Exception as e:
        # 如果读取配置文件出错，使用默认设置
        print(f"加载配置失败: {e}")
        dial_username, dial_password = DEFAULT_SETTINGS.values()

    return dial_username, dial_password

# 保存配置
def save_settings(dial_username, dial_password):
    """保存配置文件"""
    try:
        if not config.has_section("Settings"):
            config.add_section("Settings")
        config.set("Settings", "dial_username", dial_username)
        config.set("Settings", "dial_password", dial_password)

        with open(CONFIG_FILE, "w") as configfile:
            config.write(configfile)
    except Exception as e:
        print(f"保存配置失败: {e}")

def create_gui():
    root = tk.Tk()
    root.title("Yelp 注册自动化 v1.0")
    root.geometry("550x700")  # 稍微加大窗口以适应新控件

    # 加载保存的设置
    dial_username_val, dial_password_val = load_settings()

    # 输入区域框架
    input_frame = tk.LabelFrame(root, text="注册设置", padx=10, pady=10)
    input_frame.pack(pady=10, fill="x", padx=15)

    tk.Label(input_frame, text="总注册账号数:").grid(row=0, column=0, sticky="w")
    total_accounts = tk.Entry(input_frame, width=25)
    total_accounts.grid(row=0, column=1, pady=5)
    total_accounts.insert(0, "100")

    tk.Label(input_frame, text="每个IP注册数量(线程数):").grid(row=1, column=0, sticky="w")
    accounts_per_ip = tk.Entry(input_frame, width=25)
    accounts_per_ip.grid(row=1, column=1, pady=5)
    accounts_per_ip.insert(0, "5")

    # 拨号设置框架
    dial_frame = tk.LabelFrame(root, text="宽带拨号", padx=10, pady=10)
    dial_frame.pack(pady=10, fill="x", padx=15)

    # 拨号功能开关
    dial_enabled = tk.BooleanVar()
    tk.Checkbutton(dial_frame, text="启用宽带拨号", variable=dial_enabled).grid(row=0, column=0, columnspan=3, sticky="w")

    # 连接名称行
    tk.Label(dial_frame, text="连接名称:").grid(row=1, column=0, sticky="e", padx=(0, 5), pady=(0, 5))
    dial_connection = tk.Entry(dial_frame, width=25)
    dial_connection.grid(row=1, column=1, sticky="w")
    dial_connection.insert(0, "宽带连接")

    # 宽带账号行
    tk.Label(dial_frame, text="宽带账号:").grid(row=2, column=0, sticky="e", padx=(0, 5), pady=(0, 5))
    dial_username = tk.Entry(dial_frame, width=25)
    dial_username.grid(row=2, column=1, sticky="w")
    dial_username.insert(0, dial_username_val)

    # 宽带密码行
    tk.Label(dial_frame, text="宽带密码:").grid(row=3, column=0, sticky="e", padx=(0, 5), pady=(0, 5))
    dial_password = tk.Entry(dial_frame, width=25)
    dial_password.grid(row=3, column=1, sticky="w")
    dial_password.insert(0, dial_password_val)

    # 按钮列 - 放在第三列，垂直居中
    btn_frame = tk.Frame(dial_frame)
    btn_frame.grid(row=2, column=2, rowspan=3, sticky="ns", padx=(20, 0))

    # 拨号测试按钮
    def test_connection():
        conn = dial_connection.get()
        user = dial_username.get()
        pwd = dial_password.get()

        if not conn or not user or not pwd:
            messagebox.showerror("错误", "请填写完整的拨号信息")
            return

        if test_dial(conn, user, pwd, log_text):
            save_settings(user, pwd)
            messagebox.showinfo("成功", "拨号测试成功！配置已保存")
        else:
            messagebox.showerror("错误", "拨号测试失败，请检查配置")

    test_btn = tk.Button(btn_frame, text="拨号测试", command=test_connection)
    test_btn.pack(pady=(0, 10), fill="x")

    # 调试开关
    debug_frame = tk.Frame(input_frame)
    debug_frame.grid(row=5, column=0, columnspan=2, pady=5, sticky="w")

    debug_mode = tk.BooleanVar(value=False)  # 默认关闭调试模式
    tk.Checkbutton(debug_frame, text="调试模式(显示浏览器窗口)", variable=debug_mode).pack(side=tk.LEFT)

    # 日志区域
    log_frame = tk.LabelFrame(root, text="运行日志", padx=10, pady=10)
    log_frame.pack(pady=10, fill="both", expand=True, padx=15)

    log_text = tk.Text(log_frame, height=15, wrap=tk.WORD)
    scrollbar = tk.Scrollbar(log_frame, command=log_text.yview)
    log_text.configure(yscrollcommand=scrollbar.set)

    log_text.pack(side=tk.LEFT, fill="both", expand=True)
    scrollbar.pack(side=tk.RIGHT, fill="y")

    # 控制按钮区域
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)

    def start_task():
        if app_state.is_running:
            return

        try:
            accounts_per_ip_val = int(accounts_per_ip.get())
            total_accounts_val = int(total_accounts.get())
            dial_username_val = dial_username.get()
            dial_password_val = dial_password.get()

            # 保存配置文件
            save_settings(dial_username_val, dial_password_val)

        except ValueError:
            messagebox.showerror("输入错误", "请输入有效的数字")
            return

        app_state.is_running = True
        app_state.stop_event.clear()
        start_btn.config(state=tk.DISABLED)
        stop_btn.config(state=tk.NORMAL)

        start_registration_thread(
            total_accounts=total_accounts_val,
            accounts_per_ip=accounts_per_ip_val,
            log_text=log_text,
            dial_enabled=dial_enabled.get(),
            dial_connection=dial_connection,
            dial_username=dial_username,
            dial_password=dial_password,
            root=root,
            debug_mode=debug_mode.get()
        )

        def check_status():
            if app_state.is_running:
                root.after(500, check_status)
            else:
                start_btn.config(state=tk.NORMAL)
                stop_btn.config(state=tk.DISABLED)
                log_text.see(tk.END)

        check_status()

    def stop_task():
        app_state.stop_event.set()
        app_state.is_running = False
        log_text.insert(tk.END, "正在停止任务...\n")

    def on_closing():
        if messagebox.askokcancel("退出", "确认要退出程序吗？"):
            # 保存设置
            save_settings(dial_username.get(), dial_password.get())

            # 清理资源
            app_state.stop_event.set()
            app_state.cleanup_drivers()

            # 延迟退出确保清理完成
            threading.Thread(target=lambda: (time.sleep(1), root.destroy()), daemon=True).start()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    # 开始按钮
    start_btn = tk.Button(btn_frame, text="▶ 开始注册", width=15, command=start_task)
    start_btn.pack(side=tk.LEFT, padx=5)

    # 导出按钮
    export_btn = tk.Button(btn_frame, text="⏏ 导出Cookie", width=15, command=lambda: export_zss_cookie(log_text))
    export_btn.pack(side=tk.LEFT, padx=5)

    # 停止按钮
    stop_btn = tk.Button(btn_frame, text="⏹ 停止任务", width=15, command=stop_task, state=tk.DISABLED)
    stop_btn.pack(side=tk.LEFT, padx=5)

    root.mainloop()

if __name__ == "__main__":
    create_gui()