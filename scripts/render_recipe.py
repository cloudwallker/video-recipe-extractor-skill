"""Render one real video frame with compact, caption-like recipe steps."""
import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


def read_json(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' 必须是非空文字')
    return value.strip()


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' 必须是有限数字')
    return value


def validate(recipe, evidence):
    if not isinstance(recipe, dict) or not isinstance(evidence, dict):
        raise ValueError('菜谱和证据 JSON 顶层必须是对象')
    if recipe.get('version') != 1:
        raise ValueError('recipe.version 必须是 1')
    title = nonempty(recipe.get('title'), 'title')
    if '未知' in title or '未说明' in title:
        raise ValueError('成品文字不显示未知，请省略没有依据的用量')
    duration = evidence.get('source', {}).get('duration_seconds')
    if duration is not None and finite_number(duration, 'duration_seconds') <= 0:
        raise ValueError('视频时长必须大于零')
    index = {}
    for field in ('segments', 'frames'):
        for item in evidence.get(field, []):
            key = nonempty(item.get('id'), 'evidence.id')
            if key in index:
                raise ValueError('证据 ID 重复')
            start = item.get('time') if field == 'frames' else item.get('start')
            end = start if field == 'frames' else item.get('end')
            finite_number(start, '证据.start')
            finite_number(end, '证据.end')
            if start < 0 or end < start or (duration is not None and end > duration + 0.05):
                raise ValueError('证据时间越界')
            index[key] = item
    frame_id = recipe.get('hero', {}).get('frame')
    if frame_id not in index or 'path' not in index[frame_id]:
        raise ValueError('hero.frame 必须引用真实帧 ID')
    steps = recipe.get('steps')
    if not isinstance(steps, list) or not steps:
        raise ValueError('至少需要一个步骤')
    for label, items in [('steps', steps), ('ingredients', recipe.get('ingredients', [])),
                         ('notes', recipe.get('notes', []))]:
        if not isinstance(items, list):
            raise ValueError(label + ' 必须是数组')
        for item in items:
            content = nonempty(item.get('name' if label == 'ingredients' else 'text'), label)
            if label == 'steps' and ('未知' in content or '未说明' in content):
                raise ValueError('成品文字不显示未知，请省略没有依据的用量')
            refs = item.get('evidence')
            if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in index for r in refs):
                raise ValueError(label + ' 缺少有效证据引用')
            if label == 'ingredients' and 'amount' in item:
                amount = nonempty(item['amount'], 'amount')
                if '未知' in amount or '未说明' in amount:
                    raise ValueError('没有用量时省略 amount，不输出未知')
    return index


