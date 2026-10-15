import ast
from dataclasses import dataclass, field

DANGEROUS_CALLS = {
    "eval": ("high", "eval() 可执行任意代码，存在注入风险"),
    "exec": ("high", "exec() 可执行任意代码，存在注入风险"),
    "compile": ("medium", "compile() 动态编译代码，需确认来源可信"),
    "__import__": ("medium", "__import__() 动态导入，可能绕过静态检查"),
    "globals": ("low", "globals() 暴露全局命名空间"),
    "locals": ("low", "locals() 暴露局部命名空间"),
    "getattr": ("low", "getattr() 动态属性访问，可能绕过检查"),
    "setattr": ("low", "setattr() 动态属性设置"),
}

DANGEROUS_ATTRS = {
    ("os", "system"): ("high", "os.system() 执行 shell 命令，存在命令注入风险"),
    ("os", "popen"): ("high", "os.popen() 执行 shell 命令，存在命令注入风险"),
    ("os", "execv"): ("high", "os.execv() 替换进程，危险"),
    ("os", "execve"): ("high", "os.execve() 替换进程，危险"),
    ("os", "execl"): ("high", "os.execl() 替换进程，危险"),
    ("os", "execlp"): ("high", "os.execlp() 替换进程，危险"),
    ("os", "execvp"): ("high", "os.execvp() 替换进程，危险"),
    ("os", "execvpe"): ("high", "os.execvpe() 替换进程，危险"),
    ("subprocess", "call"): ("medium", "subprocess.call() 执行外部命令，需检查 shell 参数"),
    ("subprocess", "run"): ("medium", "subprocess.run() 执行外部命令，需检查 shell 参数"),
    ("subprocess", "Popen"): ("medium", "subprocess.Popen() 执行外部命令，需检查 shell 参数"),
    ("subprocess", "check_output"): ("medium", "subprocess.check_output() 执行外部命令，需检查 shell 参数"),
    ("subprocess", "check_call"): ("medium", "subprocess.check_call() 执行外部命令，需检查 shell 参数"),
    ("pickle", "load"): ("high", "pickle.load() 反序列化任意对象，存在代码执行风险"),
    ("pickle", "loads"): ("high", "pickle.loads() 反序列化任意对象，存在代码执行风险"),
    ("yaml", "load"): ("high", "yaml.load() 未指定 Loader 可构造任意对象"),
    "marshal.loads": ("high", "marshal.loads() 反序列化风险"),
    ("shutil", "rmtree"): ("medium", "shutil.rmtree() 递归删除目录，需确认路径"),
    "open": ("low", "open() 文件操作，需确认路径来源"),
}

SUBPROCESS_SHELL_CALLS = {("subprocess", "run"), ("subprocess", "call"),
                          ("subprocess", "Popen"), ("subprocess", "check_output"),
                          ("subprocess", "check_call")}

DANGEROUS_IMPORTS = {"pickle", "marshal", "ctypes", "subprocess"}


@dataclass
class SecurityIssue:
    type: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str = ""


SUGGESTIONS = {
    "eval": "避免使用 eval，改用 ast.literal_eval 解析字面量或专用解析器",
    "exec": "避免使用 exec，重构为静态可分析的代码",
    "pickle": "改用 json 等安全格式序列化",
    "os.system": "改用 subprocess.run(args, shell=False) 并校验输入",
    "shell_true": "设置 shell=False 并以列表传参，对输入做白名单校验",
    "hardcoded_secret": "从环境变量或密钥管理服务读取密钥",
    "assert": "不要用 assert 做业务校验（生产环境 -O 会跳过）",
}


def detect_security(path: str, source: str) -> list[dict]:
    issues: list[dict] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return issues

    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported[name] = alias.name
                if alias.name in DANGEROUS_IMPORTS:
                    issues.append(_issue("dangerous_import", "medium", path, node.lineno,
                                         f"导入危险模块 {alias.name}",
                                         f"评估是否真的需要 {alias.name}，考虑更安全的替代"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in DANGEROUS_IMPORTS:
                issues.append(_issue("dangerous_import", "medium", path, node.lineno,
                                     f"从危险模块 {module} 导入",
                                     f"评估是否真的需要 {module}"))
            for alias in node.names:
                bound = f"{module}.{alias.name}" if module else alias.name
                imported[alias.asname or alias.name] = bound

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_CALLS:
                sev, msg = DANGEROUS_CALLS[func.id]
                issues.append(_issue(func.id, sev, path, node.lineno, msg,
                                     SUGGESTIONS.get(func.id, "")))
                if func.id == "eval":
                    issues.extend(_check_eval_args(path, node))
            elif isinstance(func, ast.Attribute):
                key = _attr_key(func, imported)
                if key in DANGEROUS_ATTRS:
                    sev, msg = DANGEROUS_ATTRS[key]
                    issues.append(_issue(f"{key[0]}.{key[1]}" if isinstance(key, tuple) else key,
                                         sev, path, node.lineno, msg,
                                         SUGGESTIONS.get(key[1] if isinstance(key, tuple) else key, "")))
                if key in SUBPROCESS_SHELL_CALLS:
                    issues.extend(_check_shell_true(path, node))
        if isinstance(node, ast.Assert) and _is_business_assert(node):
            issues.append(_issue("assert", "low", path, node.lineno,
                                 "使用 assert 做业务校验，生产环境可能被跳过",
                                 SUGGESTIONS["assert"]))

    issues.extend(_detect_hardcoded_secrets(path, source))
    seen = set()
    deduped = []
    for it in issues:
        k = (it["type"], it["line"], it["message"])
        if k not in seen:
            seen.add(k)
            deduped.append(it)
    return deduped


def _issue(type_, severity, file, line, message, suggestion="") -> dict:
    return {"type": type_, "severity": severity, "file": file, "line": line,
            "message": message, "suggestion": suggestion}


def _attr_key(node: ast.Attribute, imported: dict[str, str]) -> tuple:
    if isinstance(node.value, ast.Name):
        real = imported.get(node.value.id, node.value.id)
        parts = real.split(".")
        return (parts[0], node.attr)
    return ("", node.attr)


def _check_eval_args(path: str, node: ast.Call) -> list[dict]:
    if node.args and isinstance(node.args[0], ast.Name):
        return [_issue("eval", "high", path, node.lineno,
                       "eval() 参数为变量，注入风险更高",
                       SUGGESTIONS["eval"])]
    return []


def _check_shell_true(path: str, node: ast.Call) -> list[dict]:
    for kw in node.keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return [_issue("shell_true", "high", path, node.lineno,
                           "subprocess shell=True 存在命令注入风险",
                           SUGGESTIONS["shell_true"])]
    return []


def _is_business_assert(node: ast.Assert) -> bool:
    return not (isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Constant))


SECRET_PATTERNS = [
    ("password", "密码"),
    ("passwd", "密码"),
    ("secret", "密钥"),
    ("api_key", "API Key"),
    ("apikey", "API Key"),
    ("token", "Token"),
]


def _detect_hardcoded_secrets(path: str, source: str) -> list[dict]:
    import re
    issues = []
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for keyword, label in SECRET_PATTERNS:
            pattern = rf"({keyword})\s*=\s*['\"]([^'\"]{{4,}})['\"]"
            m = re.search(pattern, stripped, re.IGNORECASE)
            if m and m.group(2).lower() not in ("none", "true", "false", "your_key_here", "xxxx"):
                issues.append(_issue("hardcoded_secret", "high", path, i,
                                     f"疑似硬编码{label}",
                                     SUGGESTIONS["hardcoded_secret"]))
    return issues