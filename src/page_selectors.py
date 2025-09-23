# 站点结构会更新，这里提供多个候选选择器，脚本会依次尝试。
# Updated: 2025-09-20 - Added soft restart support
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
    # 基于实际页面结构，优先选择包含候选人信息的元素
    return [
        # 最优先：直接查找包含候选人姓名的元素
        "xpath=//li[contains(text(), '易飞') or contains(text(), '孙朋') or contains(text(), 'Khalil') or contains(text(), '牛小林') or contains(text(), '林雪') or contains(text(), '李卓书')]",
        "xpath=//div[contains(text(), '易飞') or contains(text(), '孙朋') or contains(text(), 'Khalil') or contains(text(), '牛小林') or contains(text(), '林雪') or contains(text(), '李卓书')]",
        # 第二优先：查找包含职位信息的元素
        "xpath=//li[contains(text(), '大模型算法工程师')]",
        "xpath=//div[contains(text(), '大模型算法工程师')]",
        # 第三优先：查找包含消息内容的元素
        "xpath=//li[contains(text(), '撤回了一条消息') or contains(text(), '希望和你聊聊这个职位') or contains(text(), '我对这份工作非常感兴趣')]",
        "xpath=//div[contains(text(), '撤回了一条消息') or contains(text(), '希望和你聊聊这个职位') or contains(text(), '我对这份工作非常感兴趣')]",
        # 第四优先：查找包含时间戳的元素（如 11:53, 14:11, 09月10日等）
        "xpath=//li[contains(text(), '11:53') or contains(text(), '14:11') or contains(text(), '13:20') or contains(text(), '12:22') or contains(text(), '09月10日') or contains(text(), '09月01日') or contains(text(), '08月28日') or contains(text(), '08月21日')]",
        "xpath=//div[contains(text(), '11:53') or contains(text(), '14:11') or contains(text(), '13:20') or contains(text(), '12:22') or contains(text(), '09月10日') or contains(text(), '09月01日') or contains(text(), '08月28日') or contains(text(), '08月21日')]",
        # 第五优先：查找包含未读消息标识的元素
        "xpath=//li[contains(text(), '1') and not(contains(text(), '我要找工作')) and not(contains(text(), '我要招聘'))]",
        "xpath=//div[contains(text(), '1') and not(contains(text(), '我要找工作')) and not(contains(text(), '我要招聘'))]",
        # 最后：尝试通用的选择器，但排除明显的导航元素
        "xpath=//li[not(contains(text(), '沟通') or contains(text(), '任性选') or contains(text(), '我要找工作') or contains(text(), '我要招聘') or contains(text(), '+86') or contains(text(), '非中国大陆'))]",
        "xpath=//div[not(contains(text(), '沟通') or contains(text(), '任性选') or contains(text(), '我要找工作') or contains(text(), '我要招聘') or contains(text(), '+86') or contains(text(), '非中国大陆'))]",
    ]

def chat_company_name_items() -> List[str]:
    # 公司名（聊天列表项内）对应 Locators.COMPANY_NAME_IN_CHAT
    return [
        "xpath=//div[@class='title-box']/span[@class='name-box']//span[2]",
        "xpath=//span[contains(@class, 'company')]",
        "xpath=//div[contains(@class, 'company')]",
        "xpath=//span[contains(text(), '公司')]",
        "xpath=//div[contains(@class, 'title')]//span[2]",
    ]

def chat_last_message_items() -> List[str]:
    # 最近一条消息文本 对应 Locators.LAST_MESSAGE
    return [
        "xpath=//div[@class='gray last-msg']/span[@class='last-msg-text']",
        "xpath=//div[contains(@class, 'last-msg')]",
        "xpath=//span[contains(@class, 'last-msg')]",
        "xpath=//div[contains(@class, 'message')]",
        "xpath=//span[contains(@class, 'message')]",
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
