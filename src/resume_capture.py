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

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


INLINE_RESUME_SELECTORS = [
    '.resume-box',
    '.resume-content-wrap',
    '.new-resume-online-main-ui',
]

INLINE_SECTION_HEADINGS = [
    '期望职位',
    '工作经历',
    '项目经验',
    '教育经历',
    '教育经理',
    '资格证书',
    '技能标签',
    '自我评价',
]


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


def _format_inline_text(text: str) -> str:
    if not text:
        return ''
    
    # 过滤保护文本
    protection_texts = [
        "为妥善保护牛人在BOSS直聘平台提交、发布、展示的简历",
        "包括但不限于在线简历、附件简历",
        "包括但不限于联系方式、期望职位、教育经历、工作经历等",
        "任何用户原则上仅可出于自身招聘的目的",
        "通过BOSS直聘平台在线浏览牛人简历",
        "未经BOSS直聘及牛人本人书面授权",
        "任何用户不得将牛人在BOSS直聘平台提交、发布、展示的简历中的个人信息",
        "在任何第三方平台进行复制、使用、传播、存储",
        "BOSS直聘平台",
        "个人信息"
    ]
    
    lines = text.splitlines()
    output = []
    for raw in lines:
        trimmed = raw.strip()
        
        # 跳过保护文本
        if trimmed and any(protection_text in trimmed for protection_text in protection_texts):
            continue
            
        if trimmed and any(trimmed.startswith(h) for h in INLINE_SECTION_HEADINGS):
            output.append('')
            output.append(trimmed)
            output.append('---')
        else:
            output.append(raw)
    
    while output and output[-1] == '':
        output.pop()
    formatted = "\n".join(output)
    while "\n\n\n" in formatted:
        formatted = formatted.replace("\n\n\n", "\n\n")
    return formatted.strip("\n")


def _snapshot_inline_resume(page) -> Optional[Dict[str, Any]]:
    try:
        return page.evaluate(
            """
            ({ selectors }) => {
              const list = Array.isArray(selectors) ? selectors : [];
              let target = null;
              for (const sel of list) {
                const node = document.querySelector(sel);
                if (node) { target = node; break; }
              }
              if (!target) return null;
              const rect = target.getBoundingClientRect();
              const closestData = target.closest('[data-props]') || document.querySelector('[data-props]');
              const html = target.innerHTML || '';
              const text = target.innerText || '';
              const dataProps = closestData ? (closestData.getAttribute('data-props') || '') : '';
              const hasResumeItem = !!target.querySelector('.resume-item');
              const hasSectionTitle = !!target.querySelector('.section-title');
              return {
                mode: 'inline',
                selector: target.tagName ? target.tagName.toLowerCase() : null,
                classList: Array.from(target.classList || []),
                childCount: target.childElementCount || 0,
                canvasCount: target.querySelectorAll ? target.querySelectorAll('canvas').length : 0,
                htmlLength: html.length,
                html,
                text,
                dataProps,
                textLength: text.length,
                dataPropsLength: dataProps.length,
                hasResumeItem,
                hasSectionTitle,
                boundingRect: {
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                  top: rect.top,
                  left: rect.left,
                  bottom: rect.bottom,
                  right: rect.right,
                }
              };
            }
            """,
            {"selectors": INLINE_RESUME_SELECTORS},
        )
    except Exception:
        return None


