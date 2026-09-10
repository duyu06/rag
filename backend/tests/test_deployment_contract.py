from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DeploymentContractsTest(unittest.TestCase):
    def test_compose_pins_qdrant_and_persists_model_cache(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("image: qdrant/qdrant:v1.19.1", compose)
        self.assertIn("hf_cache:/app/.cache/huggingface", compose)
        self.assertIn("hf_cache:", compose)
        self.assertIn("./backend/data:/app/data", compose)
        self.assertIn("OLLAMA_BASE_URL: http://host.docker.internal:11434", compose)

    def test_windows_deploy_script_validates_real_runtime(self):
        script = (ROOT / "scripts/deploy.ps1").read_text(encoding="utf-8")
        for marker in (
            "docker compose up -d --build",
            '"$OllamaApi/api/chat"',
            "ollama pull $Model",
            "scripts/release_smoke.py",
            '"--agent"',
            "scripts/init_demo.py",
            "docker compose logs --tail 120 qdrant backend frontend",
            "RandomNumberGenerator",
        ):
            self.assertIn(marker, script)

    def test_demo_initializer_is_idempotent_and_api_configurable(self):
        script = (ROOT / "scripts/init_demo.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("YAOKE_API"', script)
        self.assertIn('"--force"', script)
        self.assertIn('status.get("ready")', script)
        self.assertIn("skipping re-index", script)

    def test_ci_uses_same_qdrant_and_parses_deployment_files(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("image: qdrant/qdrant:v1.19.1", ci)
        self.assertIn("docker compose config", ci)
        self.assertIn("Validate Windows deployment script syntax", ci)
        self.assertIn("shell: pwsh", ci)

    def test_windows_deployment_guide_exposes_one_command_path(self):
        guide = (ROOT / "docs/DEPLOY_WINDOWS.md").read_text(encoding="utf-8")
        self.assertIn(".\\scripts\\deploy.ps1", guide)
        self.assertIn("release_smoke.py --agent", guide)
        self.assertIn("Demo 20/20 ready", guide)


if __name__ == "__main__":
    unittest.main()
