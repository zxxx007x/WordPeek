# WordPeek API Key 设置

这个文件说明怎么让 WordPeek 识别游戏画面里的英文。

## 为什么要填 API key

游戏 UI、图片、截图里的英文不是可复制文字。WordPeek 需要先把你框选的画面发给 AI 视觉模型，让它识别出英文，然后再查词和解释。

## 现在怎么做

打开这个文件：

```text
F:\AI_Codex\WordPeek\data\api_keys.json
```

如果文件不存在，复制：

```text
F:\AI_Codex\WordPeek\data\api_keys.example.json
```

然后重命名为：

```text
api_keys.json
```

把你的 OpenAI API key 填到 `openai_api_key` 里面：

```json
{
  "openai_api_key": "这里粘贴你的 OpenAI API key",
  "openai_base_url": "https://api.openai.com/v1",
  "openai_model": "gpt-4o-mini",
  "openai_api_style": "responses"
}
```

保存文件，然后关闭并重新打开 WordPeek：

```text
F:\AI_Codex\WordPeek\run_wordpeek.bat
```

之后使用：

```text
按 F8 -> 拖框圈住英文 -> 松开鼠标 -> 等识别和解释
```

## 安全提醒

API key 只放在你自己电脑本地，不要发到聊天里，也不要截图给别人。

如果以后想换成 DeepSeek、MiMo 或其他模型，可以继续在这里加配置项，例如：

```json
{
  "openai_api_key": "",
  "openai_model": "gpt-4o-mini",
  "text_provider": "openai",
  "ocr_provider": "openai"
}
```

当前版本先使用 OpenAI 做屏幕文字识别和 AI 补词。

## 如果你用的是中转 API

中转通常会给你两个东西：

```text
API Key
Base URL
```

把它们填到：

```text
F:\AI_Codex\WordPeek\data\api_keys.json
```

示例：

```json
{
  "openai_api_key": "你的中转 key",
  "openai_base_url": "https://你的中转地址/v1",
  "openai_model": "中转支持的视觉模型名",
  "openai_api_style": "chat_completions"
}
```

如果你的中转明确支持 OpenAI Responses API，可以用：

```json
"openai_api_style": "responses"
```

如果你的中转只说“兼容 OpenAI API”或“兼容 ChatGPT API”，通常先用：

```json
"openai_api_style": "chat_completions"
```

注意：框选识别需要模型支持图片输入。中转如果只支持纯文本模型，就只能做词汇解释，不能做截图识别。
