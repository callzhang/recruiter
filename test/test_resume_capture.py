import unittest
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.resume_capture import group_text_logs_to_lines, _try_wasm_exports


class DummyFrame:
    def __init__(self, data):
        self._data = data
        self.last_script = None

    def evaluate(self, script):
        self.last_script = script
        # Emulate the structure returned by the browser snippet
        return { 'data': self._data, 'error': None, 'attempts': [] }


class DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


logger = DummyLogger()


class TestResumeCaptureGrouping(unittest.TestCase):
    def test_grouping_basic(self):
        logs = [
            { 't': 'Hello', 'x': 10, 'y': 20 },
            { 't': ' ', 'x': 50, 'y': 20 },
            { 't': 'World', 'x': 60, 'y': 20 },
            { 't': 'Next', 'x': 10, 'y': 40 },
        ]
        out = group_text_logs_to_lines(logs, y_tolerance=3)
        self.assertIn('text', out)
        self.assertEqual(out['lineCount'], 2)
        self.assertIn('Hello World', out['text'])
        self.assertTrue(out['text'].split('\n')[1].startswith('Next'))

    def test_empty(self):
        out = group_text_logs_to_lines([], y_tolerance=4)
        self.assertEqual(out['lineCount'], 0)
        self.assertEqual(out['itemCount'], 0)
        self.assertEqual(out['text'], '')

    def test_wasm_export(self):
        fake_data = { 'name': '测试', 'position': '后端开发' }
        frame = DummyFrame(fake_data)
        wasm_obj = _try_wasm_exports(frame, logger)
        self.assertEqual(wasm_obj, fake_data)
        self.assertTrue('data-props' in frame.last_script or 'async' in frame.last_script)


if __name__ == '__main__':
    unittest.main()
