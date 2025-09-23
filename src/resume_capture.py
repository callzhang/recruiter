"""
Resume capture helpers: robust multi-step pipeline to extract text or image
from a WASM-driven canvas-based resume viewer embedded in an iframe.

Primary entrypoint: capture_resume_from_chat(page, chat_id, logger=None)

Steps (in order):
- open chat and click "在线简历"
- locate iframe ('c-resume') and get frame
- try WASM exports (get_export_geek_detail_info, callbacks)
- install canvas text hooks and rebuild lines
- capture canvas.toDataURL
- capture tiled screenshots inside the iframe
- element screenshot fallback of container

This module is intentionally verbose and defensive.
"""

from __future__ import annotations

import re
import time
import base64
from textwrap import dedent
from typing import Any, Dict, Optional


CANVAS_TEXT_HOOK_SCRIPT = dedent("""
(function(){
  try {
    if (window.__resume_hooked) { return true; }
    window.__resume_hooked = true;
  } catch (err) {}

  var logs = [];

  function record(ctx, text, x, y, style) {
    try {
      logs.push({
        t: String(text || ''),
        x: Number(x) || 0,
        y: Number(y) || 0,
        f: (ctx && ctx.font) || '',
        s: style || (ctx && (ctx.fillStyle || ctx.strokeStyle)) || ''
      });
    } catch (e) {}
  }

  try {
    var proto = window.CanvasRenderingContext2D && window.CanvasRenderingContext2D.prototype;
    if (proto && !proto.__resume_text_wrapped) {
      function wrap(methodName, styleProp) {
        var original = proto[methodName];
        if (typeof original !== 'function') { return; }
        proto[methodName] = function(text, x, y) {
          record(this, text, x, y, this && this[styleProp]);
          return original.apply(this, arguments);
        };
      }
      wrap('fillText', 'fillStyle');
      wrap('strokeText', 'strokeStyle');
      proto.__resume_text_wrapped = true;
    }
  } catch (e) {}

  try {
    var canvasProto = window.HTMLCanvasElement && window.HTMLCanvasElement.prototype;
    if (canvasProto && !canvasProto.__resume_context_wrapped) {
      var originalGetContext = canvasProto.getContext;
      if (typeof originalGetContext === 'function') {
        canvasProto.getContext = function() {
          return originalGetContext.apply(this, arguments);
        };
      }
      canvasProto.__resume_context_wrapped = true;
    }
  } catch (e) {}

  try {
    window.__getResumeTextLogs = function(){ return logs.slice(); };
  } catch (e) {}

  return true;
})();
""")


CANVAS_REBUILD_SCRIPT = dedent("""
(function(){
  try {
    var logs = (window.__getResumeTextLogs && window.__getResumeTextLogs()) || [];
    logs.sort(function(a, b){
      var ay = (a && a.y) || 0;
      var by = (b && b.y) || 0;
      var dy = ay - by;
      if (dy !== 0) { return dy; }
      var ax = (a && a.x) || 0;
      var bx = (b && b.x) || 0;
      return ax - bx;
    });
    var tol = 4;
    var lines = [];
    for (var i = 0; i < logs.length; i++) {
      var item = logs[i];
      var y = Number(item && item.y) || 0;
      var last = lines.length ? lines[lines.length - 1] : null;
      if (!last || Math.abs(last.y - y) > tol) {
        lines.push({ y: y, parts: [item] });
      } else {
        last.parts.push(item);
      }
    }
    function esc(s) {
      return String(s).replace(/[<&>]/g, function(ch){
        if (ch === '<') { return '&lt;'; }
        if (ch === '>') { return '&gt;'; }
        return '&amp;';
      });
    }
    var textLines = [];
    var htmlLines = [];
    for (var j = 0; j < lines.length; j++) {
      var line = lines[j];
      var txt = '';
      var parts = (line && line.parts) || [];
      for (var k = 0; k < parts.length; k++) {
        var part = parts[k];
        txt += String((part && part.t) || '');
      }
      textLines.push(txt);
      htmlLines.push('<div>' + esc(txt) + '</div>');
    }
    return {
      html: htmlLines.join('\\\\n'),
      text: textLines.join('\\\\n'),
      lineCount: lines.length,
      itemCount: logs.length
    };
  } catch (err) {
    return { html: '', text: '', lineCount: 0, itemCount: 0, error: String(err) };
  }
})();
""")


