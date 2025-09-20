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

def start_service():
    """启动服务"""
    print("[*] 启动Boss直聘后台服务...")
    
    # 安装依赖
    if not install_dependencies():
        return False
    
    # 启动服务
    try:
        env = os.environ.copy()
        host = env.get('BOSS_SERVICE_HOST', '127.0.0.1')
        port = env.get('BOSS_SERVICE_PORT', '5001')
        # 启动前释放端口
        free_port(port)
        # 确保不存在残留的 uvicorn 进程（例如上一次reloader未退出干净）
        try:
            subprocess.run(["pkill", "-f", "uvicorn.*boss_service:app"], check=False)
            time.sleep(0.5)
        except Exception:
            pass

        # 使用 uvicorn 以可导入字符串方式启动，限定 reload 监听路径（相对路径），排除启动脚本
        # 注意：uvicorn 要求 --reload-dir 与 --reload-exclude 为相对路径
        src_dir_rel = "src"
        root_dir_rel = "."
        start_file_rel = "start_service.py"
        cmd = [
            sys.executable, "-m", "uvicorn",
            "boss_service:app",
            "--host", host,
            "--port", port,
            "--log-level", "info",
            "--reload",
            "--reload-dir", src_dir_rel,
            "--reload-dir", root_dir_rel,
            "--reload-exclude", start_file_rel,
            "--reload-delay", "0.3",
        ]
        # 新建进程组，以便整体发送信号
        process = subprocess.Popen(cmd, env=env, preexec_fn=os.setsid)
        
        def signal_handler(sig, frame):
            print("\n[*] 正在停止服务...")
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except Exception:
                pass
                process.wait(timeout=1)
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    pass
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
