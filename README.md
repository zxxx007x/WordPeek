# WordPeek 游戏词汇助手

WordPeek 是一个 Windows 端小工具：你按快捷键框选屏幕上的英文单词/短语，它会识别文字，并弹出中文意思、IPA 音标、音节、例句和游戏语境解释。

## 功能

- `F8` 框选屏幕区域，识别游戏 UI、图片或网页里的英文
- 本地游戏词库优先查询
- 本地没有的词可以调用 AI 补充
- 发音信息使用 IPA 音标和英文音节拆分，不使用中文谐音
- 支持官方 OpenAI API 或兼容 OpenAI 的中转 API
- 支持双屏虚拟桌面框选截图

## 怎么用

1. 双击 `run_wordpeek.bat`。
2. 按 `F8`。
3. 拖框圈住屏幕上的英文词，例如游戏 UI 里的 `parry`。
4. 弹窗会出现在鼠标附近，并显示解释；按 `Esc` 可以隐藏窗口。

也可以直接在输入框里打词，然后点“查一下”。

## AI 补充

框选识别游戏画面/图片文字，以及本地词库查不到时的自动补词，都需要 OpenAI API。

AI 结果会缓存到：

```text
data/ai_cache.json
```

开启方法：打开下面这个文件，把 key 填进去：

```text
data/api_keys.json
```

如果没有这个文件，复制：

```text
data/api_keys.example.json
```

然后重命名为：

```text
data/api_keys.json
```

格式是：

```json
{
  "openai_api_key": "这里粘贴你的 OpenAI API key",
  "openai_base_url": "https://api.openai.com/v1",
  "openai_model": "gpt-4o-mini",
  "openai_api_style": "responses"
}
```

如果没有填写 API key，程序仍然能查本地词库，只是不能框选识别游戏画面，也不会自动 AI 补词。

注意：`data/api_keys.json` 是你的本地密钥文件，已经被 `.gitignore` 忽略，不要上传到 GitHub。

详细说明见：

```text
API_SETUP.md
```

## 自己加词

本地词库在：

```text
data/vocab.json
```

你也可以查到 AI 结果后点“保存到本地词库”，以后就不用再请求 AI。

## 改快捷键

编辑：

```text
data/config.json
```

默认是：

```json
{
  "hotkey": {
    "modifiers": [],
    "key": "F8"
  }
}
```

如果快捷键和其他软件冲突，可以把 `key` 改成 `F9`、`F10`，或者把 `modifiers` 改成 `["CONTROL", "ALT"]`。

默认 `F8` 会进入屏幕框选识别模式。如果你想改回“复制当前选中文本再查”，把 `hotkey_action` 改成：

```json
"hotkey_action": "copy_selection"
```

## 隐私说明

框选识别会把你选择的屏幕区域截图发送给你配置的 AI API 服务商，用于识别里面的英文。请不要框选包含账号、密钥、聊天隐私或其他敏感信息的区域。
