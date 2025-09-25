#!/usr/bin/env python3
"""
启动Boss直聘后台服务
"""
import subprocess
import sys
import os
import time
import signal
import socket

def install_dependencies():
    """安装依赖"""
    print("[*] 检查并安装依赖...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("[+] 依赖安装完成")
    except subprocess.CalledProcessError as e:
        print(f"[!] 依赖安装失败: {e}")
        return False
    return True

def free_port(port: str):
    """在macOS上释放占用端口的进程(lsof -ti :port; kill pid)。"""
    try:
        pids = subprocess.check_output(["lsof", "-ti", f":{port}"]).decode().strip().splitlines()
        print(f'found pids: {pids}')
        for pid in pids:
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
        print(f'released port: {port}')
    except Exception:
        pass

def is_chrome_running(cdp_port: str) -> bool:
    """检查Chrome是否已经在运行"""
    try:
        import requests
        response = requests.get(f"http://localhost:{cdp_port}/json/version", timeout=2)
        return response.status_code == 200
    except Exception:
        return False

def kill_existing_chrome(user_data: str):
    """杀死现有的Chrome进程（基于user-data-dir）"""
    try:
        # 查找使用相同user-data-dir的Chrome进程
        result = subprocess.run(
            ["pgrep", "-f", f"--user-data-dir={user_data}"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        time.sleep(0.5)
                        os.kill(int(pid), signal.SIGKILL)
                    except Exception:
                        pass
            print(f"[*] 已清理现有Chrome进程")
    except Exception:
        pass

def start_service():
    """启动服务"""
    print("[*] 启动Boss直聘后台服务...")
    
    # 安装依赖
    # if not install_dependencies():
    #     return False
    
    # 启动服务
    try:
        env = os.environ.copy()
        host = env.get('BOSS_SERVICE_HOST', '127.0.0.1')
        port = env.get('BOSS_SERVICE_PORT', '5001')
        cdp_port = env.get('CDP_PORT', '9222')
        user_data = env.get('BOSSZP_USER_DATA', '/tmp/bosszhipin_profile')
        # 启动前释放端口
        free_port(port)
        # 确保不存在残留的 uvicorn 进程（例如上一次reloader未退出干净）
        try:
            subprocess.run(["pkill", "-f", "uvicorn.*boss_service:app"], check=False)
            time.sleep(0.5)
        except Exception:
            pass

        # 检查Chrome是否已经在运行
        if is_chrome_running(cdp_port):
            print(f"[*] Chrome已在端口 {cdp_port} 运行，跳过启动")
        else:
            print(f"[*] 启动Chrome (CDP端口: {cdp_port})...")
            # 清理可能存在的旧Chrome进程
            kill_existing_chrome(user_data)
            
            # 启动独立的 Chrome (CDP)，确保浏览器长驻，与 API 进程解耦
            chrome_cmd = [
                "google-chrome" if sys.platform != "darwin" else \
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--no-sandbox",
                "--window-size=1200,800",
                # 限制Chrome只处理特定URL，避免干扰正常浏览
                "--restrict-http-scheme",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                # 设置默认页面为空白页，避免自动打开其他页面
                "--new-window",
                "about:blank"
            ]
            try:
                subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                time.sleep(2.0)  # 增加等待时间确保Chrome完全启动
                print(f"[+] Chrome启动完成")
            except Exception as e:
                print(f"[!] Chrome启动失败: {e}")
                return False

        # 使用 uvicorn 启动（可开启 --reload；CDP模式下重载不会中断浏览器）
        # 只监控与 boss_service 相关的核心文件，排除不必要的文件
        cmd = [
            sys.executable, "-m", "uvicorn",
            "boss_service:app",
            "--host", host,
            "--port", port,
            "--log-level", "info",
            "--reload",
            "--reload-include", "boss_service.py",
            "--reload-dir", "src/",
            '--reload-delay', '5.0'
        ]
        # 新建进程组，以便整体发送信号
        process = subprocess.Popen(cmd, env=env, preexec_fn=os.setsid)
        
        def signal_handler(sig, frame):
            print("\n[*] 正在停止服务...")
            try:
                # 停止uvicorn进程
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    pass
            
            # 可选：清理Chrome进程（通常保留以便下次使用）
            cleanup_chrome = os.environ.get('CLEANUP_CHROME_ON_EXIT', 'false').lower() == 'true'
            if cleanup_chrome:
                print("[*] 清理Chrome进程...")
                kill_existing_chrome(user_data)
            
            print("[+] 服务已停止")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        print("[+] 服务启动成功!")
        print(f"[*] 服务地址: http://{host}:{port}")
        print("[*] 按 Ctrl+C 停止服务")
        
        # 等待进程结束
        process.wait()
        
    except KeyboardInterrupt:
        print("\n[*] 正在停止服务...")
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            process.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass
        print("[+] 服务已停止")
    except Exception as e:
        print(f"[!] 启动服务失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    start_service()
