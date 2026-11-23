param(
    [switch]$LocalDemo,
    [switch]$Install,
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ($Install) {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 虚拟环境' }
    }
    & $pythonPath -m pip install -r backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
}
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
if ($LocalDemo) {
    $env:PYQ_ACCEPTANCE_ALLOW_HOST = '1'
    Write-Host '运行模式：本地可信演示。仅执行你信任的代码。'
} else {
    Remove-Item Env:PYQ_ACCEPTANCE_ALLOW_HOST -ErrorAction SilentlyContinue
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw '请先启动 Docker Desktop，再执行此脚本' }
    docker image inspect python:3.10-slim *> $null
    if ($LASTEXITCODE -ne 0) {
        docker pull python:3.10-slim
        if ($LASTEXITCODE -ne 0) { throw '执行镜像准备失败，请检查 Docker 网络' }
    }
}
Write-Host "打开 http://127.0.0.1:$Port/acceptance.html"
& $pythonPath -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
