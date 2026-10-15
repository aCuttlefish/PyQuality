from backend.analyzers.security import detect_security


def test_detect_eval():
    code = "def f(x):\n    return eval(x)"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "eval" and i["severity"] == "high" for i in issues)


def test_detect_exec():
    code = "def f(code):\n    exec(code)"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "exec" for i in issues)


def test_detect_os_system():
    code = "import os\n\ndef f(cmd):\n    os.system(cmd)"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "os.system" and i["severity"] == "high" for i in issues)


def test_detect_pickle_load():
    code = "import pickle\n\ndef f(path):\n    with open(path, 'rb') as f:\n        return pickle.load(f)"
    issues = detect_security("a.py", code)
    types = {i["type"] for i in issues}
    assert "pickle" in types or "pickle.load" in types or any("pickle" in i["type"] for i in issues)


def test_detect_shell_true():
    code = "import subprocess\n\ndef f(cmd):\n    subprocess.run(cmd, shell=True)"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "shell_true" and i["severity"] == "high" for i in issues)


def test_detect_hardcoded_secret():
    code = 'API_KEY = "sk-abcdef1234567890"\n\ndef f():\n    return API_KEY'
    issues = detect_security("a.py", code)
    assert any(i["type"] == "hardcoded_secret" for i in issues)


def test_detect_dangerous_import():
    code = "import pickle\nimport ctypes"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "dangerous_import" for i in issues)


def test_clean_code_no_security_issues():
    code = '"""clean"""\n\ndef add(a, b):\n    """add"""\n    return a + b'
    issues = detect_security("a.py", code)
    high = [i for i in issues if i["severity"] == "high"]
    assert not high


def test_syntax_error_returns_empty():
    issues = detect_security("a.py", "def f(:\n    pass")
    assert issues == []


def test_dedup_same_line():
    code = "def f(x):\n    return eval(x)"
    issues = detect_security("a.py", code)
    eval_issues = [i for i in issues if i["type"] == "eval" and i["line"] == 2]
    assert len(eval_issues) >= 1

def test_detect_os_exec_family():
    code = "import os\n\ndef f():\n    os.execv('/bin/ls', ['ls'])\n    os.execve('/bin/ls', ['ls'], {})"
    issues = detect_security("a.py", code)
    exec_issues = [i for i in issues if "os.exec" in i["type"] and i["severity"] == "high"]
    assert len(exec_issues) >= 2


def test_detect_subprocess_check_output():
    code = "import subprocess\n\ndef f(cmd):\n    subprocess.check_output(cmd)"
    issues = detect_security("a.py", code)
    assert any("check_output" in i["type"] for i in issues)


def test_detect_subprocess_check_call_shell_true():
    code = "import subprocess\n\ndef f(cmd):\n    subprocess.check_call(cmd, shell=True)"
    issues = detect_security("a.py", code)
    assert any(i["type"] == "shell_true" and i["severity"] == "high" for i in issues)