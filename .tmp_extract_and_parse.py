"""Extract harness heredoc from SSM YAML and ast.parse it."""
import ast
import textwrap

YAML_PATH = "database-blocking-locks/database-blocking-locks-automation.yaml"
HEREDOC_OPEN = "cat > /tmp/blocking_locks_harness.py << 'PYTHON_EOF'"
HEREDOC_CLOSE = "PYTHON_EOF"

with open(YAML_PATH, "r", encoding="utf-8") as fh:
    lines = fh.readlines()

open_idx = None
close_idx = None
for idx, line in enumerate(lines):
    if open_idx is None and HEREDOC_OPEN in line:
        open_idx = idx
        continue
    if open_idx is not None and line.strip() == HEREDOC_CLOSE:
        close_idx = idx
        break

assert open_idx is not None and close_idx is not None, (open_idx, close_idx)

body = "".join(lines[open_idx + 1:close_idx])
dedented = textwrap.dedent(body)

with open("/tmp/blocking_locks_harness.py", "w", encoding="utf-8") as fh:
    fh.write(dedented)

ast.parse(dedented)
print("ast.parse OK; %d lines" % dedented.count("\n"))