def _log(logger, level: str, message: str) -> None:
    try:
        if logger and hasattr(logger, level):
            getattr(logger, level)(message)
    except Exception:
        pass


def _try_open_online_resume(page, chat_id: str, logger=None) -> Dict[str, Any]:
    """Open the target chat and click the online resume button.
    Returns { success, details } and leaves the UI on the online resume dialog.
    """
    # Close existing overlay if present
    try:
        overlay_resume = page.locator("div.boss-layer__wrapper")
        if overlay_resume.count() > 0:
            _log(logger, "info", "已有在线简历对话框遮挡，关闭它")
            try:
                page.locator('div.boss-popup__close').click(timeout=1000)
            except Exception:
                pass
    except Exception:
        pass

    # Focus the chat item
    target = None
    try:
        precise = page.locator(
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

    # Wait for conversation panel
    try:
        page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return { 'success': False, 'details': '对话面板未出现' }

    # Click online resume button
    try:
        btn = page.locator("a.resume-btn-online").first
        if btn and btn.count() > 0:
            btn.wait_for(state="visible", timeout=5000)
            btn.click()
        else:
            return { 'success': False, 'details': '未找到“在线简历”按钮' }
    except Exception as e:
        return { 'success': False, 'details': f'点击在线简历失败: {e}' }

    return { 'success': True, 'details': '已打开在线简历' }


def _get_resume_frame(page, logger=None):
    """Wait and return (iframe_element_handle, frame) for resume viewer."""
    try:
        t0 = time.time()
        iframe_handle = page.wait_for_selector("iframe[src*='c-resume']")
        _log(logger, "info", f"iframe[src*='c-resume'] time: {time.time() - t0}")
        frame = page.frame(url=re.compile(r"/c-resume"))
        return iframe_handle, frame
    except Exception as e:
        _log(logger, "error", f"查找简历iframe失败: {e}")
        return None, None


def _try_wasm_exports(frame, logger=None) -> Optional[Dict[str, Any]]:
    """Attempt to retrieve structured data from WASM module.
    Returns a dict if found; otherwise None.
    """
    if frame is None:
        return None
    try:
        payload = frame.evaluate(
            """
            async () => {
                const out = { data: null, error: null, attempts: [] };

                const hasPayload = (val) => {
                    if (!val) return false;
                    if (Array.isArray(val)) return val.length > 0;
                    if (typeof val === 'object') return Object.keys(val).length > 0;
                    return true;
                };

                const ensureStore = () => {
                    if (typeof window.__resume_data_store !== 'object' || window.__resume_data_store === null) {
                        try {
                            window.__resume_data_store = {};
                        } catch (_) {
                            return {};
                        }
                    }
                    return window.__resume_data_store;
                };

                const takeFromStore = () => {
                    try {
                        const store = ensureStore();
                        const data = store.export_geek_detail_info || store.geek_detail_info;
                        return hasPayload(data) ? data : null;
                    } catch (err) {
                        out.attempts.push(`store:${err}`);
                        return null;
                    }
                };

                const useModule = async (mod, label) => {
                    if (!mod) return null;
                    const tag = (msg) => out.attempts.push(`${label||'mod'}:${msg}`);

                    try {
                        if (typeof mod.default === 'function') {
                            await mod.default();
                        }
                    } catch (err) {
                        tag(`init:${err}`);
                    }

                    try {
                        const store = ensureStore();
                        if (typeof mod.register_js_callback === 'function') {
                            try {
                                mod.register_js_callback('export_geek_detail_info', (d) => {
                                    try { store.export_geek_detail_info = d; } catch (_) {}
                                });
                            } catch (err) {
                                tag(`register-export:${err}`);
                            }
                            try {
                                mod.register_js_callback('geek_detail_info', (d) => {
                                    try { store.geek_detail_info = d; } catch (_) {}
                                });
                            } catch (err) {
                                tag(`register-geek:${err}`);
                            }
                        }
                    } catch (err) {
                        tag(`store:${err}`);
                    }

                    let directResult = null;
                    try {
                        if (typeof mod.get_export_geek_detail_info === 'function') {
                            directResult = mod.get_export_geek_detail_info();
                            if (hasPayload(directResult)) {
                                return directResult;
                            }
                        }
                    } catch (err) {
                        tag(`get:${err}`);
                    }

                    const triggerPayloads = [undefined, null, '', 'null', '{}', '[]', { force: true }, []];
                    const triggerNames = [
                        'export_geek_detail_info',
                        'geek_detail_info',
                        'export_resume_detail_info',
                        'resume_detail',
                        'geek_detail',
                    ];

                    if (typeof mod.trigger_rust_callback === 'function') {
                        for (const name of triggerNames) {
                            for (const payload of triggerPayloads) {
                                try {
                                    mod.trigger_rust_callback(name, payload);
                                    tag(`trigger:${name}:${typeof payload}:ok`);
                                } catch (err) {
                                    tag(`trigger:${name}:${typeof payload}:${err}`);
                                }
                            }
                        }
                    }

                    for (let attempt = 0; attempt < 6; attempt++) {
                        const storeData = takeFromStore();
                        if (hasPayload(storeData)) {
                            return storeData;
                        }
                        if (typeof mod.get_export_geek_detail_info === 'function') {
                            try {
                                const retryDirect = mod.get_export_geek_detail_info();
                                if (hasPayload(retryDirect)) {
                                    return retryDirect;
                                }
                            } catch (err) {
                                tag(`retry-get:${err}`);
                            }
                        }
                        await new Promise((resolve) => setTimeout(resolve, 20 * (attempt + 1)));
                    }

                    const fallbackStore = takeFromStore();
                    if (hasPayload(fallbackStore)) {
                        return fallbackStore;
                    }

                    return null;
                };

                try {
                    if (typeof get_export_geek_detail_info === 'function') {
                        const direct = get_export_geek_detail_info();
                        if (hasPayload(direct)) {
                            out.data = direct;
                            return out;
                        }
                    }
                } catch (err) {
                    out.attempts.push(`global-direct:${err}`);
                }

                const moduleObjects = [];
                try {
                    const store = ensureStore();
                    const globalKeys = Object.keys(window);
                    for (const key of globalKeys) {
                        if (!key) continue;
                        let val;
                        try {
                            val = window[key];
                        } catch (_) {
                            continue;
                        }
                        if (!val || (typeof val !== 'object' && typeof val !== 'function')) continue;
                        const hasExports = typeof val.register_js_callback === 'function'
                            && typeof val.trigger_rust_callback === 'function';
                        if (hasExports || typeof val.get_export_geek_detail_info === 'function') {
                            moduleObjects.push({ label: `window.${key}`, module: val });
                        }
                    }
                } catch (err) {
                    out.attempts.push(`enumerate:${err}`);
                }

                for (const entry of moduleObjects) {
                    try {
                        const res = await useModule(entry.module, entry.label);
                        if (hasPayload(res)) {
                            out.data = res;
                            return out;
                        }
                    } catch (err) {
                        out.attempts.push(`use-${entry.label}:${err}`);
                    }
                }

                const urlCandidates = new Set();
                const pushUrl = (url, reason) => {
                    if (!url || typeof url !== 'string') return;
                    try {
                        const normalized = new URL(url, window.location.href).href;
                        urlCandidates.add(normalized);
                        out.attempts.push(`candidate:${reason}:${normalized}`);
                    } catch (_) {}
                };

                const nodes = [
                    ...Array.from(document.querySelectorAll("script[type='module'][src]")),
                    ...Array.from(document.querySelectorAll('script[src]')),
                    ...Array.from(document.querySelectorAll("link[rel='modulepreload'][href]")),
                    ...Array.from(document.querySelectorAll("link[rel='preload'][as='script'][href]"))
                ];
                for (const node of nodes) {
                    const src = node && (node.src || node.href);
                    if (!src) continue;
                    const lower = src.toLowerCase();
                    if (lower.includes('wasm') && lower.includes('canvas') && lower.endsWith('.js')) {
                        pushUrl(src, 'match');
                    } else if (lower.includes('index') && lower.endsWith('.js')) {
                        try {
                            const normalized = new URL(src, window.location.href);
                            const baseHref = normalized.href.replace(/[^/]*$/, '');
                            pushUrl(`${baseHref}wasm_canvas-1.0.2-5030.js`, 'derived');
                        } catch (_) {}
                    }
                }

                try {
                    const resources = (performance && typeof performance.getEntriesByType === 'function')
                        ? performance.getEntriesByType('resource')
                        : [];
                    for (const entry of resources || []) {
                        if (entry && entry.name) {
                            pushUrl(entry.name, 'perf');
                        }
                    }
                } catch (_) {}

                const fallbackVersion = '1.0.2-5030';
                try {
                    pushUrl(new URL(`wasm_canvas-${fallbackVersion}.js`, window.location.href).href, 'fallback-relative');
                } catch (_) {}
                try {
                    pushUrl(`https://static.zhipin.com/assets/zhipin/wasm/resume/wasm_canvas-${fallbackVersion}.js`, 'fallback-global');
                } catch (_) {}

                for (const url of Array.from(urlCandidates)) {
                    try {
                        const mod = await import(url);
                        const res = await useModule(mod, url);
                        if (hasPayload(res)) {
                            out.data = res;
                            return out;
                        }
                    } catch (err) {
                        out.attempts.push(`import:${url}:${err}`);
                    }
                }

                const finalStore = takeFromStore();
                if (hasPayload(finalStore)) {
                    out.data = finalStore;
                }

                return out;
            }
            """
        )
        extras = None
        try:
            extras = frame.evaluate(
                """
                () => {
                    const out = {};
                    try {
                        const node = document.querySelector('[data-props]');
                        if (node) {
                            const raw = node.getAttribute('data-props');
                            if (raw) {
                                try {
                                    out.dataProps = JSON.parse(raw);
                                } catch (err) {
                                    out.dataPropsError = String(err);
                                }
                            }
                        }
                    } catch (err) {
                        out.dataPropsError = String(err);
                    }
                    try {
                        const state = window.__INITIAL_STATE__;
                        if (state) {
                            out.initialStateKeys = Object.keys(state || {});
                            if (state.resume) {
                                out.initialResume = state.resume;
                            } else if (state.geekDetail) {
                                out.initialResume = state.geekDetail;
                            }
                        }
                    } catch (err) {
                        out.initialStateError = String(err);
                    }
                    return out;
                }
                """
            )
        except Exception as extras_err:
            extras = { 'error': str(extras_err) }

        if isinstance(payload, dict):
            if extras:
                payload['extra'] = extras
            data_obj = payload.get("data")
            if isinstance(data_obj, dict) and isinstance(extras, dict):
                data_props = extras.get('dataProps')
                initial_resume = extras.get('initialResume')
                def _merge_fields(source):
                    if isinstance(source, dict):
                        for key in (
                            'geekAdvantageList',
                            'geekAdvantage',
                            'geekSkillList',
                            'geekSkill',
                            'geekExpectList',
                            'geekExpect',
                            'advantageList',
                            'personalAdvantage',
                        ):
                            if key in source and source[key] is not None:
                                try:
                                    data_obj[key] = source[key]
                                except Exception:
                                    pass
                _merge_fields(data_props)
                _merge_fields(initial_resume)
        if isinstance(payload, dict) and payload.get("data"):
            return payload.get("data")
    except Exception as e:
        _log(logger, "error", f"WASM导出失败: {payload}, \nError: {e}")
    return None


def _install_canvas_text_hooks(frame, logger=None) -> bool:
    if frame is None:
        return False
    try:
        return bool(frame.evaluate(CANVAS_TEXT_HOOK_SCRIPT))
    except Exception as e:
        _log(logger, "error", f"安装fillText钩子失败: {e}")
        return False


def _rebuild_text_from_logs(frame, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None:
        return None
    try:
        frame.wait_for_selector("canvas#resume", timeout=5000)
    except Exception:
        pass
    try:
        rebuilt = frame.evaluate(CANVAS_REBUILD_SCRIPT)
        if isinstance(rebuilt, dict) and (rebuilt.get('text') or rebuilt.get('html')):
            return rebuilt
    except Exception as e:
        _log(logger, "error", f"canvas拦截失败: {e}")
    return None


def _install_clipboard_hooks(frame, logger=None) -> bool:
    if frame is None:
        return False
    try:
        code = (
            "(function(){\n"
            "  try { if (window.__resume_clipboard_hooked) return true; } catch(e) {}\n"
            "  try { window.__resume_clipboard_hooked = true; } catch(e) {}\n"
            "  try { if (!window.__clipboardWrites) window.__clipboardWrites = []; } catch(e) {}\n"
            "  try {\n"
            "    if (navigator && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {\n"
            "      var orig = navigator.clipboard.writeText.bind(navigator.clipboard);\n"
            "      navigator.clipboard.writeText = function(t){\n"
            "        try { (window.__clipboardWrites||[]).push({ text: String(t||''), ts: Date.now() }); } catch(e) {}\n"
            "        return orig(t);\n"
            "      };\n"
            "    }\n"
            "  } catch(e) {}\n"
            "  try {\n"
            "    var origExec = document.execCommand && document.execCommand.bind(document);\n"
            "    if (origExec) {\n"
            "      document.execCommand = function(cmd){\n"
            "        var r = true;\n"
            "        try { r = origExec.apply(document, arguments); } catch(e) {}\n"
            "        try {\n"
            "          var c = String(cmd||'').toLowerCase();\n"
            "          if (c === 'copy') {\n"
            "            var sel = '';\n"
            "            try { sel = String(window.getSelection && window.getSelection()); } catch(e2) {}\n"
            "            (window.__clipboardWrites||[]).push({ text: sel||'', ts: Date.now(), via: 'execCommand' });\n"
            "          }\n"
            "        } catch(e3) {}\n"
            "        return r;\n"
            "      };\n"
            "    }\n"
            "  } catch(e) {}\n"
            "  return true;\n"
            "})();"
        )
        return bool(frame.evaluate(code))
    except Exception as e:
        _log(logger, "error", f"安装剪贴板钩子失败: {e}")
        return False


def _read_clipboard_logs(frame, logger=None) -> Optional[str]:
    if frame is None:
        return None
    try:
        data = frame.evaluate("(function(){ try { return (window.__clipboardWrites||[]).slice(); } catch(e){ return []; } })()")
        if isinstance(data, list) and data:
            # Concatenate unique lines
            texts = []
            seen = set()
            for item in data:
                try:
                    t = str((item or {}).get('text') or '')
                    if t and t not in seen:
                        seen.add(t)
                        texts.append(t)
                except Exception:
                    continue
            if texts:
                return "\n".join(texts)
    except Exception:
        return None
    return None


def _try_trigger_copy_buttons(frame, logger=None) -> None:
    if frame is None:
        return
    # Best-effort: click common copy/export buttons inside the viewer
    selectors = [
        "button:has-text('复制')",
        "a:has-text('复制')",
        "button:has-text('复制简历')",
        "a:has-text('复制简历')",
        "button:has-text('导出')",
        "a:has-text('导出')",
    ]
    for s in selectors:
        try:
            loc = frame.locator(s).first
            if loc and loc.count() > 0:
                try:
                    loc.click()
                    try:
                        frame.wait_for_timeout(300)
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            continue


def _capture_canvas_data_url(frame, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None:
        return None
    try:
        ch = None
        try:
            ch = frame.query_selector("canvas#resume")
        except Exception:
            ch = None
        if ch is not None:
            data_url = ch.evaluate("c => c && c.toDataURL('image/png')")
            width = ch.evaluate("c => c && c.width || 0") or 0
            height = ch.evaluate("c => c && c.height || 0") or 0
            return {
                'image_base64': data_url.split(',', 1)[1],
                'data_url': data_url,
                'width': int(width),
                'height': int(height),
                'details': '来自canvas.toDataURL整张画布'
            }
    except Exception as e:
        _log(logger, "error", f"canvas.toDataURL整张画布失败: {e}")
    return None


def _capture_tiled_screenshots(frame, iframe_handle, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None or iframe_handle is None:
        return None
    try:
        total_h = frame.evaluate("() => (document.querySelector('canvas#resume')||{}).height || document.documentElement.scrollHeight || document.body.scrollHeight || 0") or 0
        view_h = frame.evaluate("() => window.innerHeight || document.documentElement.clientHeight || 0") or 1000
        step = max(600, int(view_h * 0.9))
        slices = []
        container_loc = frame.locator("div#resume").first
        use_container = False
        try:
            use_container = container_loc.count() > 0
        except Exception:
            use_container = False

        y = 0
        iter_guard = 0
        # 安装绘图监听钩子
        try:
            frame.evaluate("""
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
        except Exception:
            pass

        while y < max(total_h, view_h) and iter_guard < 200:
            iter_guard += 1
            
            # 记录滚动前的绘图计数
            tick_before = 0
            try:
                tick_before = frame.evaluate("() => window.__drawTick || 0")
            except Exception:
                pass
            
            try:
                # 更智能的滚动策略
                actual_scroll = frame.evaluate(
                    """
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
                      if (typeof scroller.scrollTo === 'function') {
                        scroller.scrollTo(0, y);
                        scrolled = true;
                      } else {
                        try { 
                          scroller.scrollTop = y; 
                          scrolled = true;
                        } catch(e) {}
                      }
                      
                      // 发送多种事件来触发重绘
                      const target = document.querySelector('div#resume') || can || scroller;
                      if (target) {
                        try {
                          target.dispatchEvent(new WheelEvent('wheel', {
                            deltaY: 200,
                            bubbles: true
                          }));
                          target.dispatchEvent(new Event('scroll', { bubbles: true }));
                        } catch(e) {}
                      }
                      
                      // 尝试键盘事件
                      try {
                        document.body.focus();
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                          key: 'PageDown',
                          code: 'PageDown',
                          bubbles: true
                        }));
                      } catch(e) {}
                      
                      return {
                        scrolled: scrolled,
                        scrollTop: scroller.scrollTop,
                        scrollHeight: scroller.scrollHeight,
                        clientHeight: scroller.clientHeight,
                        target: scroller.tagName + (scroller.className ? '.' + scroller.className : '')
                      };
                    }
                    """,
                    y,
                )
                if actual_scroll and isinstance(actual_scroll, dict) and logger:
                    logger.info(f"滚动到 {y}, 容器: {actual_scroll.get('target', 'unknown')}, scrollTop: {actual_scroll.get('scrollTop', 0)}")
                
            except Exception as e:
                if logger:
                    logger.error(f"滚动失败: {e}")
                break
            
            # 等待绘图更新或超时
            update_detected = False
            try:
                frame.wait_for_function(
                    f"() => (window.__drawTick || 0) > {tick_before}",
                    timeout=1500
                )
                update_detected = True
                if logger:
                    logger.info(f"检测到绘图更新 (tick: {tick_before} -> ?)")
            except Exception:
                # 如果没有检测到绘图更新，继续但增加等待时间
                try:
                    frame.wait_for_timeout(150)
                except Exception:
                    pass
            try:
                if use_container:
                    img_bytes = container_loc.screenshot()
                else:
                    img_bytes = iframe_handle.screenshot()
                b64 = base64.b64encode(img_bytes).decode('utf-8')
                slices.append(b64)
                if logger:
                    logger.info(f"截图 {iter_guard} 完成 (位置: {y})")
            except Exception as e:
                if logger:
                    logger.error(f"截图失败: {e}")
                break
            y += step
        if slices:
            width_px = 0
            try:
                width_px = int(frame.evaluate("() => (document.querySelector('canvas#resume')||{}).width || document.documentElement.clientWidth || window.innerWidth || 0") or 0)
            except Exception:
                width_px = 0
            return {
                'image_base64': slices[0],
                'images_base64': slices,
                'data_url': None,
                'width': width_px,
                'height': int(total_h or 0),
                'details': f'平铺截图切片 {len(slices)} 段'
            }
    except Exception:
        pass
    return None


def _element_screenshot_fallback(page, frame, logger=None) -> Optional[Dict[str, Any]]:
    if frame is None:
        return None
    try:
        container = frame.locator("div#resume").first
        handle = container.element_handle()
        dims = container.bounding_box() or {}
        width = int(dims.get('width') or 0)
        height = int(dims.get('height') or 0)
        # Expand viewport to avoid gray area
        try:
            page.set_viewport_size({"width": width + 200, "height": height + 200})
            time.sleep(2)
        except Exception:
            pass
        shot = handle.screenshot()
        b64 = base64.b64encode(shot).decode('utf-8')
        return {
            'image_base64': b64,
            'data_url': None,
            'width': width,
            'height': height,
            'details': '容器元素截图（可能受限于可视区域）'
        }
    except Exception:
        return None


def capture_resume_from_chat(page, chat_id: str, logger=None, capture_method: str = "auto") -> Dict[str, Any]:
    """High-level method used by the service: returns a dict with keys:
    - success: bool
    - text/html or image_base64/data_url
    - width/height
    - details
    
    Args:
        page: Playwright page object
        chat_id: Chat ID to capture resume from
        logger: Optional logger for debug info
        capture_method: Method to use for capture. Options:
            - "auto" (default): Try all methods in optimal order
            - "wasm": Only try WASM export methods
            - "image": Skip text methods, only use screenshot methods
    """
    try:
        # Validate capture_method parameter
        valid_methods = ["auto", "wasm", "image"]
        if capture_method not in valid_methods:
            return { 'success': False, 'details': f'无效的capture_method: {capture_method}，必须是: {valid_methods}' }

        if logger:
            logger.info(f"使用捕获方法: {capture_method}")

        # 1) open online resume UI
        open_ret = _try_open_online_resume(page, chat_id, logger)
        if not open_ret.get('success'):
            return { 'success': False, 'details': open_ret.get('details') or '无法打开在线简历' }

        # 2) locate iframe and frame
        iframe_handle, frame = _get_resume_frame(page, logger)
        if frame is None:
            return { 'success': False, 'details': '未找到简历iframe' }

        # 3) WASM exports (if enabled)
        if capture_method in ["auto", "wasm"]:
            wasm_obj = _try_wasm_exports(frame, logger)
            if wasm_obj is not None:
                try:
                    import json as _json
                    text_dump = _json.dumps(wasm_obj, ensure_ascii=False, indent=2)
                except Exception:
                    text_dump = str(wasm_obj)
                return {
                    'success': True,
                    'text': text_dump,
                    'html': None,
                    'width': 0,
                    'height': 0,
                    'details': f'来自WASM导出(get_export_geek_detail_info) - 方法:{capture_method}'
                }
            
            # If wasm method is specifically requested but failed
            if capture_method == "wasm":
                return { 'success': False, 'details': 'WASM方法失败，未找到可用的导出函数' }

        # 4) Install canvas hooks and rebuild text (auto mode only)
        if capture_method == "auto":
            hooked = _install_canvas_text_hooks(frame, logger)
            if hooked:
                rebuilt = _rebuild_text_from_logs(frame, logger)
                if isinstance(rebuilt, dict) and (rebuilt.get('text') or rebuilt.get('html')):
                    return {
                        'success': True,
                        'text': (rebuilt.get('text') or '') or None,
                        'html': (rebuilt.get('html') or '') or None,
                        'width': 0,
                        'height': 0,
                        'details': f"来自canvas拦截，lines={rebuilt.get('lineCount')}, items={rebuilt.get('itemCount')} - 方法:auto"
                    }

        # 5) Clipboard interception path (auto mode only)
        if capture_method == "auto":
            _install_clipboard_hooks(frame, logger)
            _try_trigger_copy_buttons(frame, logger)
            clip_text = _read_clipboard_logs(frame, logger)
            if clip_text:
                return {
                    'success': True,
                    'text': clip_text,
                    'html': None,
                    'width': 0,
                    'height': 0,
                    'details': '来自剪贴板拦截(copy/导出) - 方法:auto'
                }

        # 6) Canvas data URL capture (auto and image modes)
        if capture_method in ["auto", "image"]:
            data_url_ret = _capture_canvas_data_url(frame, logger)
            if data_url_ret is not None:
                data_url_ret.update({ 
                    'success': True, 
                    'text': None, 
                    'html': None,
                    'details': f"{data_url_ret.get('details', 'Canvas toDataURL')} - 方法:{capture_method}"
                })
                return data_url_ret

        # 7) Tiled screenshots in iframe (auto and image modes)
        if capture_method in ["auto", "image"]:
            tiled_ret = _capture_tiled_screenshots(frame, iframe_handle, logger)
            if tiled_ret is not None:
                tiled_ret.update({ 
                    'success': True, 
                    'text': None, 
                    'html': None,
                    'details': f"{tiled_ret.get('details', '平铺截图')} - 方法:{capture_method}"
                })
                return tiled_ret

        # 8) Element screenshot fallback (auto and image modes)
        if capture_method in ["auto", "image"]:
            elem_ret = _element_screenshot_fallback(page, frame, logger)
            if elem_ret is not None:
                elem_ret.update({ 
                    'success': True, 
                    'text': None, 
                    'html': None,
                    'details': f"{elem_ret.get('details', '元素截图')} - 方法:{capture_method}"
                })
                return elem_ret

        # Specific error message based on capture method
        if capture_method == "wasm":
            return { 'success': False, 'details': 'WASM方法失败' }
        elif capture_method == "image":
            return { 'success': False, 'details': '所有截图方法均失败' }
        else:
            return { 'success': False, 'details': '所有方法均失败' }
    except Exception as e:
        return { 'success': False, 'details': f'捕获失败: {e}' }


__all__ = [
    'capture_resume_from_chat',
    'CANVAS_TEXT_HOOK_SCRIPT',
    'CANVAS_REBUILD_SCRIPT',
]


def group_text_logs_to_lines(logs: list[dict], y_tolerance: int = 4) -> Dict[str, Any]:
    """Pure-Python grouping of text draw logs into lines.
    Each item in logs is expected to be a dict with keys: t (text), x, y.
    Returns { text, html, lineCount, itemCount } similar to the JS rebuild.
    """
    try:
        safe_logs = []
        for it in logs or []:
            try:
                safe_logs.append({
                    't': str(it.get('t', '')),
                    'x': float(it.get('x', 0) or 0),
                    'y': float(it.get('y', 0) or 0),
                })
            except Exception:
                continue
        safe_logs.sort(key=lambda d: (d['y'], d['x']))

        lines = []
        for it in safe_logs:
            last = lines[-1] if lines else None
            if not last or abs(last['y'] - it['y']) > y_tolerance:
                lines.append({'y': it['y'], 'parts': [it]})
            else:
                last['parts'].append(it)

        def _esc(s: str) -> str:
            return (
                s.replace('&', '&amp;')
                 .replace('<', '&lt;')
                 .replace('>', '&gt;')
            )

        html_lines = []
        text_lines = []
        for line in lines:
            parts = line['parts']
            txt = ''.join(str(p.get('t', '')) for p in parts)
            text_lines.append(txt)
            html_lines.append(f"<div>{_esc(txt)}</div>")

        html = "\n".join(html_lines)
        text = "\n".join(text_lines)
        return {
            'text': text,
            'html': html,
            'lineCount': len(lines),
            'itemCount': len(safe_logs),
        }
    except Exception as e:
        return {
            'text': '',
            'html': '',
            'lineCount': 0,
            'itemCount': 0,
            'error': str(e)
        }
