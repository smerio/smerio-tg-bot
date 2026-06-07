# Python Local Unit Testing Module Duplication Bug & Solution

This document details a common Python import path duplication bug encountered during local unit testing of packaged microservices/AWS Lambda functions, and how to avoid it.

---

## 🛑 The Bug: Duplicate Module Instances in `sys.modules`

### 1. Context (AWS Lambda Runtime)
In AWS Lambda, all source files located in the deployment package are extracted to the root path of the function's execution environment. Therefore, modules are imported relative to the root:
```python
# src/handler.py
import config
```

### 2. The Local Testing Conflict
When writing unit tests locally, tests are typically located in a separate directory (`tests/`) outside the `src/` directory. To import the source code under test, developers often set `PYTHONPATH` or write imports like:
```python
# tests/test_handler.py
from src import handler, config
```

If `PYTHONPATH` includes `src` (to allow `handler.py` to find `config.py` via `import config`), Python's import system resolves imports in two different ways depending on the import path prefix:
1. `src/handler.py` imports `config` using the top-level module name `"config"`.
2. `tests/test_handler.py` imports `src.config` using the package prefix path `"src.config"`.

Because Python tracks loaded modules by key in `sys.modules`, this results in **two distinct module instances** in memory:
* `sys.modules["config"]`
* `sys.modules["src.config"]`

### 3. The Consequences
* **State Inconsistency**: Any modification to module-level variables or configuration states made by the tests (e.g. `config.ALLOWED_TELEGRAM_USER_ID = 5139816564`) will only apply to `src.config` in the test file, but the handler file will read from the separate `config` module instance, resulting in authentication failures.
* **Mocking Failures**: Mocking (e.g., `@patch("config.VARIABLE")`) might target the wrong module instance, causing tests to use the real environment variables instead of mocked values.

---

## 💡 The Solution: Top-Level Test Imports and PYTHONPATH

To resolve module duplication and mirror the production Lambda environment exactly, all local unit tests must import source modules using their production top-level names rather than their package directory paths.

### 1. Test Code Implementation
Instead of using `from src import ...`, import modules directly as they will be resolved at runtime:
```python
# tests/test_handler.py - Correct
import handler
import config
import payload_utils
```

### 2. Test Execution Environment
Ensure the source directory (e.g., `src/`) is added to the python path during test execution so the interpreter resolves direct module imports correctly:
```bash
PYTHONPATH=src python -m unittest discover tests
```

By adding `src` to the `PYTHONPATH`, both the test files and the production files resolve imports using the exact same keys (e.g., `"config"`, `"handler"`), ensuring a single module instance exists in `sys.modules` and state/mocking updates synchronize perfectly.