def _inline_snapshot_has_content(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not snapshot:
        return False
    text = (snapshot.get('text') or '').strip()
    if text:
        return True
    data_props = (snapshot.get('dataProps') or '').strip()
    if data_props:
        return True
    if snapshot.get('hasResumeItem') or snapshot.get('hasSectionTitle'):
        return True
    return False


def _extract_inline_snapshot(snapshot: Dict[str, Any], html_limit: int = 0) -> Dict[str, Any]:
    result = dict(snapshot or {})
    text = result.get('text') or ''
    formatted = _format_inline_text(text)
    result['formattedText'] = formatted or text
    trimmed = result['formattedText'] or ''
    snippet = trimmed[:1000]
    if trimmed and len(trimmed) > 1000:
        snippet += '...<truncated>'
    result['textSnippet'] = snippet

    html_content = result.get('html') or ''
    if html_limit and html_limit > 0 and len(html_content) > html_limit:
        result['htmlSnippet'] = html_content[:html_limit] + '...<truncated>'
    else:
        result['htmlSnippet'] = html_content
    return result


def _capture_inline_resume(
    page,
    logger=None,
    html_limit: int = 0,
    *,
    max_attempts: int = 10,
) -> Optional[Dict[str, Any]]:
    for _ in range(max_attempts):
        snapshot = _snapshot_inline_resume(page)
        if _inline_snapshot_has_content(snapshot):
            return _extract_inline_snapshot(snapshot, html_limit)
        time.sleep(0.25)
    return None


def _try_open_online_resume(page, chat_id: str, logger=None) -> Dict[str, Any]:
    """Open the target chat and click the online resume button.
    Returns { success, details } and leaves the UI on the online resume dialog.
    """
    # Close existing overlay if present
    from .chat_utils import close_overlay_dialogs
    closed = close_overlay_dialogs(page, add_notification=lambda msg, level: _log(logger, level, msg))
    if closed:
        _log(logger, "info", "已关闭遮挡的弹出层")

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



def _wait_for_resume_entry(page, timeout_ms: int, logger=None) -> Dict[str, Any]:
    selector = (
        "iframe[src*='c-resume'], "
        ".resume-box"
    )
    try:
        handle = page.wait_for_selector(selector, timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return {'mode': None}

    tag = handle.evaluate("el => el.tagName.toLowerCase()")
    if tag == 'iframe':
        frame = handle.content_frame() or page.frame(url=re.compile(r"/c-resume"))
        return {
            'mode': 'iframe',
            'iframe_handle': handle,
            'frame': frame,
        }

    return {
        'mode': 'inline',
    }


def _frame_is_usable(frame: Optional[Any]) -> bool:
    return frame is not None and not frame.is_detached()


def _get_resume_frame(page, logger=None, timeout_ms: int = 10000):
    start = time.time()
    entry = _wait_for_resume_entry(page, timeout_ms, logger)
    if entry.get('mode') == 'iframe' and _frame_is_usable(entry.get('frame')):
        _log(logger, "info", f"iframe[src*='c-resume'] time: {time.time() - start}")
        return entry.get('iframe_handle'), entry.get('frame')
    return None, None


def prepare_resume_context(
    page,
    chat_id: str,
    logger=None,
    *,
    total_timeout: float = 12000,
    inline_html_limit: int = 20000,
) -> Dict[str, Any]:
    """Prepare resume context by opening resume and detecting mode.

    This is a high-level orchestrator that coordinates the resume preparation process.
    """
    open_result = _try_open_online_resume(page, chat_id, logger)
    if not open_result.get('success'):
        return _create_error_result(open_result, '无法打开在线简历')

    entry = _wait_for_resume_entry(page, total_timeout, logger)
    mode = entry.get('mode')

    if mode == 'inline':
        inline_snapshot = _capture_inline_resume(
            page,
            logger,
            html_limit=inline_html_limit,
            max_attempts=5,
        )
        return {
            'success': True,
            'mode': 'inline',
            'inline': inline_snapshot,
            'openResult': open_result,
        }

    if mode == 'iframe':
        frame = entry.get('frame')
        if _frame_is_usable(frame):
            return {
                'success': True,
                'mode': 'iframe',
                'frame': frame,
                'iframe_handle': entry.get('iframe_handle'),
                'openResult': open_result,
            }
        return _create_error_result(open_result, 'iframe不可用')

    return _create_error_result(open_result, '未找到简历iframe或inline内容')


def _create_error_result(open_result: Dict[str, Any], details: str) -> Dict[str, Any]:
    """Create a standardized error result."""
    return {
        'success': False,
        'mode': None,
        'details': details,
        'openResult': open_result,
    }


def _try_wasm_exports(frame, logger=None) -> Optional[Dict[str, Any]]:
    """Attempt to retrieve structured data from WASM module.
    Returns a dict if found; otherwise None.
    """
    if frame is None:
        return None
    payload = None
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
    """Main resume capture function - orchestrates the capture process.
    
    Args:
        page: Playwright page object
        chat_id: Chat ID to capture resume from
        logger: Optional logger for debug info
        capture_method: Method to use for capture ("auto", "wasm", "image")
    """
    try:
        # Step 1: Validate parameters
        validation_result = _validate_capture_parameters(capture_method, logger)
        if not validation_result['valid']:
            return validation_result['result']

        # Step 2: Get resume context
        context_info = prepare_resume_context(page, chat_id, logger, inline_html_limit=0)
        
        # Step 3: Handle based on resume mode
        if context_info.get('mode') == 'inline':
            return _handle_inline_capture(context_info, capture_method)
        else:
            return _handle_iframe_capture(page, context_info, capture_method, logger)

    except Exception as e:
        return {'success': False, 'details': f'捕获失败: {e}'}


def _validate_capture_parameters(capture_method: str, logger=None) -> Dict[str, Any]:
    """Validate capture method parameters."""
    if capture_method not in ["auto", "wasm", "image"]:
        return {
            'valid': False,
            'result': {'success': False, 'details': f'无效的capture_method: {capture_method}'}
        }
    
    if logger:
        logger.info(f"使用捕获方法: {capture_method}")
    
    return {'valid': True, 'result': None}


def _build_inline_result(
    inline_data: Optional[Dict[str, Any]],
    capture_method: str,
    *,
    details: Optional[str] = None,
) -> Dict[str, Any]:
    inline_data = inline_data or {}
    rect = inline_data.get('boundingRect') or {}
    return {
        'success': True,
        'text': inline_data.get('formattedText') or inline_data.get('text'),
        'html': inline_data.get('htmlSnippet') or inline_data.get('html'),
        'width': int(rect.get('width') or 0),
        'height': int(rect.get('height') or 0),
        'details': details or f"来自inline简历 - 方法:{capture_method}",
    }


def _handle_inline_capture(context_info: Dict[str, Any], capture_method: str) -> Dict[str, Any]:
    """Handle inline resume capture."""
    return _build_inline_result(context_info.get('inline'), capture_method)


def _handle_iframe_capture(page, context_info: Dict[str, Any], capture_method: str, logger=None) -> Dict[str, Any]:
    """Handle iframe resume capture."""
    frame = context_info.get('frame')
    if not frame:
        return {'success': False, 'details': '未找到简历iframe'}

    iframe_handle = context_info.get('iframe_handle') or frame.frame_element() if frame else None

    # Route to specific capture method
    if capture_method == "wasm":
        return _capture_wasm_method(frame, capture_method)
    elif capture_method == "image":
        return _capture_image_method(page, frame, iframe_handle, capture_method, logger)
    else:  # auto method
        return _capture_auto_method(page, frame, iframe_handle, capture_method, logger)


def _capture_wasm_method(frame, capture_method: str) -> Dict[str, Any]:
    """Capture resume using WASM method."""
    wasm_obj = _try_wasm_exports(frame)
    if wasm_obj:
        import json as _json
        text_dump = _json.dumps(wasm_obj, ensure_ascii=False, indent=2)
        return {
            'success': True,
            'text': text_dump,
            'html': None,
            'width': 0,
            'height': 0,
            'details': f'来自WASM导出 - 方法:{capture_method}'
        }
    return {'success': False, 'details': 'WASM方法失败'}


def _compose_details(label: str, payload_details: Optional[str], capture_method: str) -> str:
    base = (payload_details or '').strip()
    if base:
        return f"{base} - 方法:{capture_method}"
    return f"{label} - 方法:{capture_method}"


def _run_image_strategies(
    page,
    frame,
    iframe_handle,
    capture_method: str,
    logger=None,
) -> Optional[Dict[str, Any]]:
    attempts = [
        (
            'Canvas toDataURL',
            lambda: _capture_canvas_data_url(frame, logger),
            _create_image_result,
        ),
        (
            '平铺截图',
            lambda: _capture_tiled_screenshots(frame, iframe_handle, logger),
            _create_tiled_result,
        ),
    ]

    if page is not None:
        attempts.append(
            (
                '容器元素截图',
                lambda: _element_screenshot_fallback(page, frame, logger),
                _create_image_result,
            )
        )

    for label, getter, formatter in attempts:
        payload = getter()
        if payload:
            details = _compose_details(label, payload.get('details'), capture_method)
            return formatter(payload, details)
    return None


def _capture_image_method(page, frame, iframe_handle, capture_method: str, logger=None) -> Dict[str, Any]:
    """Capture resume using image methods."""
    result = _run_image_strategies(page, frame, iframe_handle, capture_method, logger)
    if result:
        return result
    return {'success': False, 'details': '所有截图方法均失败'}


def _capture_auto_method(page, frame, iframe_handle, capture_method: str, logger=None) -> Dict[str, Any]:
    """Capture resume using auto method with multiple fallback strategies."""
    def inline_fallback():
        snapshot = _capture_inline_resume(page, logger, html_limit=0, max_attempts=5)
        if snapshot:
            return _build_inline_result(
                snapshot,
                capture_method,
                details=f"inline简历fallback - 方法:{capture_method}",
            )
        return None

    strategies = [
        lambda: _capture_wasm_method(frame, capture_method),
        lambda: _try_canvas_text_hooks(frame, capture_method, logger),
        lambda: _try_clipboard_hooks(frame, capture_method, logger),
        lambda: _run_image_strategies(page, frame, iframe_handle, capture_method, logger),
        inline_fallback,
    ]

    for attempt in strategies:
        result = attempt()
        if isinstance(result, dict) and result.get('success'):
            return result

    return {'success': False, 'details': '所有方法均失败'}


def _try_canvas_text_hooks(frame, capture_method: str, logger=None) -> Dict[str, Any]:
    """Try canvas text hooks method."""
    hooked = _install_canvas_text_hooks(frame, logger)
    if hooked:
        rebuilt = _rebuild_text_from_logs(frame, logger)
        if rebuilt and (rebuilt.get('text') or rebuilt.get('html')):
            return {
                'success': True,
                'text': rebuilt.get('text'),
                'html': rebuilt.get('html'),
                'width': 0,
                'height': 0,
                'details': f"Canvas拦截 - 方法:{capture_method}"
            }
    return {'success': False, 'details': 'Canvas拦截失败'}


def _try_clipboard_hooks(frame, capture_method: str, logger=None) -> Dict[str, Any]:
    """Try clipboard hooks method."""
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
            'details': f'剪贴板拦截 - 方法:{capture_method}'
        }
    return {'success': False, 'details': '剪贴板拦截失败'}


def _create_image_result(data_url_ret: Dict[str, Any], details: str) -> Dict[str, Any]:
    """Create standardized image result."""
    return {
        'success': True,
        'text': None,
        'html': None,
        'image_base64': data_url_ret.get('image_base64'),
        'data_url': data_url_ret.get('data_url'),
        'width': data_url_ret.get('width', 0),
        'height': data_url_ret.get('height', 0),
        'details': details
    }


def _create_tiled_result(tiled_ret: Dict[str, Any], details: str) -> Dict[str, Any]:
    """Create standardized tiled result."""
    return {
        'success': True,
        'text': None,
        'html': None,
        'images_base64': tiled_ret.get('images_base64', []),
        'width': tiled_ret.get('width', 0),
        'height': tiled_ret.get('height', 0),
        'details': details
    }


__all__ = [
    # Main public functions
    'capture_resume_from_chat',      # Primary resume capture function
    'prepare_resume_context',        # Resume context preparation
    'group_text_logs_to_lines',      # Text log processing utility
    
    # JavaScript constants for external use
    'CANVAS_TEXT_HOOK_SCRIPT',       # Canvas text hooking JavaScript
    'CANVAS_REBUILD_SCRIPT',         # Canvas text rebuilding JavaScript
    
    # Selector constants
    'INLINE_RESUME_SELECTORS',       # CSS selectors for inline resumes
    'INLINE_SECTION_HEADINGS',       # Section heading patterns
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
