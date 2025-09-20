#!/usr/bin/env python3
"""
改进的登录检测脚本 - 参考get_jobs项目的登录逻辑
"""
from playwright.sync_api import sync_playwright
import sys
import os
import time
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import settings

def wait_for_login_success(page, max_wait_time=300):
    """等待登录成功，参考get_jobs项目的逻辑"""
    print("[*] 开始等待登录成功...")
    print(f"[*] 最大等待时间: {max_wait_time} 秒")
    
    start_time = time.time()
    login_success = False
    
    while time.time() - start_time < max_wait_time:
        try:
            current_url = page.url
            current_title = page.title()
            
            print(f"[*] 当前URL: {current_url}")
            print(f"[*] 页面标题: {current_title}")
            
            # 检查是否在登录页面
            if "login" in current_url or "signin" in current_url:
                print("[*] 当前在登录页面，请完成登录...")
                time.sleep(3)
                continue
            
            # 检查是否跳转到首页或其他页面
            if current_url == settings.BASE_URL or current_url == settings.BASE_URL + "/":
                print("[*] 已跳转到首页，检查登录状态...")
                
                # 尝试访问需要登录的页面
                try:
                    page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded", timeout=10000)
                    time.sleep(3)
                    
                    # 检查页面内容
                    page_text = page.locator("body").inner_text()
                    print(f"[*] 消息页面内容长度: {len(page_text)} 字符")
                    
                    # 检查是否有登录按钮（如果有说明未登录）
                    if "登录" in page_text and "立即登录" in page_text:
                        print("[*] 页面仍显示登录按钮，返回首页重新登录...")
                        page.goto(settings.BASE_URL, wait_until="load")
                        time.sleep(3)
                        continue
                    
                    # 检查是否有用户相关元素
                    user_indicators = ["我的", "个人中心", "企业中心", "招聘管理", "消息", "沟通"]
                    for indicator in user_indicators:
                        if indicator in page_text:
                            print(f"[+] 发现用户元素: {indicator}")
                            login_success = True
                            break
                    
                    if login_success:
                        break
                    
                    # 检查是否有候选人相关内容
                    candidate_indicators = ["候选人", "简历", "打招呼", "投递", "面试", "聊天"]
                    for indicator in candidate_indicators:
                        if indicator in page_text:
                            print(f"[+] 发现候选人相关内容: {indicator}")
                            login_success = True
                            break
                    
                    if login_success:
                        break
                    
                    # 如果页面内容足够丰富，可能已登录
                    if len(page_text) > 100:
                        print("[*] 页面内容丰富，可能已登录")
                        login_success = True
                        break
                    
                    print("[*] 页面内容较少，可能未完全登录，继续等待...")
                    
                except Exception as e:
                    print(f"[*] 访问消息页面失败: {e}")
                    page.goto(settings.BASE_URL, wait_until="load")
                    time.sleep(3)
                    continue
            
            # 检查是否有验证码
            if check_captcha(page):
                print("[!] 检测到验证码，请手动处理...")
                input("处理完验证码后按回车继续...")
            
            time.sleep(3)
            
        except Exception as e:
            print(f"[!] 等待登录时出错: {e}")
            time.sleep(5)
    
    return login_success

def check_captcha(page):
    """检查是否有验证码"""
    try:
        captcha_selectors = [
            "iframe[src*='geetest']",
            "iframe[src*='captcha']", 
            "iframe[id*='captcha']",
            ".captcha",
            "[class*='captcha']"
        ]
        
        for selector in captcha_selectors:
            if page.locator(selector).count() > 0:
                return True
        return False
    except:
        return False

def wait_for_chat_page_ready(page, max_wait_time=60):
    """等待聊天页面完全加载"""
    print("[*] 等待聊天页面完全加载...")
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        try:
            # 检查页面是否完全加载
            page_text = page.locator("body").inner_text()
            
            # 检查是否有加载中的提示
            if "加载中" in page_text or "请稍候" in page_text:
                print("[*] 页面仍在加载中...")
                time.sleep(2)
                continue
            
            # 检查是否有错误信息
            if "错误" in page_text or "404" in page_text:
                print("[!] 页面显示错误信息")
                return False
            
            # 检查是否有候选人相关内容
            if any(keyword in page_text for keyword in ["候选人", "简历", "打招呼", "投递", "面试", "聊天", "消息"]):
                print("[+] 聊天页面加载完成")
                return True
            
            # 检查是否有"无数据"提示
            if "暂无" in page_text or "无数据" in page_text:
                print("[*] 页面显示暂无数据")
                return True
            
            print("[*] 等待页面内容加载...")
            time.sleep(2)
            
        except Exception as e:
            print(f"[!] 检查页面状态时出错: {e}")
            time.sleep(2)
    
    print("[!] 等待聊天页面加载超时")
    return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=1000)
        context = browser.new_context()
        page = context.new_page()
        
        print("[*] 启动改进的登录检测...")
        print("[*] 浏览器将保持打开，请完成登录操作")
        
        # 访问首页
        print(f"[*] 访问首页: {settings.BASE_URL}")
        page.goto(settings.BASE_URL, wait_until="load")
        
        # 等待登录成功
        if wait_for_login_success(page, max_wait_time=600):  # 最多等待10分钟
            print("\n[+] 登录成功！")
            
            # 确保在聊天页面
            print("[*] 确保在聊天页面...")
            page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded")
            
            # 等待聊天页面完全加载
            if wait_for_chat_page_ready(page, max_wait_time=60):
                print("[+] 聊天页面加载完成")
                
                # 保存登录状态
                context.storage_state(path=settings.STORAGE_STATE)
                print(f"[+] 已保存登录状态到 {settings.STORAGE_STATE}")
                
                print("\n[+] 登录完成！现在可以运行候选人读取脚本了")
                print("[*] 运行命令: python src/read_candidates.py --limit 10")
            else:
                print("[!] 聊天页面加载失败")
        else:
            print("\n[!] 登录失败或超时")
            print("[*] 请检查网络连接和登录状态")
        
        print("\n[*] 浏览器将在30秒后关闭...")
        time.sleep(30)
        browser.close()

if __name__ == "__main__":
    main()
