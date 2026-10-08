import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'render_recipe.py'


class RecipeRenderingTests(unittest.TestCase):
    def setUp(self):
        parent = SCRIPT.parent.parent / '.test-tmp'
        parent.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(parent))
        self.root = Path(self.tmp.name)
        Image.new('RGB', (640, 360), (100, 40, 20)).save(self.root / 'hero.png')
        self.evidence = {
            'source': {'duration_seconds': 30},
            'segments': [{'id': 's001', 'start': 0, 'end': 8, 'text': '番茄两个切块', 'kind': 'subtitle'}],
            'frames': [{'id': 'f001', 'time': 20, 'path': 'hero.png'}],
        }
        self.recipe = {
            'version': 1, 'title': '番茄炒蛋', 'hero': {'frame': 'f001'},
            'ingredients': [{'name': '番茄', 'amount': '2个', 'evidence': ['s001']},
                            {'name': '食用油', 'evidence': ['s001']}],
            'steps': [{'text': '1. 番茄两个切块，鸡蛋打散。', 'evidence': ['s001']},
                      {'text': '2. 油热后炒鸡蛋，凝固后盛出。', 'evidence': ['s001']}],
            'notes': [],
        }

    def tearDown(self):
        self.root.resolve().relative_to(SCRIPT.parent.parent.resolve())
        self.tmp.cleanup()

    def run_cli(self, recipe=None, evidence=None, output='result.png'):
        (self.root / 'recipe.json').write_text(json.dumps(self.recipe if recipe is None else recipe, ensure_ascii=False), encoding='utf-8')
        (self.root / 'evidence.json').write_text(json.dumps(self.evidence if evidence is None else evidence, ensure_ascii=False), encoding='utf-8')
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root / 'recipe.json'),
                               '--evidence', str(self.root / 'evidence.json'),
                               '--out', str(self.root / output), '--width', '640'],
                              capture_output=True, text=True, encoding='utf-8')

    def test_missing_amount_stays_omitted_and_hero_geometry_is_preserved(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(self.root / 'result.png') as img:
            self.assertEqual(img.width, 640)
            self.assertGreater(img.height, 360)
            self.assertEqual(img.getpixel((10, 10)), (100, 40, 20))
        text = (self.root / 'result.md').read_text(encoding='utf-8')
        self.assertIn('番茄：2个', text)
        self.assertIn('食用油', text)
        self.assertNotIn('未知', text)
        self.assertNotIn('毫升', text)
        self.assertNotIn('克', text)

    def test_rejects_missing_evidence_reference(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['evidence'] = ['nonexistent']
        result = self.run_cli(recipe)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'result.png').exists())

    def test_rejects_out_of_range_hero_time(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['frames'][0]['time'] = 99
        self.assertNotEqual(self.run_cli(evidence=evidence).returncode, 0)

    def test_rejects_duplicate_evidence_ids(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['frames'][0]['id'] = 's001'
        self.assertNotEqual(self.run_cli(evidence=evidence).returncode, 0)

    def test_does_not_overwrite_existing_image(self):
        out = self.root / 'result.png'
        out.write_bytes(b'existing artifact')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(out.read_bytes(), b'existing artifact')

    def test_does_not_overwrite_existing_markdown(self):
        out = self.root / 'result.md'
        out.write_text('existing recipe', encoding='utf-8')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertFalse((self.root / 'result.png').exists())

    def test_long_steps_wrap_by_growing_image_without_tiny_font(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['text'] = '番茄切块，鸡蛋打散，先炒鸡蛋再盛出，番茄炒出汁后倒回鸡蛋，轻轻翻匀后盛盘。' * 8
        short = self.run_cli(output='short.png')
        long = self.run_cli(recipe, output='long.png')
        self.assertEqual(short.returncode, 0, short.stderr)
        self.assertEqual(long.returncode, 0, long.stderr)
        with Image.open(self.root / 'short.png') as a, Image.open(self.root / 'long.png') as b:
            self.assertGreater(b.height, a.height + 200)

    def test_rejects_frame_paths_escaping_evidence_directory(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['frames'][0]['path'] = '../hero.png'
        self.assertNotEqual(self.run_cli(evidence=evidence).returncode, 0)

    def test_does_not_display_unknown_amount_in_step_captions(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['text'] = '1. 番茄克数未知，切块。'
        result = self.run_cli(recipe)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'result.png').exists())

    def test_missing_source_error_does_not_echo_material_paths(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['frames'][0]['path'] = 'PERSONAL_PATH_SENTINEL.png'
        result = self.run_cli(evidence=evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PERSONAL_PATH_SENTINEL', result.stderr)
        self.assertNotIn(str(self.root), result.stderr)

    def test_argument_error_does_not_echo_sensitive_input(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'recipe.json', '--evidence', 'evidence.json',
                                 '--out', 'out.png', '--width', 'SECRET_SENTINEL'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SECRET_SENTINEL', result.stderr)

    def test_malformed_json_shape_is_reported_without_traceback(self):
        result = self.run_cli(recipe=[])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn(str(SCRIPT), result.stderr)


if __name__ == '__main__':
    unittest.main()
