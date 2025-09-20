#!/usr/bin/env python3
"""
智能候选人读取脚本 - 参考get_jobs项目的登录和页面处理逻辑
"""
from playwright.sync_api import sync_playwright
import sys
import os
import time
import json
import csv
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import settings
from src.utils import export_records

def smart_login_check(page, max_wait_time=600):
    """智能登录状态检查"""
    print("[*] 检查登录状态...")
    print(f"[*] 最大等待时间: {max_wait_time} 秒 (约 {max_wait_time // 60} 分钟)")
    
    start_time = time.time()
    
    try:
        # 先访问首页检查登录状态
        page.goto(settings.BASE_URL, wait_until="domcontentloaded", timeout=10000)
        time.sleep(2)
        
        page_text = page.locator("body").inner_text()
        
        # 检查是否有登录按钮
        if "登录" in page_text and "立即登录" in page_text:
            print("[!] 检测到登录按钮，需要重新登录")
            print("[*] 请在浏览器中完成登录操作...")
            
            # 等待用户登录
            while time.time() - start_time < max_wait_time:
                remaining_time = max_wait_time - (time.time() - start_time)
                remaining_minutes = int(remaining_time // 60)
                remaining_seconds = int(remaining_time % 60)
                
                print(f"[*] 等待登录中... 剩余时间: {remaining_minutes}分{remaining_seconds}秒")
                
                # 重新检查登录状态
                page.goto(settings.BASE_URL, wait_until="domcontentloaded", timeout=10000)
                time.sleep(3)
                
                page_text = page.locator("body").inner_text()
                
                # 如果不再显示登录按钮，说明登录成功
                if not ("登录" in page_text and "立即登录" in page_text):
                    print("[+] 登录成功！")
                    break
                
                time.sleep(10)  # 每10秒检查一次
            
            # 最终检查登录状态
            page_text = page.locator("body").inner_text()
            if "登录" in page_text and "立即登录" in page_text:
                print("[!] 登录超时")
                return False
        
        # 检查是否有用户相关元素
        user_indicators = ["我的", "个人中心", "企业中心", "招聘管理"]
        for indicator in user_indicators:
            if indicator in page_text:
                print(f"[+] 发现用户元素: {indicator}")
                return True
        
        # 如果页面内容足够丰富，可能已登录
        if len(page_text) > 500:
            print("[+] 页面内容丰富，可能已登录")
            return True
        
        return False
        
    except Exception as e:
        print(f"[!] 检查登录状态时出错: {e}")
        return False

def wait_for_chat_page_load(page, max_attempts=30):
    """等待聊天页面加载，处理各种加载状态"""
    print("[*] 访问聊天页面...")
    total_wait_time = max_attempts * 20
    print(f"[*] 最大等待时间: {total_wait_time} 秒 (约 {total_wait_time // 60} 分钟)")
    
    for attempt in range(max_attempts):
        remaining_time = (max_attempts - attempt) * 20
        remaining_minutes = remaining_time // 60
        remaining_seconds = remaining_time % 60
        try:
            print(f"[*] 尝试访问聊天页面 (第 {attempt + 1} 次)...")
            print(f"[*] 剩余等待时间: {remaining_minutes}分{remaining_seconds}秒")
            
            # 访问聊天页面
            page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            
            # 检查页面状态
            page_text = page.locator("body").inner_text()
            print(f"[*] 页面内容长度: {len(page_text)} 字符")
            
            # 检查是否有错误
            if "错误" in page_text or "404" in page_text:
                print("[!] 页面显示错误")
                continue
            
            # 检查是否在登录页面
            if "登录" in page_text and "立即登录" in page_text:
                print("[!] 重定向到登录页面")
                return False
            
            # 检查是否有加载中提示
            if "加载中" in page_text or "请稍候" in page_text:
                print(f"[*] 页面仍在加载中，等待... (第 {attempt + 1} 次)")
                print(f"[*] 剩余等待时间: {remaining_minutes}分{remaining_seconds}秒")
                time.sleep(20)  # 增加等待时间到20秒
                continue
            
            # 检查是否有候选人相关内容
            candidate_keywords = ["候选人", "简历", "打招呼", "投递", "面试", "聊天", "消息"]
            found_keywords = [kw for kw in candidate_keywords if kw in page_text]
            
            if found_keywords:
                print(f"[+] 发现候选人相关内容: {found_keywords}")
                return True
            
            # 检查是否有"无数据"提示
            if "暂无" in page_text or "无数据" in page_text or "没有" in page_text:
                print("[*] 页面显示暂无数据")
                return True
            
            # 如果页面内容足够丰富，认为加载完成
            if len(page_text) > 100:
                print("[+] 页面加载完成")
                return True
            
            print(f"[*] 页面内容较少，继续等待... (第 {attempt + 1} 次)")
            print(f"[*] 剩余等待时间: {remaining_minutes}分{remaining_seconds}秒")
            time.sleep(20)  # 增加等待时间到20秒
            
        except Exception as e:
            print(f"[!] 访问聊天页面失败: {e}")
            time.sleep(20)  # 增加等待时间到20秒
            continue
    
    print("[!] 聊天页面加载失败")
    return False

def extract_candidates_from_page(page):
    """从页面提取候选人信息"""
    print("[*] 开始提取候选人信息...")
    
    candidates = []
    
    # 尝试不同的选择器
    selectors = [
        "li[class*='item']",
        "div[class*='item']", 
        "li[class*='conversation']",
        "div[class*='conversation']",
        "li[class*='chat']",
        "div[class*='chat']",
        "li[class*='message']",
        "div[class*='message']"
    ]
    
    for selector in selectors:
        try:
            elements = page.locator(selector).all()
            if elements:
                print(f"[*] 使用选择器 {selector} 找到 {len(elements)} 个元素")
                
                for i, elem in enumerate(elements):
                    try:
                        text = elem.inner_text().strip()
                        if text and len(text) > 10:  # 过滤掉太短的文本
                            candidate = {
                                "index": i + 1,
                                "timestamp": int(time.time()),
                                "raw_text": text,
                                "selector_used": selector
                            }
                            
                            # 尝试提取结构化信息
                            lines = text.split('\n')
                            for line in lines:
                                line = line.strip()
                                if '岁' in line:
                                    candidate["age"] = line
                                elif any(edu in line for edu in ['本科', '硕士', '大专', '博士']):
                                    candidate["education"] = line
                                elif '年' in line and '经验' in line:
                                    candidate["experience"] = line
                                elif any(city in line for city in ['市', '区', '省']):
                                    candidate["location"] = line
                            
                            candidates.append(candidate)
                            print(f"[+] 提取候选人 {i+1}: {text[:50]}...")
                            
                    except Exception as e:
                        print(f"[!] 提取第 {i+1} 个候选人信息失败: {e}")
                        continue
                
                if candidates:
                    break
                    
        except Exception as e:
            print(f"[!] 选择器 {selector} 失败: {e}")
            continue
    
    return candidates

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.HEADLESS, slow_mo=1000)
        context = browser.new_context(storage_state=settings.STORAGE_STATE)
        page = context.new_page()
        
        print("[*] 启动智能候选人读取...")
        
        # 检查登录状态
        if not smart_login_check(page, max_wait_time=600):
            print("[!] 登录状态失效，请重新登录")
            print("[*] 运行命令: python improved_login.py")
            browser.close()
            return
        
        # 等待聊天页面加载
        if not wait_for_chat_page_load(page):
            print("[!] 无法访问聊天页面")
            browser.close()
            return
        
        # 提取候选人信息
        candidates = extract_candidates_from_page(page)
        
        if candidates:
            # 导出数据
            json_path, csv_path = export_records(candidates, prefix="smart_candidates")
            print(f"[+] 成功提取 {len(candidates)} 个候选人")
            print(f"[+] 导出文件: {json_path}")
            print(f"[+] 导出文件: {csv_path}")
        else:
            print("[*] 未找到候选人数据")
            print("[*] 可能的原因:")
            print("  1. 当前没有收到候选人消息")
            print("  2. 需要切换到不同的筛选条件")
            print("  3. 页面结构发生了变化")
            
            # 保存页面截图用于调试
            try:
                page.screenshot(path="data/output/debug_page.png")
                print("[+] 已保存页面截图到 data/output/debug_page.png")
            except:
                pass
        
        print("\n[*] 浏览器将在10秒后关闭...")
        time.sleep(10)
        browser.close()

if __name__ == "__main__":
    main()
