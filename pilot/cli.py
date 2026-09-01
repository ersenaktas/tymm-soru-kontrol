from __future__ import annotations
import argparse, asyncio
from pathlib import Path
from .engine import ReviewEngine
from .models import ReviewJob
from .provider import FakeNotebookProvider
from .rules import init_package

def main():
    p=argparse.ArgumentParser(); p.add_argument("--fake",action="store_true"); p.add_argument("--file",type=Path); p.add_argument("--init-rules",action="store_true"); p.add_argument("--subject-file",type=Path); a=p.parse_args()
    if a.init_rules: init_package(Path("rules/rules.bin")); return
    if not a.fake or not a.file: p.error("pilot için --fake --file veya --init-rules kullanın")
    provider=FakeNotebookProvider(); asyncio.run(provider.login())
    result=ReviewEngine(provider,Path("rules/rules.bin"),Path("outputs")).run_many([ReviewJob(a.file, subject_path=a.subject_file)])[0]
    print(result.error or f"Raporlar: {result.docx_path}, {result.pdf_path}")
if __name__ == "__main__": main()
