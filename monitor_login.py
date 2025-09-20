#!/usr/bin/env python3
"""
持续监控登录状态和页面变化
"""
from playwright.sync_api import sync_playwright
import sys
import os
import time
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import settings

def monitor_page_changes(page, max_wait_time=300):
    """持续监控页面变化"""
    print("[*] 开始持续监控页面变化...")
    print(f"[*] 最大等待时间: {max_wait_time} 秒")
    
    start_time = time.time()
    last_url = ""
    last_title = ""
    last_content_length = 0
    
    while time.time() - start_time < max_wait_time:
        try:
            current_url = page.url
            current_title = page.title()
            
            # 获取页面内容长度作为变化指标
            try:
                page_text = page.locator("body").inner_text()
                current_content_length = len(page_text)
            except:
                current_content_length = 0
            
            # 检查是否有变化
            if (current_url != last_url or 
                current_title != last_title or 
                abs(current_content_length - last_content_length) > 100):
                
                print(f"\n[*] 检测到页面变化!")
                print(f"[*] 时间: {time.strftime('%H:%M:%S')}")
                print(f"[*] URL: {current_url}")
                print(f"[*] 标题: {current_title}")
                print(f"[*] 内容长度: {current_content_length}")
                
                # 检查是否登录成功
                if is_logged_in_successfully(page):
                    print("[+] 登录成功！页面状态正常")
                    return True
                
                # 检查是否在登录页面
                if "login" in current_url or "signin" in current_url:
                    print("[*] 当前在登录页面，请完成登录...")
                else:
                    print("[*] 页面已跳转，检查登录状态...")
                
                last_url = current_url
                last_title = current_title
                last_content_length = current_content_length
            
            # 检查是否有验证码
            if check_captcha(page):
                print("[!] 检测到验证码，请手动处理...")
                input("处理完验证码后按回车继续...")
            
            time.sleep(2)  # 每2秒检查一次
            
        except Exception as e:
            print(f"[!] 监控过程中出错: {e}")
            time.sleep(5)
    
    print(f"[!] 监控超时 ({max_wait_time} 秒)")
    return False

def is_logged_in_successfully(page):
    """检查是否真正登录成功"""
    try:
        url = page.url
        title = page.title()
        
        # 检查URL - 登录后应该能访问特定页面
        if any(path in url for path in ["/web/chat/", "/web/boss/", "/web/user/"]):
            print("[*] URL显示已登录")
            
            # 检查页面内容
            page_text = page.locator("body").inner_text()
            
            # 检查是否有登录按钮（如果有说明未登录）
            if "登录" in page_text and "立即登录" in page_text:
                print("[*] 页面仍显示登录按钮，可能未完全登录")
                return False
            
            # 检查是否有用户相关元素
            user_indicators = ["我的", "个人中心", "企业中心", "招聘管理", "消息", "沟通"]
            for indicator in user_indicators:
                if indicator in page_text:
                    print(f"[*] 发现用户元素: {indicator}")
                    return True
            
            # 检查是否有候选人相关内容
            candidate_indicators = ["候选人", "简历", "打招呼", "投递", "面试"]
            for indicator in candidate_indicators:
                if indicator in page_text:
                    print(f"[*] 发现候选人相关内容: {indicator}")
                    return True
            
            # 如果页面内容足够丰富，可能已登录
            if len(page_text) > 500:
                print("[*] 页面内容丰富，可能已登录")
                return True
            
        return False
        
    except Exception as e:
        print(f"[!] 检查登录状态时出错: {e}")
        return False

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

def test_message_access(page):
    """测试消息页面访问"""
    print("\n[*] 测试消息页面访问...")
    
    message_urls = [
        "/web/chat/index",
        "/web/boss/chat", 
        "/web/chat",
        "/chat"
    ]
    
    for url_path in message_urls:
        try:
            full_url = settings.BASE_URL.rstrip('/') + url_path
            print(f"[*] 尝试访问: {full_url}")
            
            page.goto(full_url, wait_until="domcontentloaded", timeout=10000)
            time.sleep(2)
            
            title = page.title()
            if title and "错误" not in title and "404" not in title:
                print(f"[+] 成功访问消息页面: {title}")
                
                # 检查页面内容
                try:
                    page_text = page.locator("body").inner_text()
                    print(f"[*] 页面内容长度: {len(page_text)} 字符")
                    
                    # 检查是否有候选人数据
                    if any(keyword in page_text for keyword in ["候选人", "简历", "打招呼", "投递"]):
                        print("[+] 发现候选人相关内容")
                        return True
                    elif "暂无" in page_text or "无数据" in page_text:
                        print("[*] 页面显示暂无数据")
                        return True
                    else:
                        print("[*] 页面内容正常但无候选人数据")
                        return True
                        
                except Exception as e:
                    print(f"[!] 检查页面内容失败: {e}")
                    return True
            else:
                print(f"[*] 页面加载异常: {title}")
                
        except Exception as e:
            print(f"[*] 访问失败: {e}")
            continue
    
    return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=1000)
        context = browser.new_context()
        page = context.new_page()
        
        print("[*] 启动持续监控登录状态...")
        print("[*] 浏览器将保持打开，请完成登录操作")
        
        # 访问首页
        print(f"[*] 访问首页: {settings.BASE_URL}")
        page.goto(settings.BASE_URL, wait_until="load")
        
        # 开始监控
        if monitor_page_changes(page, max_wait_time=600):  # 最多等待10分钟
            print("\n[+] 登录状态监控成功！")
            
            # 测试消息页面访问
            if test_message_access(page):
                print("[+] 消息页面访问正常")
                
                # 保存登录状态
                context.storage_state(path=settings.STORAGE_STATE)
                print(f"[+] 已保存登录状态到 {settings.STORAGE_STATE}")
                
                print("\n[+] 登录完成！现在可以运行候选人读取脚本了")
                print("[*] 运行命令: python src/read_candidates.py --limit 10")
            else:
                print("[!] 消息页面访问异常")
        else:
            print("\n[!] 登录监控超时或失败")
            print("[*] 请检查网络连接和登录状态")
        
        print("\n[*] 浏览器将在30秒后关闭...")
        time.sleep(30)
        browser.close()

if __name__ == "__main__":
    main()
