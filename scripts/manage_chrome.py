#!/usr/bin/env python3
"""
Chrome进程管理脚本
用于独立管理Boss直聘自动化系统的Chrome实例
"""
import subprocess
import sys
import os
import time
import signal
import requests
import argparse

def is_chrome_running(cdp_port: str) -> bool:
    """检查Chrome是否已经在运行"""
    try:
        response = requests.get(f"http://localhost:{cdp_port}/json/version", timeout=2)
        return response.status_code == 200
    except Exception:
        return False

def get_chrome_info(cdp_port: str):
    """获取Chrome实例信息"""
    try:
        response = requests.get(f"http://localhost:{cdp_port}/json/version", timeout=2)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def kill_chrome_by_user_data(user_data: str):
    """根据user-data-dir杀死Chrome进程"""
    try:
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
            return True
    except Exception:
        pass
    return False

def start_chrome(cdp_port: str, user_data: str):
    """启动Chrome实例"""
    if is_chrome_running(cdp_port):
        print(f"Chrome已在端口 {cdp_port} 运行")
        return True
    
    print(f"启动Chrome (端口: {cdp_port}, 用户数据: {user_data})...")
    
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
        "--restrict-http-scheme",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--new-window",
        "about:blank"
    ]
    
    try:
        subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        time.sleep(2.0)
        
        if is_chrome_running(cdp_port):
            print("✅ Chrome启动成功")
            return True
        else:
            print("❌ Chrome启动失败")
            return False
    except Exception as e:
        print(f"❌ Chrome启动异常: {e}")
        return False

def stop_chrome(cdp_port: str, user_data: str):
    """停止Chrome实例"""
    if not is_chrome_running(cdp_port):
        print(f"Chrome未在端口 {cdp_port} 运行")
        return True
    
    print(f"停止Chrome (端口: {cdp_port})...")
    
    if kill_chrome_by_user_data(user_data):
        time.sleep(1.0)
        if not is_chrome_running(cdp_port):
            print("✅ Chrome已停止")
            return True
        else:
            print("❌ Chrome停止失败")
            return False
    else:
        print("❌ 未找到Chrome进程")
        return False

def restart_chrome(cdp_port: str, user_data: str):
    """重启Chrome实例"""
    print("重启Chrome...")
    stop_chrome(cdp_port, user_data)
    time.sleep(1.0)
    return start_chrome(cdp_port, user_data)

def status_chrome(cdp_port: str):
    """显示Chrome状态"""
    if is_chrome_running(cdp_port):
        info = get_chrome_info(cdp_port)
        if info:
            print(f"✅ Chrome正在运行 (端口: {cdp_port})")
            print(f"   版本: {info.get('Browser', 'Unknown')}")
            print(f"   User-Agent: {info.get('User-Agent', 'Unknown')}")
            print(f"   WebKit版本: {info.get('WebKit-Version', 'Unknown')}")
        else:
            print(f"✅ Chrome正在运行 (端口: {cdp_port})")
    else:
        print(f"❌ Chrome未运行 (端口: {cdp_port})")

def main():
    parser = argparse.ArgumentParser(description="Chrome进程管理工具")
    parser.add_argument("action", choices=["start", "stop", "restart", "status"], help="操作类型")
    parser.add_argument("--port", default="9222", help="CDP端口 (默认: 9222)")
    parser.add_argument("--user-data", default="/tmp/bosszhipin_profile", help="用户数据目录")
    
    args = parser.parse_args()
    
    if args.action == "start":
        success = start_chrome(args.port, args.user_data)
        sys.exit(0 if success else 1)
    elif args.action == "stop":
        success = stop_chrome(args.port, args.user_data)
        sys.exit(0 if success else 1)
    elif args.action == "restart":
        success = restart_chrome(args.port, args.user_data)
        sys.exit(0 if success else 1)
    elif args.action == "status":
        status_chrome(args.port)
        sys.exit(0)

if __name__ == "__main__":
    main()