def choose_font(explicit=None):
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ValueError('指定字体不存在')
        return str(path)
    candidates = [
        'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
        '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Medium.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    raise ValueError('未找到中文字体，请用 --font 指定 CJK TTF/OTF/TTC 字体')


def wrap_text(text, font, max_width):
    """Keep font size fixed; expand the row when captions need multiple lines."""
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines = []
    current = ''
    for char in text:
        if char == '\n':
            lines.append(current)
            current = ''
        elif current and draw.textlength(current + char, font=font) > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current += char
    if current:
        lines.append(current.rstrip())
    return lines or ['']


def draw_caption(canvas, text_lines, box, font, font_size, stroke):
    draw = ImageDraw.Draw(canvas)
    x, y, width, height = box
    line_height = math.ceil(font_size * 1.4)
    top = y + (height - line_height * len(text_lines)) / 2
    for i, text in enumerate(text_lines):
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        px = x + (width - text_width) / 2 - bounds[0]
        py = top + i * line_height + (line_height - text_height) / 2 - bounds[1]
        draw.text((px, py), text, font=font, fill='white',
                  stroke_width=stroke, stroke_fill='black')


def timestamp(seconds):
    seconds = int(seconds)
    return '{:02d}:{:02d}:{:02d}'.format(seconds // 3600, seconds // 60 % 60, seconds % 60)


def markdown(recipe, index):
    def refs(ids):
        return '、'.join('{} ({})'.format(key, timestamp(index[key].get('time', index[key].get('start', 0)))) for key in ids)
    lines = ['# ' + recipe['title'], '', '版式：一张视频主图 + 文字步骤；文字为根据视频整理的后期菜谱。', '']
    if recipe.get('ingredients'):
        lines += ['## 食材', '']
        for item in recipe['ingredients']:
            amount = '：' + item['amount'] if item.get('amount') else ''
            lines.append('- ' + item['name'] + amount)
        lines.append('')
    lines += ['## 做法', '']
    for step in recipe['steps']:
        lines += [step['text'], '', '依据：' + refs(step['evidence']), '']
    if recipe.get('notes'):
        lines += ['## 核对备注', '']
        lines += ['- {}（{}）'.format(item['text'], refs(item['evidence'])) for item in recipe['notes']]
    lines += ['', '主图：' + refs([recipe['hero']['frame']]), '']
    return '\n'.join(lines)


def render(recipe_path, evidence_path, output, width=1440, font_path=None,
           font_size=None, hero_bottom=1.0, band_center=0.85):
    recipe = read_json(recipe_path)
    evidence = read_json(evidence_path)
    index = validate(recipe, evidence)
    if not 320 <= width <= 4096:
        raise ValueError('width 范围为 320–4096')
    if not 0.2 <= hero_bottom <= 1 or not 0 <= band_center <= 1:
        raise ValueError('hero-bottom 范围为 0.2–1，band-center 范围为 0–1')
    output = Path(output)
    if output.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
        raise ValueError('输出格式必须是 JPG 或 PNG')
    companions = [output, output.with_suffix('.md'), output.with_suffix('.layout.json')]
    if any(path.exists() for path in companions):
        raise ValueError('输出已存在，请选择新文件名')
    root = Path(evidence_path).resolve().parent
    relative = Path(index[recipe['hero']['frame']]['path'])
    if relative.is_absolute():
        raise ValueError('帧路径必须相对于 evidence.json')
    source = (root / relative).resolve()
    try:
        source.relative_to(root)
    except ValueError:
        raise ValueError('帧路径不能离开证据目录')
    with Image.open(source) as opened:
        hero = opened.convert('RGB')
    hero = hero.crop((0, 0, hero.width, round(hero.height * hero_bottom)))
    resample = getattr(Image, 'Resampling', Image).LANCZOS
    hero = hero.resize((width, round(hero.height * width / hero.width)), resample)
    size = font_size or max(18, round(width * 0.033))
    if not 12 <= size <= width // 8:
        raise ValueError('字号过小或过大')
    font = ImageFont.truetype(choose_font(font_path), size)
    stroke = max(1, round(size / 14))
    padding = max(12, round(width * 0.018))
    rows = []
    for item in recipe['steps']:
        lines = wrap_text(item['text'], font, width - 2 * padding - 2 * stroke)
        height = max(round(width * 0.074), math.ceil(size * 1.4) * len(lines) + padding * 2)
        rows.append((lines, height))
    title_lines = wrap_text(recipe['title'], font, width - padding * 2)
    title_height = math.ceil(size * 1.4) * len(title_lines) + padding * 2
    if title_height > hero.height:
        raise ValueError('标题过长，无法放在主图底部')
    total = hero.height + sum(row[1] for row in rows)
    if total > 24000:
        raise ValueError('长图超过 24000px，请简化步骤或按菜拆分')
    canvas = Image.new('RGB', (width, total))
    canvas.paste(hero, (0, 0))
    draw_caption(canvas, title_lines, (0, hero.height - title_height, width, title_height), font, size, stroke)
    layout = {'width': width, 'height': total, 'hero_height': hero.height,
              'hero_frame': recipe['hero']['frame'], 'font_size': size, 'rows': []}
    y = hero.height
    for lines, height in rows:
        # A crop of the same hero provides every background. No extra step photos.
        band_height = min(height, hero.height)
        start = max(0, min(hero.height - band_height, round(hero.height * band_center - band_height / 2)))
        band = hero.crop((0, start, width, start + band_height))
        for offset in range(0, height, band_height):
            take = min(band_height, height - offset)
            canvas.paste(band.crop((0, 0, width, take)), (0, y + offset))
        draw_caption(canvas, lines, (0, y, width, height), font, size, stroke)
        layout['rows'].append({'y': y, 'height': height, 'lines': lines})
        y += height
    output.parent.mkdir(parents=True, exist_ok=True)
    # Sidecars are computed before writing to avoid malformed half-deliveries.
    md = markdown(recipe, index)
    canvas.save(output, **({'quality': 95, 'subsampling': 0} if output.suffix.lower() != '.png' else {}))
    output.with_suffix('.md').write_text(md, encoding='utf-8')
    output.with_suffix('.layout.json').write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
    return layout


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('命令参数无效，请用 --help 查看用法')


def main():
    parser = SafeArgumentParser(description='一张真实视频主图，下方排列中文菜谱步骤')
    parser.add_argument('recipe')
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--font')
    parser.add_argument('--font-size', type=int)
    parser.add_argument('--hero-bottom', type=float, default=1.0)
    parser.add_argument('--band-center', type=float, default=0.85)
    try:
        args = parser.parse_args()
        result = render(args.recipe, args.evidence, args.out, args.width,
                        args.font, args.font_size, args.hero_bottom, args.band_center)
        print(json.dumps({'status': 'rendered', 'width': result['width'],
                          'height': result['height'], 'steps': len(result['rows'])}, ensure_ascii=False))
    except ValueError as error:
        print('错误：' + str(error), file=sys.stderr)
        return 1
    except (KeyError, TypeError, AttributeError):
        print('错误：菜谱或证据结构无效，请按 recipe-format.md 检查字段', file=sys.stderr)
        return 1
    except OSError:
        print('错误：文件读取或写入失败，请检查输入文件、中文字体和输出目录权限', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    sys.exit(main())
