# 菜谱输入与证据

每个 JSON 只包含一道菜。`hero.frame` 引用准备脚本生成的真实帧 ID；渲染器从 `evidence.json` 所在目录读取相对帧路径。所有步骤、食材和备注的 `evidence` 数组至少包含一个已存在的字幕/ASR片段或帧 ID。

```json
{
  "version": 1,
  "title": "番茄炒蛋",
  "hero": {"frame": "f001"},
  "ingredients": [
    {"name": "番茄", "amount": "2个", "evidence": ["s001"]},
    {"name": "鸡蛋", "amount": "3个", "evidence": ["s002"]},
    {"name": "盐", "amount": "少许", "evidence": ["s002"]}
  ],
  "steps": [
    {"text": "1. 番茄切块，鸡蛋加少许盐打散。", "evidence": ["s001", "s002"]},
    {"text": "2. 油热后炒鸡蛋，凝固后盛出。", "evidence": ["s003"]},
    {"text": "3. 番茄炒出汁，加一点糖。", "evidence": ["s004"]},
    {"text": "4. 倒回鸡蛋，翻匀即可。", "evidence": ["s005"]}
  ],
  "notes": []
}
```

这是结构示例，ID和内容必须替换成当前视频证据。`ingredients` 可省略；它仅写入附带的 Markdown，不会额外绘制食材表。`amount` 没有依据时整个字段省略。`steps[].text` 包含希望绘制的序号；渲染器不自动添加重复序号。`notes` 用于冲突等核对备注，写入 Markdown，默认不占长图。

`evidence.json` 的结构如下（由 prepare 生成，不手造真实帧记录）：

```json
{
  "source": {"kind": "local_video", "filename": "video.mp4", "duration_seconds": 42.0},
  "segments": [{"id": "s001", "start": 0.0, "end": 5.0, "text": "两个番茄切块", "kind": "subtitle"}],
  "frames": [{"id": "f001", "time": 2.0, "path": "frames/f001.jpg"}],
  "audio_path": "audio.wav",
  "transcript_status": "subtitle"
}
```

只给字幕时可以先提取文字菜谱；没有真实主图，不调用长图渲染。补帧产生的新 evidence 可合并到经审核的新文件，必要时重命名 ID，保持时间和帧路径真实，不修改原始字幕索引来掩盖冲突。

重叠的 VTT 滚动字幕会生成去重的 `text` 索引；原句不同于索引时保存在 `raw_text`，文字稿优先显示原句。核对食材和用量时读取原句，不能只用去重后的半句推断。普通 SRT 和没有时间重叠的字幕保留全文。

渲染器校验引用和时间范围，不判断食材、数字和步骤是否语义匹配；这一核对由 Agent 完成。时间点是视频位置，不是做菜时长。
