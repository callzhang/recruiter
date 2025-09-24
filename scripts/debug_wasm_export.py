#!/usr/bin/env python3
"""Deep WASM resume debug helper with structured logging."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.resume_capture import (  # noqa: E402
    _build_inline_result,
    _capture_auto_method,
    _capture_canvas_data_url,
    _capture_tiled_screenshots,
    _install_canvas_text_hooks,
    _install_clipboard_hooks,
    _read_clipboard_logs,
    _rebuild_text_from_logs,
    _try_trigger_copy_buttons,
    _try_wasm_exports,
    capture_resume_from_chat,
    prepare_resume_context,
)

CaptureFn = Callable[[str, Optional[Any]], None]


def _safe_preview(payload: Any, limit: int = 1000) -> str:
    """Create a safe preview of payload with proper newline handling."""
    def _process_string(s: str) -> str:
        """Process a string value, escaping newlines and truncating if needed."""
        if len(s) > limit:
            s = s[:limit] + "..."
        # Replace actual newlines with visible \n for better readability
        return s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    
    def _process_value(value):
        """Process a single value."""
        if isinstance(value, str):
            return _process_string(value)
        elif isinstance(value, dict):
            return {k: _process_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_process_value(item) for item in value]
        else:
            return _process_string(str(value))
    
    try:
        processed = _process_value(payload)
        return json.dumps(processed, ensure_ascii=False, indent=2)
    except Exception:
        return _process_string(str(payload))


def _print_step(title: str, payload: Optional[Any] = None) -> None:
    print(f"\n=== {title} ===")
    if payload is None:
        print('(Empty payload)')
        return
    
    preview = _safe_preview(payload)
    print(preview)


class _StdoutLogger:
    def info(self, msg: str) -> None:
        print(f"[INFO] {msg}")

    def error(self, msg: str) -> None:
        print(f"[ERROR] {msg}")

    def warning(self, msg: str) -> None:
        print(f"[WARNING] {msg}")


@contextmanager
def _playwright_connection() -> Iterable[Tuple[Any, Browser]]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(settings.CDP_URL)
        try:
            yield playwright, browser
        finally:
            pass  # 浏览器由外部生命周期管理


def _setup_wasm_route(context) -> None:
    """如果启用且本地存在 wasm 文件，则用它替换远程资源."""
    local_wasm = ROOT / 'wasm' / 'wasm_canvas-1.0.2-5030.js'
    if not local_wasm.exists():
        print("Local wasm_canvas-1.0.2-5030.js not found, skipping route")
        return

    pattern = r"*wasm_canvas-.*\\.js"

    def _route_resume(route, request):
        if request.method.upper() != 'GET':
            return route.continue_()
        return route.fulfill(
            path=str(local_wasm),
            content_type='application/javascript; charset=utf-8',
        )

    try:
        context.unroute(pattern)
    except Exception:
        pass
    context.route(pattern, _route_resume)


def _navigate_to_chat(page: Page, capture: CaptureFn) -> None:
    if settings.CHAT_URL in (page.url or ''):
        return
    try:
        page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception as err:
        capture("导航错误", {"error": str(err)})


def _get_first_chat_id(page: Page, capture: CaptureFn) -> Optional[str]:
    try:
        first_item = page.locator("div.geek-item").first
        first_item.wait_for(state="visible", timeout=3000)
        chat_id = first_item.get_attribute("data-id") or first_item.get_attribute("id")
        capture("获取聊天ID", {"chat_id": chat_id})
        return chat_id
    except Exception as err:
        capture("获取聊天ID失败", {"error": str(err)})
        return None


def _validate_chat_id(page: Page, chat_id: str, capture: CaptureFn) -> bool:
    """Validate that the provided chat_id exists on the page."""
    try:
        # Try to find the chat item with the provided ID
        chat_item = page.locator(f"div.geek-item[data-id='{chat_id}'], div.geek-item[id='{chat_id}']").first
        if chat_item.count() > 0:
            capture("验证聊天ID", {"chat_id": chat_id, "status": "found"})
            return True
        else:
            capture("验证聊天ID", {"chat_id": chat_id, "status": "not_found"})
            return False
    except Exception as e:
        capture("验证聊天ID失败", {"chat_id": chat_id, "error": str(e)})
        return False


def _run_debug_step(capture: CaptureFn, title: str, runner: Callable[[], Dict[str, Any]]) -> None:
    try:
        payload = runner()
    except Exception as err:
        payload = {"error": str(err)}
    capture(title, payload)


def _wasm_debug(frame) -> Dict[str, Any]:
    data = _try_wasm_exports(frame)
    return {
        "success": data is not None,
        "method": "resume_capture._try_wasm_exports",
        "data": data,
    }


def _canvas_text_debug(frame) -> Dict[str, Any]:
    hooked = _install_canvas_text_hooks(frame)
    rebuilt = _rebuild_text_from_logs(frame) if hooked else None
    return {
        "hooked": bool(hooked),
        "rebuilt": rebuilt,
        "method": "resume_capture._install_canvas_text_hooks + _rebuild_text_from_logs",
    }


def _clipboard_debug(frame) -> Dict[str, Any]:
    _install_clipboard_hooks(frame)
    _try_trigger_copy_buttons(frame)
    clip_text = _read_clipboard_logs(frame)
    preview = None
    if clip_text:
        preview = clip_text[:2000] + ("...<truncated>" if len(clip_text) > 2000 else '')
    return {
        "method": "resume_capture._install_clipboard_hooks + _read_clipboard_logs",
        "has_text": bool(clip_text),
        "textPreview": preview,
    }


def _summarize_image(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not payload:
        return {"success": False}
    summary: Dict[str, Any] = {
        "success": True,
        "width": payload.get('width'),
        "height": payload.get('height'),
        "details": payload.get('details'),
    }
    image_base64 = payload.get('image_base64')
    images_base64 = payload.get('images_base64')
    if image_base64:
        summary['image_base64_length'] = len(image_base64)
    if images_base64:
        summary['slice_count'] = len(images_base64)
        summary['slice_lengths'] = [len(it) for it in images_base64[:3]]
        if len(images_base64) > 3:
            summary['slice_lengths'].append('...')
    return summary


def _image_debug(frame, iframe_handle) -> Dict[str, Any]:
    return {
        "method": "resume_capture._capture_canvas_data_url/_capture_tiled_screenshots",
        "canvas": _summarize_image(_capture_canvas_data_url(frame)),
        "tiled": _summarize_image(_capture_tiled_screenshots(frame, iframe_handle)),
    }


def _primary_capture(context_info: Dict[str, Any], page: Page) -> Dict[str, Any]:
    mode = context_info.get('mode')
    if mode == 'inline':
        inline_snapshot = context_info.get('inline') or {}
        result = _build_inline_result(inline_snapshot, 'auto')
        text = result.get('text') or ''
        if text:
            result['textLength'] = len(text)
            result['textPreview'] = text[:1000] + ("...<truncated>" if len(text) > 1000 else '')
        result['mode'] = 'inline'
        return result

    if mode == 'iframe':
        frame = context_info.get('frame')
        if not frame:
            return {'success': False, 'details': 'iframe frame missing', 'mode': 'iframe'}
        iframe_handle = context_info.get('iframe_handle') or frame.frame_element()
        result = _capture_auto_method(page, frame, iframe_handle, 'auto', _StdoutLogger())
        result['mode'] = 'iframe'
        return result

    return {'success': False, 'details': '未知模式', 'mode': mode}


def _emit_iframe_diagnostics(frame, iframe_handle, capture: CaptureFn) -> None:
    try:
        frame_meta = {
            "url": getattr(frame, "url", None),
            "name": getattr(frame, "name", None),
            "is_detached": getattr(frame, "is_detached", lambda: None)(),
        }
    except Exception:
        frame_meta = {"repr": repr(frame)}
    capture("iframe信息", frame_meta)

    steps: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
        ("WASM导出", lambda: _wasm_debug(frame)),
        ("Canvas文本钩子", lambda: _canvas_text_debug(frame)),
        ("剪贴板钩子", lambda: _clipboard_debug(frame)),
        ("截图方法", lambda: _image_debug(frame, iframe_handle)),
    ]

    for title, runner in steps:
        _run_debug_step(capture, title, runner)


def _final_test(page: Page, chat_id: str, capture: CaptureFn) -> None:
    logger = _StdoutLogger()
    for method in ("auto", "wasm", "image"):
        result = capture_resume_from_chat(page, chat_id, logger=logger, capture_method=method)
        capture(
            f"主捕获方法 ({method})",
            {
                "success": result.get('success'),
                "details": result.get('details'),
                "method": f"resume_capture.capture_resume_from_chat({method})",
            },
        )


def _save_results(output_path: pathlib.Path, results: List[Dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n保存调试输出到 {output_path}")
    except Exception as err:
        print(f"保存调试输出失败: {err}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deep WASM resume debug helper",
        epilog="Examples:\n"
               "  python debug_wasm_export.py                    # Use first available chat\n"
               "  python debug_wasm_export.py --chat-id abc123   # Test specific chat ID\n"
               "  python debug_wasm_export.py --final-test       # Run all capture methods",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output",
        default=str((ROOT / 'scripts' / 'debug_wasm_export_output.json').resolve()),
        help="Path for JSON output",
    )
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to sleep before finishing")
    parser.add_argument(
        "--final-test",
        action="store_true",
        help="Run capture_resume_from_chat for all modes at the end",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        help="Specific chat ID to test (if not provided, will use the first available chat)",
    )
    parser.add_argument(
        "--use-local-wasm",
        action="store_true",
        help="Serve local wasm_canvas bundle (behaves differently from production)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    results: List[Dict[str, Any]] = []
    start = time.time()

    def capture(title: str, payload: Optional[Any] = None) -> None:
        elapsed = time.time() - start
        record = {"title": title, "payload": payload, "elapsed": elapsed}
        results.append(record)
        _print_step(f"{title} (t+{elapsed:.2f}s)", payload)

    with _playwright_connection() as (_, browser):
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        if args.use_local_wasm:
          _setup_wasm_route(context)

        _navigate_to_chat(page, capture)

        # Use provided chat_id or get the first available one
        if args.chat_id:
            chat_id = args.chat_id
            capture("使用提供的聊天ID", {"chat_id": chat_id})
            # Validate that the provided chat_id exists
            if not _validate_chat_id(page, chat_id, capture):
                capture("错误", {"message": f"提供的聊天ID '{chat_id}' 在页面上未找到"})
                _save_results(pathlib.Path(args.output), results)
                return
        else:
            chat_id = _get_first_chat_id(page, capture)
            if not chat_id:
                _save_results(pathlib.Path(args.output), results)
                return

        context_info = prepare_resume_context(
            page,
            chat_id,
            _StdoutLogger(),
            total_timeout=12000,
            inline_html_limit=20000,
        )

        if not context_info or not context_info.get('success'):
            capture(
                "简历获取失败",
                {
                    "error": (context_info or {}).get('details') or '未找到简历内容',
                    "mode": (context_info or {}).get('mode'),
                },
            )
            _save_results(pathlib.Path(args.output), results)
            return

        primary = _primary_capture(context_info, page)
        capture("主捕获(auto)", primary)

        if primary.get('mode') == 'iframe':
            frame = context_info.get('frame')
            if not frame:
                capture("iframe错误", {"error": "iframe frame missing"})
            else:
                iframe_handle = context_info.get('iframe_handle') or frame.frame_element()
                _emit_iframe_diagnostics(frame, iframe_handle, capture)

        if args.wait > 0:
            time.sleep(args.wait)

        if args.final_test:
            _final_test(page, chat_id, capture)

    _save_results(pathlib.Path(args.output), results)


if __name__ == "__main__":
    main()
