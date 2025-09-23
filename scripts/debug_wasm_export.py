#!/usr/bin/env python3
"""Deep WASM resume debug helper."""

import argparse
import json
import pathlib
import sys
import time
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.resume_capture import _try_open_online_resume, capture_resume_from_chat  # noqa: E402


def _safe_preview(payload, limit=2000):
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        text = repr(payload)
    if len(text) > limit:
        text = text[:limit] + "...<truncated>"
    return text


def _print_step(title, payload=None):
    print(f"\n=== {title} ===")
    if payload is None:
        return
    if isinstance(payload, (dict, list, tuple)):
        print(_safe_preview(payload))
    else:
        print(payload)


class _StdoutLogger:
    def info(self, msg):
        print(f"[INFO] {msg}")

    def error(self, msg):
        print(f"[ERROR] {msg}")

    def warning(self, msg):
        print(f"[WARN] {msg}")


@contextmanager
def _playwright_connection():
    pw = sync_playwright().start()
    browser = None
    try:
        browser = pw.chromium.connect_over_cdp(settings.CDP_URL)
        yield pw, browser
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        pw.stop()


def _wait_for_resume_frame(page, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            page.wait_for_selector("iframe[src*='c-resume']", timeout=1000)
        except Exception:
            pass
        frame = page.frame(lambda f: f.url and 'c-resume' in f.url)
        if frame:
            return frame
    return None


def _step_direct_global(frame):
    return frame.evaluate(
        """
        () => {
          const info = {
            hasGlobalGetter: typeof get_export_geek_detail_info === 'function',
          };
          if (info.hasGlobalGetter) {
            try {
              info.data = get_export_geek_detail_info();
            } catch (err) {
              info.error = String(err);
            }
          }
          return info;
        }
        """
    )


def _step_keyword_scan(frame, keywords=None):
    keywords = keywords or ['wasm', 'resume', 'geek', 'canvas', 'export']
    return frame.evaluate(
        """
        (patterns) => {
          const response = { allKeysCount: 0, sampledKeys: [], matches: [] };
          try {
            const lowerPatterns = (patterns || []).map((p) => String(p).toLowerCase());
            const keys = Object.getOwnPropertyNames(window || {});
            response.allKeysCount = keys.length;
            response.sampledKeys = keys.slice(0, 50);
            const matches = [];
            for (const key of keys) {
              const lower = key.toLowerCase();
              if (lowerPatterns.some((pat) => lower.includes(pat))) {
                let value;
                try {
                  value = window[key];
                } catch (_) {
                  continue;
                }
                matches.push({
                  key,
                  type: typeof value,
                  tag: Object.prototype.toString.call(value)
                });
              }
            }
            matches.sort((a, b) => a.key.localeCompare(b.key));
            response.matches = matches.slice(0, 200);
          } catch (err) {
            response.error = String(err);
          }
          return response;
        }
        """,
        keywords,
    )


def _step_window_modules(frame):
    return frame.evaluate(
        """
        () => {
          const hits = [];
          for (const key of Object.getOwnPropertyNames(window || {})) {
            let val;
            try {
              val = window[key];
            } catch (_) {
              continue;
            }
            if (!val || (typeof val !== 'object' && typeof val !== 'function')) continue;
            const hasRegister = typeof val.register_js_callback === 'function';
            const hasTrigger = typeof val.trigger_rust_callback === 'function';
            const hasGetter = typeof val.get_export_geek_detail_info === 'function';
            if (hasRegister || hasTrigger || hasGetter) {
              hits.push({ key, hasRegister, hasTrigger, hasGetter, type: Object.prototype.toString.call(val) });
            }
          }
          hits.sort((a, b) => a.key.localeCompare(b.key));
          return hits;
        }
        """
    )


def _step_probe_module(frame, key):
    return frame.evaluate(
        """
        async (moduleKey) => {
          const outcome = { moduleKey };
          try {
            const mod = window[moduleKey];
            if (!mod) {
              outcome.missing = true;
              return outcome;
            }
            outcome.type = Object.prototype.toString.call(mod);

            try {
              if (typeof mod.default === 'function') {
                await mod.default();
                outcome.defaultInvoked = true;
              }
            } catch (err) {
              outcome.defaultError = String(err);
            }

            const store = (window.__resume_data_store = window.__resume_data_store || {});

            if (typeof mod.register_js_callback === 'function') {
              try {
                mod.register_js_callback('export_geek_detail_info', (d) => { store.export_geek_detail_info = d; });
                mod.register_js_callback('geek_detail_info', (d) => { store.geek_detail_info = d; });
                outcome.callbacksRegistered = true;
              } catch (err) {
                outcome.callbackError = String(err);
              }
            }

            if (typeof mod.get_export_geek_detail_info === 'function') {
              try {
                outcome.direct = mod.get_export_geek_detail_info();
              } catch (err) {
                outcome.directError = String(err);
              }
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
              outcome.triggerAttempts = [];
              for (const name of triggerNames) {
                for (const payload of triggerPayloads) {
                  try {
                    const result = mod.trigger_rust_callback(name, payload);
                    outcome.triggerAttempts.push({ name, payloadDescription: typeof payload, ok: true, result });
                  } catch (err) {
                    outcome.triggerAttempts.push({ name, payloadDescription: typeof payload, error: String(err) });
                  }
                }
              }
            }

            await new Promise((resolve) => setTimeout(resolve, 50));
            const dataStore = store.export_geek_detail_info || store.geek_detail_info;
            if (dataStore) {
              outcome.store = dataStore;
            }
          } catch (err) {
            outcome.error = String(err);
          }
          return outcome;
        }
        """,
        key,
    )


def _step_collect_resources(frame):
    return frame.evaluate(
        """
        () => {
          const scripts = Array.from(document.querySelectorAll('script[src]')).map((s) => s.src);
          const modulePreloads = Array.from(document.querySelectorAll("link[rel='modulepreload'][href]")).map((l) => l.href);
          return { scripts, modulePreloads };
        }
        """
    )


def _derive_candidate_urls(resource_info):
    candidates = set()
    for url in resource_info.get('scripts', []):
        if not url:
            continue
        lower = url.lower()
        if 'wasm' in lower and 'canvas' in lower and lower.endswith('.js'):
            candidates.add(url)
        elif lower.endswith('.js') and 'index' in lower:
            base = url.rsplit('/', 1)[0]
            candidates.add(f"{base}/wasm_canvas-1.0.2-5030.js")
    for url in resource_info.get('modulePreloads', []):
        if not url:
            continue
        lower = url.lower()
        if 'wasm' in lower and 'canvas' in lower:
            candidates.add(url)
    version = '1.0.2-5030'
    candidates.add(f"https://static.zhipin.com/assets/zhipin/wasm/resume/wasm_canvas-{version}.js")
    candidates.add(f"https://static.zhipin.com/zhipin-boss/wasm-resume-container/v134/assets/wasm_canvas-{version}.js")
    return sorted(candidates)


def _step_import_module(frame, url):
    return frame.evaluate(
        """
        async (moduleUrl) => {
          const outcome = { moduleUrl };
          try {
            const mod = await import(moduleUrl);
            outcome.imported = true;
            outcome.keys = Object.keys(mod || {});
            if (typeof mod.default === 'function') {
              try {
                await mod.default();
                outcome.defaultInvoked = true;
              } catch (err) {
                outcome.defaultError = String(err);
              }
            }
            if (mod && typeof mod.register_js_callback === 'function') {
              const store = (window.__resume_data_store = window.__resume_data_store || {});
              try {
                mod.register_js_callback('export_geek_detail_info', (d) => { store.export_geek_detail_info = d; });
                mod.register_js_callback('geek_detail_info', (d) => { store.geek_detail_info = d; });
                outcome.callbacksRegistered = true;
              } catch (err) {
                outcome.callbackError = String(err);
              }
            }
            if (mod && typeof mod.get_export_geek_detail_info === 'function') {
              try {
                outcome.direct = mod.get_export_geek_detail_info();
              } catch (err) {
                outcome.directError = String(err);
              }
            }
            const triggerPayloads = [undefined, null, '', 'null', '{}', '[]', { force: true }, []];
            const triggerNames = [
              'export_geek_detail_info',
              'geek_detail_info',
              'export_resume_detail_info',
              'resume_detail',
              'geek_detail',
            ];

            if (mod && typeof mod.trigger_rust_callback === 'function') {
              outcome.triggerAttempts = [];
              for (const name of triggerNames) {
                for (const payload of triggerPayloads) {
                  try {
                    const result = mod.trigger_rust_callback(name, payload);
                    outcome.triggerAttempts.push({ name, payloadDescription: typeof payload, ok: true, result });
                  } catch (err) {
                    outcome.triggerAttempts.push({ name, payloadDescription: typeof payload, error: String(err) });
                  }
                }
              }
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
            const store = window.__resume_data_store || {};
            const dataStore = store.export_geek_detail_info || store.geek_detail_info;
            if (dataStore) {
              outcome.store = dataStore;
            }
          } catch (err) {
            outcome.error = String(err);
          }
          return outcome;
        }
        """,
        url,
    )


def _step_fetch_script_snippet(frame, url, limit=2000):
    return frame.evaluate(
        """
        async ({ targetUrl, sizeLimit }) => {
          try {
            const res = await fetch(targetUrl, { credentials: 'include' });
            const text = await res.text();
            return {
              ok: res.ok,
              status: res.status,
              length: text.length,
              snippet: text.slice(0, sizeLimit)
            };
          } catch (err) {
            return { error: String(err) };
          }
        }
        """,
        { "targetUrl": url, "sizeLimit": limit },
    )


def _step_fetch_store(frame):
    return frame.evaluate(
        """
        () => {
          const store = window.__resume_data_store || null;
          return {
            hasStore: !!store,
            exportKeys: store ? Object.keys(store || {}) : [],
            data: store,
          };
        }
        """
    )


def _step_other_fields(frame):
    return frame.evaluate(
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


def _parse_args():
    parser = argparse.ArgumentParser(description="Deep WASM resume debug helper")
    parser.add_argument("--output", default=str((ROOT / 'scripts' / 'debug_wasm_export_output.json').resolve()), help="Path for JSON output")
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to sleep before capture (manual prep)")
    return parser.parse_args()


def main():
    args = _parse_args()
    results = []

    def capture(title, payload=None):
        record = {"title": title, "payload": payload}
        results.append(record)
        _print_step(title, payload)

    with _playwright_connection() as (pw, browser):
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            print("No active context found. Ensure the external browser exposed over CDP is running.")
            sys.exit(1)

        pages = context.pages
        if not pages:
            print("No open pages detected in the connected browser.")
            sys.exit(1)

        local_wasm = ROOT / 'wasm' / 'wasm_canvas-1.0.2-5030.js'
        if local_wasm.exists():
            def _route_resume(route, request):
                if request.method.upper() != 'GET':
                    return route.continue_()
                return route.fulfill(path=str(local_wasm), content_type='application/javascript; charset=utf-8')

            pattern = r"*wasm_canvas-.*\.js"
            context.unroute(pattern)
            context.route(pattern, _route_resume)
        else:
            print("Local wasm_canvas-1.0.2-5030.js not found. Skipping route.")

        page = pages[0]
        try:
            current_url = page.url or ''
        except Exception:
            current_url = ''
        if settings.CHAT_URL not in current_url:
            try:
                page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            except Exception as nav_err:
                capture("Step 0: navigation", {"error": str(nav_err)})

        fallback_info = {"used": False}
        try:
            first_item = page.locator("div.geek-item").first
            first_item.wait_for(state="visible", timeout=3000)
            fallback_info["itemId"] = first_item.get_attribute("data-id") or first_item.get_attribute("id")
            first_item.click()
            try:
                page.wait_for_timeout(300)
            except Exception:
                pass
            btn = page.locator("a.resume-btn-online").first
            btn.wait_for(state="visible", timeout=3000)
            btn.click()
            fallback_info.update({"used": True, "details": "Opened first chat item"})
        except Exception as fallback_err:
            fallback_info.update({"error": str(fallback_err)})
        capture("Step 0: open resume", fallback_info)

        frame = None
        for _ in range(3):
            frame = _wait_for_resume_frame(page, timeout=10.0)
            if frame:
                break
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
        if not frame:
            print("Unable to locate resume iframe automatically. Please open the resume manually in the connected browser and re-run.")
            return

        capture("Step 1: Direct global getter", _step_direct_global(frame))
        capture("Step 1b: Keyword window scan", _step_keyword_scan(frame))

        module_hits = _step_window_modules(frame)
        capture("Step 2: window module candidates", module_hits)

        for idx, hit in enumerate(module_hits):
            if idx >= 10:
                print("...skipping remaining module candidates for brevity")
                break
            outcome = _step_probe_module(frame, hit['key'])
            capture(f"Step 3.{idx+1}: probe window.{hit['key']}", outcome)
            if outcome.get('store') or outcome.get('direct'):
                break

        resource_info = _step_collect_resources(frame)
        capture("Step 4: collected script resources", resource_info)

        candidate_urls = _derive_candidate_urls(resource_info)
        capture("Step 5: derived candidate module URLs", candidate_urls)

        for url in candidate_urls[:6]:
            frame = _wait_for_resume_frame(page)
            if not frame:
                capture(f"Step 5b: fetch snippet {url}", {"error": "resume iframe detached"})
                break
            try:
                capture(f"Step 5b: fetch snippet {url}", _step_fetch_script_snippet(frame, url))
            except Exception as err:
                capture(f"Step 5b: fetch snippet {url}", {"error": str(err)})
                frame = _wait_for_resume_frame(page)
                if not frame:
                    break
            try:
                outcome = _step_import_module(frame, url)
            except Exception as err:
                frame = _wait_for_resume_frame(page)
                if not frame:
                    capture(f"Step 6: import {url}", {"error": "resume iframe detached"})
                    break
                outcome = {"error": str(err)}
            capture(f"Step 6: import {url}", outcome)
            if outcome.get('store') or outcome.get('direct'):
                break

        frame = _wait_for_resume_frame(page)
        if not frame:
            capture("Step 6b: other fields", {"error": "resume iframe detached"})
            return
        capture("Step 6b: other fields", _step_other_fields(frame))

        store_snapshot = _step_fetch_store(frame)
        capture("Final store snapshot", store_snapshot)

        if args.wait > 0:
            time.sleep(args.wait)

        capture("capture_resume_from_chat", capture_resume_from_chat(page, args.chat_id, logger=_StdoutLogger()))

    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\nSaved detailed debug output to {output_path}")
    except Exception as err:
        print(f"Failed to write debug output: {err}")


if __name__ == "__main__":
    main()
