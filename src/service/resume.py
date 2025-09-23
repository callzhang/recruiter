#!/usr/bin/env python3
"""
Resume viewing and extraction helpers.
Delegated from BossService to keep service file small.
"""
from __future__ import annotations

import time
import base64
import re
from typing import Dict

from src.config import settings
from src.resume_capture import (
    CANVAS_TEXT_HOOK_SCRIPT,
    CANVAS_REBUILD_SCRIPT,
)


def view_online_resume(service, chat_id: str) -> Dict:
    """点击会话 -> 点击“在线简历” -> 等待canvas#resume -> 返回base64/尺寸或切片。
    逻辑与原 boss_service.view_online_resume 一致。
    """
    # 会话与登录
    service._ensure_browser_session()
    if not service.is_logged_in and not service.ensure_login():
        raise Exception("未登录")

    # 若已有在线简历对话框（含 iframe）遮挡，关闭它
    overlay_resume = service.page.locator("div.boss-layer__wrapper")
    if overlay_resume.count() > 0:
        try:
            service.add_notification("已有在线简历对话框遮挡，关闭它", "info")
            service.page.locator('div.boss-popup__close').click(timeout=1000)
        except Exception as e:
            service.add_notification(f"关闭在线简历对话框失败: {e}", "error")

    # 打开对应会话条目
    target = None
    try:
        precise = service.page.locator(
            f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
            f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
        ).first
        if precise and precise.count() > 0:
            target = precise
        target.wait_for(state="visible", timeout=5000)
        target.click()
    except Exception:
        target = None
    if not target:
        return { 'success': False, 'details': '未找到指定对话项' }

    # 等待右侧会话面板就绪
    try:
        service.page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return { 'success': False, 'details': '对话面板未出现' }

    # 点击“在线简历”按钮
    try:
        btn = service.page.locator("a.resume-btn-online").first
        if btn and btn.count() > 0:
            btn.wait_for(state="visible", timeout=5000)
            btn.click()
        else:
            return { 'success': False, 'details': '未找到“在线简历”按钮' }
    except Exception as e:
        return { 'success': False, 'details': f'点击在线简历失败: {e}' }

    # 进入 iframe
    t0 = time.time()
    target_handle = service.page.wait_for_selector("iframe[src*='c-resume']")
    service.add_notification(f'iframe[src*="c-resume"] time: {time.time() - t0}', "info")
    target_frame = service.page.frame(url=re.compile(r"/c-resume"))

    # 1) WASM 导出
    if target_frame is not None:
        try:
            wasm_export = target_frame.evaluate("""
                async () => {
                    const out = { data: null, error: null };
                    try {
                        if (typeof get_export_geek_detail_info === 'function') {
                            try { out.data = get_export_geek_detail_info(); } catch (_) {}
                        }
                        if (!out.data) {
                            const srcs = [
                              ...Array.from(document.querySelectorAll('script[src]')).map(s => s.src),
                              ...Array.from(document.querySelectorAll("link[rel='modulepreload'][href]")).map(l => l.href)
                            ].filter(src => src && /wasm.*canvas.*\.js/i.test(src));
                            for (const src of srcs) {
                                try {
                                    const mod = await import(src);
                                    if (mod && typeof mod.default === 'function') { try { await mod.default(); } catch(e){} }
                                    try {
                                        if (typeof window.__resume_data_store !== 'object') window.__resume_data_store = {};
                                        if (mod && typeof mod.register_js_callback === 'function') {
                                            try { mod.register_js_callback('export_geek_detail_info', function(d){ try{ window.__resume_data_store.export_geek_detail_info = d; }catch(e){} }); } catch(e){}
                                            try { mod.register_js_callback('geek_detail_info', function(d){ try{ window.__resume_data_store.geek_detail_info = d; }catch(e){} }); } catch(e){}
                                        }
                                    } catch(e) {}
                                    if (mod && typeof mod.get_export_geek_detail_info === 'function') {
                                        const d = mod.get_export_geek_detail_info();
                                        if (d && (Array.isArray(d) ? d.length : Object.keys(d||{}).length)) { out.data = d; break; }
                                    }
                                    try { if (mod && typeof mod.trigger_rust_callback === 'function') { mod.trigger_rust_callback('export_geek_detail_info', null); mod.trigger_rust_callback('geek_detail_info', null); } } catch(e){}
                                    try {
                                        const s = window.__resume_data_store || {};
                                        const sd = s.export_geek_detail_info || s.geek_detail_info;
                                        if (sd && (Array.isArray(sd) ? sd.length : Object.keys(sd||{}).length)) { out.data = sd; break; }
                                    } catch(e) {}
                                } catch (e) {
                                    out.error = String(e);
                                }
                            }
                        }
                        if (!out.data) {
                            try {
                                for (const k of Object.keys(window)) {
                                    const v = window[k];
                                    if (v && typeof v.get_export_geek_detail_info === 'function') {
                                        out.data = v.get_export_geek_detail_info();
                                        break;
                                    }
                                }
                            } catch (e) {}
                        }
                    } catch (e) {
                        out.error = String(e);
                    }
                    return out;
                }
            """)
            if isinstance(wasm_export, dict) and wasm_export.get('data'):
                try:
                    data_obj = wasm_export['data']
                    import json as _json
                    text_dump = _json.dumps(data_obj, ensure_ascii=False, indent=2)
                    return {
                        'success': True,
                        'text': text_dump,
                        'html': None,
                        'width': 0,
                        'height': 0,
                        'details': '来自WASM导出(get_export_geek_detail_info)'
                    }
                except Exception:
                    pass
        except Exception as e:
            service.add_notification(f"WASM导出失败: {e}", "error")

    # 2) 安装 fillText/strikeText 钩子
    if target_frame is not None:
        try:
            target_frame.evaluate(CANVAS_TEXT_HOOK_SCRIPT)
        except Exception as e:
            service.add_notification(f"安装fillText钩子失败: {e}", "error")

    # 3) 重建文本
    if target_frame is not None:
        try:
            target_frame.wait_for_selector("canvas#resume", timeout=5000)
            rebuilt = target_frame.evaluate(CANVAS_REBUILD_SCRIPT)
            if isinstance(rebuilt, dict) and (rebuilt.get('text') or rebuilt.get('html')):
                return {
                    'success': True,
                    'text': (rebuilt.get('text') or '') or None,
                    'html': (rebuilt.get('html') or '') or None,
                    'width': 0,
                    'height': 0,
                    'details': f"来自canvas拦截，lines={rebuilt.get('lineCount')}, items={rebuilt.get('itemCount')}"
                }
        except Exception as e:
            service.add_notification(f"canvas拦截失败: {e}", "error")

    # 4) toDataURL 尝试
    try:
        ch = None
        try:
            ch = target_frame.query_selector("canvas#resume")
        except Exception:
            ch = None
        if ch is not None:
            try:
                data_url = ch.evaluate("c => c && c.toDataURL('image/png')")
                if data_url and isinstance(data_url, str) and data_url.startswith('data:image/png;base64,'):
                    width = ch.evaluate("c => c && c.width || 0") or 0
                    height = ch.evaluate("c => c && c.height || 0") or 0
                    return {
                        'success': True,
                        'text': None,
                        'html': None,
                        'image_base64': data_url.split(',', 1)[1],
                        'data_url': data_url,
                        'width': int(width),
                        'height': int(height),
                        'details': '来自canvas.toDataURL整张画布'
                    }
            except Exception as e:
                service.add_notification(f"canvas.toDataURL整张画布失败: {e}", "error")

        # 5) 改进的平铺截图（使用绘图感知滚动）
        try:
            service.add_notification("开始平铺截图流程", "info")
            
            # 安装绘图监听钩子
            try:
                target_frame.evaluate("""
                    () => {
                        if (!window.__drawTick) window.__drawTick = 0;
                        const p = CanvasRenderingContext2D.prototype;
                        if (!p.__patched) {
                            ['drawImage','fillText','strokeText','fill','stroke','clearRect'].forEach(k=>{
                                const o = p[k]; 
                                if (typeof o !== 'function') return;
                                p[k] = function(...a){ 
                                    try{ window.__drawTick++; }catch(_){} 
                                    return o.apply(this,a); 
                                };
                            });
                            p.__patched = true;
                        }
                        return window.__drawTick || 0;
                    }
                """)
                service.add_notification("绘图监听钩子安装成功", "info")
            except Exception as e:
                service.add_notification(f"绘图钩子安装失败: {e}", "error")
            
            total_h = target_frame.evaluate("() => (document.querySelector('canvas#resume')||{}).height || document.documentElement.scrollHeight || document.body.scrollHeight || 0") or 0
            view_h = target_frame.evaluate("() => window.innerHeight || document.documentElement.clientHeight || 0") or 1000
            step = max(600, int(view_h * 0.8))
            service.add_notification(f"计算尺寸 - 总高度: {total_h}, 可视高度: {view_h}, 步长: {step}", "info")
            
            slices = []
            container_loc = target_frame.locator("div#resume").first
            use_container = False
            try:
                use_container = container_loc.count() > 0
            except Exception:
                use_container = False

            y = 0
            iter_guard = 0
            max_iterations = min(20, max(3, int(total_h / step) + 2)) if total_h > 0 else 10
            service.add_notification(f"开始滚动截图，预计 {max_iterations} 次迭代", "info")
            
            while y < max(total_h, view_h * 2) and iter_guard < max_iterations:
                iter_guard += 1
                
                # 记录滚动前的绘图计数
                tick_before = 0
                try:
                    tick_before = target_frame.evaluate("() => window.__drawTick || 0")
                except Exception:
                    pass
                
                try:
                    # 多策略滚动
                    scroll_result = target_frame.evaluate("""
                        (y) => {
                          const can = document.querySelector('canvas#resume');
                          const candidates = [
                            document.querySelector('div#resume'),
                            can && can.parentElement,
                            document.querySelector('.boss-layer__wrapper'),
                            document.querySelector('.dialog-wrap'),
                            document.scrollingElement,
                            document.documentElement,
                            document.body
                          ].filter(Boolean);
                          
                          // 找到有滚动能力的容器
                          const scroller = candidates.find(el => 
                            el.scrollHeight - el.clientHeight > 10
                          ) || document.documentElement;
                          
                          let scrolled = false;
                          const oldScrollTop = scroller.scrollTop;
                          
                          // 尝试多种滚动方法
                          if (typeof scroller.scrollTo === 'function') {
                            scroller.scrollTo(0, y);
                            scrolled = Math.abs(scroller.scrollTop - oldScrollTop) > 5;
                          }
                          if (!scrolled) {
                            try { 
                              scroller.scrollTop = y; 
                              scrolled = Math.abs(scroller.scrollTop - oldScrollTop) > 5;
                            } catch(e) {}
                          }
                          
                          // 发送多种事件来触发重绘
                          const target = document.querySelector('div#resume') || can || scroller;
                          if (target) {
                            try {
                              // wheel事件
                              target.dispatchEvent(new WheelEvent('wheel', {
                                deltaY: 300,
                                bubbles: true
                              }));
                              // scroll事件
                              target.dispatchEvent(new Event('scroll', { bubbles: true }));
                              // resize事件（有时能触发重绘）
                              window.dispatchEvent(new Event('resize'));
                            } catch(e) {}
                          }
                          
                          // 键盘事件
                          try {
                            document.body.focus();
                            ['PageDown', 'ArrowDown', 'Space'].forEach(key => {
                              document.dispatchEvent(new KeyboardEvent('keydown', {
                                key: key,
                                code: key,
                                bubbles: true
                              }));
                            });
                          } catch(e) {}
                          
                          // 强制canvas重绘（如果可能）
                          if (can) {
                            try {
                              const ctx = can.getContext('2d');
                              if (ctx) {
                                ctx.save();
                                ctx.restore();
                              }
                            } catch(e) {}
                          }
                          
                          return {
                            scrolled: scrolled,
                            scrollTop: scroller.scrollTop,
                            oldScrollTop: oldScrollTop,
                            scrollHeight: scroller.scrollHeight,
                            clientHeight: scroller.clientHeight,
                            target: scroller.tagName + (scroller.className ? '.' + scroller.className.split(' ')[0] : '')
                          };
                        }
                    """, y)
                    
                    if scroll_result and isinstance(scroll_result, dict):
                        service.add_notification(f"滚动 {iter_guard}: 目标位置 {y}, 实际 {scroll_result.get('scrollTop', 0)}, 容器: {scroll_result.get('target', 'unknown')}", "info")
                    
                except Exception as e:
                    service.add_notification(f"滚动失败: {e}", "error")
                    break
                
                # 等待绘图更新或超时
                update_detected = False
                try:
                    target_frame.wait_for_function(
                        f"() => (window.__drawTick || 0) > {tick_before}",
                        timeout=2000
                    )
                    update_detected = True
                    service.add_notification(f"检测到绘图更新 (tick从 {tick_before} 增加)", "info")
                except Exception:
                    # 如果没有检测到绘图更新，稍微等待
                    try:
                        target_frame.wait_for_timeout(200)
                    except Exception:
                        pass
                
                # 截图
                try:
                    if use_container:
                        img_bytes = container_loc.screenshot()
                    else:
                        img_bytes = target_handle.screenshot()
                    b64 = base64.b64encode(img_bytes).decode('utf-8')
                    slices.append(b64)
                    service.add_notification(f"截图 {iter_guard} 完成 (位置: {y}, 更新检测: {update_detected})", "info")
                except Exception as e:
                    service.add_notification(f"截图失败: {e}", "error")
                    break
                
                y += step
                
            if slices:
                width_px = 0
                try:
                    width_px = int(target_frame.evaluate("() => (document.querySelector('canvas#resume')||{}).width || document.documentElement.clientWidth || window.innerWidth || 0") or 0)
                except Exception:
                    width_px = 0
                    
                service.add_notification(f"平铺截图完成，共 {len(slices)} 片段", "info")
                return {
                    'success': True,
                    'text': None,
                    'html': None,
                    'image_base64': slices[0],
                    'images_base64': slices,
                    'data_url': None,
                    'width': width_px,
                    'height': int(total_h or 0),
                    'details': f'改进的平铺截图切片 {len(slices)} 段，检测绘图更新'
                }
            else:
                service.add_notification("平铺截图未产生任何切片", "warning")
        except Exception as e:
            service.add_notification(f"平铺截图流程失败: {e}", "error")
        
        # 6) 新标签页全页截图兼底方案
        try:
            service.add_notification("尝试新标签页全页截图", "info")
            iframe_url = target_frame.url
            service.add_notification(f"获取iframe URL: {iframe_url}", "info")
            
            # 在新标签页打开iframe URL
            page = service.page
            new_page = page.context.new_page()
            
            try:
                new_page.goto(iframe_url, wait_until="domcontentloaded", timeout=15000)
                service.add_notification("新标签页加载成功", "info")
                
                # 等待canvas加载
                new_page.wait_for_selector("canvas#resume", timeout=10000)
                service.add_notification("新标签页canvas加载成功", "info")
                
                # 稍微等待渲染完成
                new_page.wait_for_timeout(3000)
                
                # 全页截图
                screenshot = new_page.screenshot(full_page=True)
                b64 = base64.b64encode(screenshot).decode('utf-8')
                
                # 获取canvas尺寸
                canvas_size = new_page.evaluate("""
                    () => {
                        const can = document.querySelector('canvas#resume');
                        return can ? {
                            width: can.width,
                            height: can.height,
                            cssWidth: can.style.width,
                            cssHeight: can.style.height
                        } : null;
                    }
                """)
                
                service.add_notification(f"新标签页全页截图成功，canvas尺寸: {canvas_size}", "info")
                
                return {
                    'success': True,
                    'text': None,
                    'html': None,
                    'image_base64': b64,
                    'data_url': None,
                    'width': canvas_size.get('width', 0) if canvas_size else 0,
                    'height': canvas_size.get('height', 0) if canvas_size else 0,
                    'details': '新标签页全页截图'
                }
                
            finally:
                # 关闭新标签页
                try:
                    new_page.close()
                except Exception:
                    pass
                    
        except Exception as e:
            service.add_notification(f"新标签页全页截图失败: {e}", "error")
            
    except Exception as e:
        return { 'success': False, 'details': f'截图失败: {e}' }
