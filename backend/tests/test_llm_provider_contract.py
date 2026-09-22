from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LLMProviderContractsTest(unittest.TestCase):
    def test_config_keeps_api_keys_secret_and_backwards_compatible(self):
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("llm_provider: str = \"auto\"", config)
        self.assertIn("llm_api_key: SecretStr = SecretStr(\"\")", config)
        self.assertIn("openai_api_key: str = \"\"", config)
        self.assertIn("ollama_model: str", config)

    def test_deepseek_and_generic_openai_compatible_are_supported(self):
        provider = (ROOT / "backend/app/llm_provider.py").read_text(encoding="utf-8")
        self.assertIn('"deepseek": ("https://api.deepseek.com", "deepseek-flash")', provider)
        self.assertIn('"qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus")', provider)
        self.assertIn('provider = "openai-compatible"', provider)
        self.assertIn('cfg.base_url + "/chat/completions"', provider)
        self.assertIn('cfg.base_url + "/models"', provider)
        self.assertIn('payload["thinking"] = {"type": "disabled" if tools', provider)

    def test_agent_and_streaming_use_provider_adapter_without_removing_ollama(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        native = (ROOT / "backend/app/native_stream.py").read_text(encoding="utf-8")
        self.assertIn('current_provider_name() != "ollama"', agent)
        self.assertIn("return chat_message(", agent)
        self.assertIn('current_provider_name() != "ollama"', native)
        self.assertIn("yield from stream_chat(", native)
        self.assertIn('settings.ollama_base_url.rstrip("/") + "/api/chat"', agent)
        self.assertIn("with httpx.stream(", native)

    def test_env_documents_deepseek_and_custom_provider(self):
        env = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
        self.assertIn("LLM_PROVIDER=deepseek", env)
        self.assertIn("LLM_MODEL=deepseek-flash", env)
        self.assertIn("LLM_PROVIDER=openai-compatible", env)
        self.assertIn("LLM_BASE_URL=https://your-provider.example/v1", env)


if __name__ == "__main__":
    unittest.main()
