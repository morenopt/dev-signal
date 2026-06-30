import subprocess
result = subprocess.run(
    ["uv", "run", "python", "test_devto_quick.py"],
    capture_output=True, text=True, encoding="utf-8"
)
with open("test_output.txt", "w", encoding="utf-8") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\nRETURN CODE: {result.returncode}\n")
