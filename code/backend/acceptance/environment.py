"""运行前诊断：只报告配置存在性，不把配置了密钥描述为已连接模型。"""
import platform
import subprocess

from backend.acceptance import llm_provider, runner


def inspect_environment():
    runner.reset_backend_cache()
    backend = runner.detect_execution_backend()
    image_ready = False
    if backend.name == "DOCKER" and backend.available:
        try:
            image_ready = subprocess.run(
                ["docker", "image", "inspect", runner.DOCKER_IMAGE],
                capture_output=True, timeout=10,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    actions = []
    if not llm_provider.is_available():
        actions.append("设置 DEEPSEEK_API_KEY 后重启服务可自动生成标准和诊断提示词；也可手动填写案例并确认")
    if not backend.available:
        actions.append("启动 Docker Desktop 后点击刷新环境；动态测试在环境可用前不会执行")
    elif backend.name == "DOCKER" and not image_ready:
        actions.append(f"先运行 docker pull {runner.DOCKER_IMAGE} 准备执行镜像")
    elif backend.name == "HOST_SUBPROCESS_DEV":
        actions.append("当前是可信代码的本地演示模式；正式运行请使用 Docker")
    return {
        "model_configured": llm_provider.is_available(),
        "model_connection": "NOT_PROBED",
        "python_version": platform.python_version(),
        "execution_backend": backend.name, "execution_available": backend.available,
        "execution_detail": backend.detail, "docker_image": runner.DOCKER_IMAGE,
        "image_ready": image_ready,
        "ready_for_execution": backend.available and (backend.name != "DOCKER" or image_ready),
        "actions": actions,
    }
