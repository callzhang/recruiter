# 站点结构会更新，这里提供多个候选选择器，脚本会依次尝试。
from typing import List

def nav_message_candidates() -> List[str]:
    # 顶部/侧边栏“消息/沟通”入口
    return [
        "text=消息",
        "text=沟通",
        "a:has-text('消息')",
        "a:has-text('沟通')",
        "xpath=//a[contains(., '消息') or contains(., '沟通')]",
        "xpath=//span[contains(., '消息') or contains(., '沟通')]/ancestor::a",
    ]

def filter_greeting_candidates() -> List[str]:
    # “打招呼”筛选/标签
    return [
        "text=打招呼",
        "button:has-text('打招呼')",
        "xpath=//a[contains(., '打招呼')]",
        "xpath=//button[contains(., '打招呼')]",
    ]

def conversation_list_items() -> List[str]:
    # 左侧会话列表条目（候选人）
    return [
        # 对齐 get_jobs Locators.CHAT_LIST_ITEM
        "xpath=//li[@role='listitem']",
        "xpath=//div[contains(@class,'list') or contains(@class,'conversation') or contains(@class,'chat')]//li",
        "xpath=//ul/li[contains(@class,'item')]",
    ]

def chat_company_name_items() -> List[str]:
    # 公司名（聊天列表项内）对应 Locators.COMPANY_NAME_IN_CHAT
    return [
        "xpath=//div[@class='title-box']/span[@class='name-box']//span[2]",
    ]

def chat_last_message_items() -> List[str]:
    # 最近一条消息文本 对应 Locators.LAST_MESSAGE
    return [
        "xpath=//div[@class='gray last-msg']/span[@class='last-msg-text']",
    ]

def open_resume_actions() -> List[str]:
    # 打开简历按钮/链接
    return [
        "text=查看简历",
        "a:has-text('简历')",
        "button:has-text('简历')",
        "xpath=//a[contains(., '简历')]",
        "xpath=//button[contains(., '简历')]",
    ]

def resume_sections() -> List[str]:
    # 简历主要分区标题
    return ["基本信息", "工作经历", "教育经历", "项目经历", "技能特长", "自我评价"]

def captcha_iframes() -> List[str]:
    # 常见验证码 iframe 线索
    return [
        "iframe[src*='geetest']",
        "iframe[src*='captcha']",
        "iframe[id*='captcha']",
    ]
